"""Synthetic-only checks against an explicitly isolated candidate API.

Never prints authentication, form inputs, model answers or report narratives.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'backend'))
from app.services import expert_risk
from performance_benchmark import build_cases, verify_before_login


def run(client, base, expected_db, record):
    verify_before_login(client, base, expected_db)
    setup = client.get('/api/setup/status').json()
    password = os.environ['ELEVATOR_BENCH_PASSWORD']
    if setup.get('initialized') is False:
        response = client.post('/api/setup/init', json={
            'display_name':'提示词保护验收', 'username':'prompt-guard-test', 'password':password})
    else:
        response = client.post('/api/auth/login', json={'username':'prompt-guard-test', 'password':password})
    response.raise_for_status()
    client.headers['Authorization'] = 'Bearer '+response.json()['token']
    catalog = client.get('/api/report/jte-items').json()['items']
    form = {'clientName':'隔离测试委托单位', 'userName':'隔离测试使用单位',
            'deviceCategory':'曳引驱动电梯', 'productNo':'GUARD-SYNTHETIC', 'instruments':'/', 'basis':'/'}

    def save(items):
        created = client.post('/api/reports', json={})
        created.raise_for_status()
        report = created.json()['report']
        saved = client.put('/api/reports/'+report['id'], json={
            'form':form, 'items':items, 'version':report['version']})
        saved.raise_for_status()
        return report['id']

    results = []
    for case in build_cases(catalog):
        rid = save(case['items'])
        started = time.perf_counter()
        response = client.post('/api/reports/'+rid+'/generate', json={'use_llm':True})
        response.raise_for_status()
        report = response.json()['report']
        provenance = report['provenance']
        assert provenance['llm_status'] == 'success' and provenance['llm_used'] is True, provenance.get('llm_error_code')
        assert report['score'] == (100 if case['name'] == 'all_fit' else 0)
        assert provenance['assessment_complete'] is True
        calls = report['performance']['model_calls']
        assert len(calls) == (2 if case['name'] == 'natural_language' else 1)
        assert all(call['status'] == 'ok' and call['runtime']['run_status'] == 'finished' for call in calls)
        if case['name'] != 'all_fit':
            for no in ('1.7','16.1','16.6'):
                selected = report['risks'][no]['selected_risks']
                source = {risk['key']:risk for risk in expert_risk.options(no)}
                assert selected and all(risk['text'] == source[risk['key']]['text']
                    and risk['measure'] == source[risk['key']]['measure'] for risk in selected)
            assert report['risks']['16.1']['selected_risks'][0]['key'] == expert_risk.options('16.1')[31]['key']
        row = dict(case=case['name'], report_id=rid, status='ok', score=report['score'],
                   http_ms=round((time.perf_counter()-started)*1000,3), performance=report['performance'])
        record(row)
        results.append(row)

    # Valid full catalog with many selectable risks: preserve facts, refuse the model call.
    many = [{'no':item['no'], 'result':'unfit' if item['opts'] else 'fit',
             'reasons':item['opts'], 'other_text':''} for item in catalog]
    rid = save(many)
    response = client.post('/api/reports/'+rid+'/generate', json={'use_llm':True})
    response.raise_for_status()
    report = response.json()['report']
    assert report['provenance']['llm_error_code'] == 'context_budget_exceeded'
    assert report['provenance']['llm_used'] is False
    blocked = report['performance']['model_calls']
    assert len(blocked) == 1 and blocked[0]['http_status'] is None and blocked[0]['http_ms'] == 0
    for item in many:
        if item['result'] == 'unfit':
            expected = expert_risk.select(item['no'], item['reasons'])
            assert report['risks'][item['no']]['selected_risks'] == expected
    record(dict(case='many_risks_blocked',report_id=rid,status='ok',performance=report['performance']))

    # The 500-character field limit is a separate API guard, not a token estimate.
    original = deepcopy(build_cases(catalog)[0]['items'])
    rid = save(original)
    extreme = deepcopy(original)
    text = chr(0x10ffff)*501
    next(item for item in extreme if item['no']=='16.1').update(result='unfit',other_text=text)
    version = client.get('/api/reports/'+rid).json()['report']['version']
    response = client.put('/api/reports/'+rid, json={'form':form,'items':extreme,'version':version})
    assert response.status_code == 422
    saved = client.get('/api/reports/'+rid).json()['report']
    assert saved['status'] == 'draft' and saved['report_no'] is None
    assert saved['items'] == original
    record(dict(case='oversize_field_rejected_draft_preserved',report_id=rid,status='ok',http_status=response.status_code))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--expected-db', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    def record(row):
        with (args.output/'samples.jsonl').open('a', encoding='utf8') as output:
            output.write(json.dumps(row,ensure_ascii=False)+'\n')
            output.flush()
            os.fsync(output.fileno())
        print(json.dumps({key:row[key] for key in ('case','status','http_ms') if key in row}),flush=True)
    with httpx.Client(base_url=args.base,timeout=180,trust_env=False) as client:
        run(client,args.base,args.expected_db,record)


if __name__ == '__main__': main()
