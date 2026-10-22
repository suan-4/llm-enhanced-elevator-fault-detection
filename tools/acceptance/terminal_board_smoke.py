"""Real model and LibreOffice checks, restricted to an isolated EM-R16 candidate."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[2]
if not str(ROOT).startswith('/userdata/releases/terminal-ui-') or ROOT.name != 'candidate':
    raise RuntimeError('Run only inside an isolated terminal-ui release candidate')
QA = ROOT / 'output/terminal-ui-acceptance'
QA.mkdir(parents=True, exist_ok=True)
os.environ.update(SQLITE_PATH=str(QA/'test.db'), EXPORT_DIR=str(QA/'exports'),
                  RECOVERY_KEY_PATH=str(QA/'recovery.key'), BACKUP_DIR=str(QA/'backup'))
sys.path.insert(0, str(ROOT/'backend'))
from app import db
from app.services import auth_service, expert_risk, report_export, report_workflow as wf


def command(*args):
    return subprocess.check_output(args, text=True, timeout=90)


def main():
    if (QA/'test.db').exists():
        raise RuntimeError('Use a fresh candidate database, do not rerun over previous evidence')
    db.init_db()
    actor, _ = auth_service.init_system(display_name='板端隔离验收', username='acceptance', password='Acceptance2026!')
    catalog = json.loads(wf.ITEMS_PATH.read_text())['items']
    ordered = sorted(catalog, key=lambda item: item['no'] != '1.9')
    results = []
    for label, count in [('all-fit', 0), ('multiple-risks', 3), ('long-32-risks', 32)]:
        report = wf.create_draft(actor=actor)
        assert len(report['items']) == 66 and all(i['result'] == 'fit' for i in report['items'])
        items = []
        for index, entry in enumerate(ordered):
            no = entry['no']
            reasons = [r['text'] for r in expert_risk.options(no)[:3 if count == 3 else 1]] if index < count else []
            items.append(dict(no=no, result='unfit' if index < count else 'fit', reasons=reasons, other_text=''))
        wf.save_content(report['id'], actor=actor, items=items,
                        form=dict(clientName='板端整改隔离验收（非正式检验）', userName='测试单位',
                                  deviceCategory='/', deviceVariety='曳引驱动乘客电梯', productNo=label,
                                  assessDate='2026-10-21', instruments='/', basis='/'))
        start = monotonic()
        report = asyncio.run(wf.generate(report['id'], use_llm=count == 0, actor=actor))
        assert report['provenance']['assessment_complete'], report['provenance']['assessment_issues']
        if count == 0:
            assert report['provenance']['llm_used'], report['provenance'].get('llm_error')
        result = dict(scenario=label, generation_ms=round((monotonic()-start)*1000),
                      llm_used=report['provenance']['llm_used'], exports=[])
        for fmt in ('docx', 'pdf'):
            info = report_export.export_report(report_id=report['id'], version=report['version'],
                result_digest=report['provenance']['result_digest'], fmt=fmt, filename=label, actor=actor)
            assert hashlib.sha256(Path(info['path']).read_bytes()).hexdigest() == info['sha256']
            result['exports'].append(info)
            if fmt != 'pdf':
                continue
            pages = int(re.search(r'Pages:\s*(\d+)', command('pdfinfo', info['path']))[1])
            raw = command('pdftotext', '-raw', info['path'], '-')
            content = ''.join(raw.split())
            text_pages = [page for page in raw.split('\f') if page.strip()]
            assert len(text_pages) == pages
            first, second, third = [''.join(page.split()) for page in text_pages[:3]]
            assert '质量体系文件编号' in first and '设备品种' in first and '曳引驱动乘客电梯' in first
            assert '注意事项' in second and '涂改无效' in second and '联系电话' in second
            assert '委托单位名称' in third and '设备类别' in third
            for index, page in enumerate(text_pages, 1):
                assert re.search(rf'第\s*{index}\s*页\s*共\s*{pages}\s*页', page), (label, index)
            for item in catalog:
                assert re.search(r'(?<!\d)' + re.escape(item['no']) + r'(?!\d)', raw), item['no']
            for risk in report['risks'].values():
                for detail in risk.get('selected_risks', []):
                    assert ''.join(detail['text'].split()) in content, detail['text']
                    assert ''.join(detail['measure'].split()) in content, detail['measure']
            result['pdf_pages'] = pages
            result['content_and_page_numbers_verified'] = True
        assert wf.get_report(report['id'])['status'] == 'filed'
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    (QA/'board-smoke.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
