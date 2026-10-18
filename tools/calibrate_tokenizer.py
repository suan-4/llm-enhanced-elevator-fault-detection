"""Calibrate pinned local tokenization against the already-running RKLLM.

Only synthetic probes are sent. No reports/accounts/databases are written.
Evidence contains hashes/counts, never prompts or model answers.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.services.prompt_budget import ModelInputError, calibration_profile, load_tokenizer


def run_calibration(client, tokenizer, *, model_id, expected_sha, context_size,
                    template_reserve, probes, record):
    def verify_identity():
        response = client.get('/v1/models')
        response.raise_for_status()
        if model_id not in [row.get('id') for row in response.json().get('data', [])]:
            raise ModelInputError('model_mismatch', '校准目标模型不匹配')
    verify_identity()
    samples = []
    for group, text in probes:
        count = len(tokenizer.encode(text, add_special_tokens=False).ids)
        if count+template_reserve+1 > context_size:
            raise ModelInputError('context_budget_exceeded', '校准样本超出上下文；未截断、未发送')
        response = client.post('/v1/chat/completions', json={
            'model': model_id, 'messages': [{'role': 'user', 'content': text}],
            'stream': False, 'enable_thinking': False, 'tools': None, 'max_tokens': 1})
        response.raise_for_status()
        runtime = response.json().get('performance') or {}
        actual = runtime.get('prefill_tokens')
        row = dict(group=group, text_sha256=hashlib.sha256(text.encode('utf8')).hexdigest(),
                   input_tokens=count, sdk_input_tokens=actual,
                   sdk_finished=runtime.get('run_status') == 'finished')
        # Checkpoint before validation so failed observations are not discarded.
        record(row)
        if (not row['sdk_finished'] or not isinstance(actual, int) or isinstance(actual, bool)
                or not 0 <= actual-count <= template_reserve or actual >= context_size):
            raise ModelInputError('tokenizer_uncalibrated', 'SDK未完成或分词差异超出预留；未生成校准文件')
        samples.append(row)
    verify_identity()
    return calibration_profile(samples, tokenizer_sha256=expected_sha, model_id=model_id,
                               context_size=context_size, template_reserve=template_reserve)


def synthetic_probes():
    from app.services import expert_risk, risk_rules
    from app.services.llm_service import build_content
    from app.services.report_workflow import _narrative_prompt
    from acceptance.performance_benchmark import build_cases
    catalog = expert_risk.enrich_items(json.loads((ROOT/'backend/app/data/jte_items.json').read_text(encoding='utf8'))['items'])
    probes = [('chinese', '只回答好。电梯机房、制动器与门系统安全评估。'),
              ('english', 'Only reply OK. Elevator safety inspection and risk assessment.'),
              ('digits_symbols', '只回答OK。1234567890 2026-10-18 16.1 GB/T 7588.1—2020 ⅠⅡⅢ / + % ≤ ≥')]
    for case in build_cases(catalog):
        risks = {}
        for item in case['items']:
            selected = expert_risk.select(item['no'], item['reasons']) if item['result'] == 'unfit' else []
            if item['other_text']:
                probes.append(('report_match_risk', build_content(expert_risk.matching_prompt(item['no'], item['other_text']))))
                # Known synthetic fixture, not a business/model matching result.
                selected = [expert_risk.options(item['no'])[31]]
            risk = expert_risk.assess(item['no'], item['result'], selected)
            if risk is not None:
                risks[item['no']] = risk
        score = risk_rules.score_of([r['category'] for r in risks.values()])
        unfit = [item for item in case['items'] if item['result'] == 'unfit']
        probes.append(('report_'+case['name'], build_content(_narrative_prompt({}, unfit, risks, score, risk_rules.grade_of(score)))))
    return probes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:18080')
    parser.add_argument('--output', type=Path, required=True, help='New evidence directory; must not exist')
    args = parser.parse_args()
    url = urlsplit(args.base)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.username or url.password:
        parser.error('Only loopback HTTP model endpoints are supported')
    source = json.loads((ROOT/'backend/app/data/tokenizer-source.json').read_text(encoding='utf8'))
    sha = source['files']['tokenizer.json']['sha256']
    tokenizer = load_tokenizer(ROOT/'backend/data/tokenizers/qwen3.5-4b/tokenizer.json', sha)
    probes = synthetic_probes()
    args.output.mkdir(parents=True, exist_ok=False)
    def record(row):
        with (args.output/'observations.jsonl').open('a', encoding='utf8') as output:
            output.write(json.dumps(row, ensure_ascii=False)+'\n')
            output.flush()
            os.fsync(output.fileno())
        print(json.dumps(row, ensure_ascii=False), flush=True)
    try:
        with httpx.Client(base_url=args.base, timeout=180, trust_env=False) as client:
            profile = run_calibration(client, tokenizer, model_id='Qwen3.5-4B_W8A8_RK3588',
                expected_sha=sha, context_size=4096, template_reserve=128, probes=probes, record=record)
        with (args.output/'calibration.json').open('x', encoding='utf8') as output:
            json.dump(profile, output, ensure_ascii=False, indent=2)
        print('Calibration complete; profile not automatically deployed.', flush=True)
    except Exception as error:
        (args.output/'failure.json').write_text(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),
            'error_type':type(error).__name__, 'code':getattr(error,'code','calibration_failed')})+'\n', encoding='utf8')
        raise


if __name__ == '__main__':
    main()
