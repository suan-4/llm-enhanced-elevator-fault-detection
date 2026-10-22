"""Serial benchmark against a verified isolated board API. Never accepts production DB.

Credentials: ELEVATOR_BENCH_USER / ELEVATOR_BENCH_PASSWORD (synthetic account only).
Raw results contain measurements, never prompts, responses, passwords or bearer tokens.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path, PurePosixPath
import statistics
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def distribution(values):
    values=[v for v in values if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)]
    if not values: return None
    return {'n':len(values),'mean':round(statistics.mean(values),3),
            'median':round(statistics.median(values),3),'min':round(min(values),3),'max':round(max(values),3)}


def summarize(samples):
    output={}
    measured=[s for s in samples if s.get('phase')=='measurement']
    for name in sorted({s['case'] for s in measured}):
        rows=[s for s in measured if s['case']==name]
        successful=[s for s in rows if s['status']=='ok']
        degraded=sum(s['status']=='degraded' for s in rows)
        entry={'attempts':len(rows),'successful':len(successful),'degraded':degraded,
               'failed':len(rows)-len(successful)-degraded,'success_rate':len(successful)/len(rows),
               'http_ms':distribution([s.get('http_ms') for s in successful]),
               'backend_ms':distribution([s.get('performance',{}).get('total_ms') for s in successful])}
        purposes={c['purpose'] for s in successful for c in s.get('performance',{}).get('model_calls',[])}
        entry['model_calls']={}
        for purpose in sorted(purposes):
            calls=[c for s in successful for c in s.get('performance',{}).get('model_calls',[]) if c['purpose']==purpose]
            entry['model_calls'][purpose]={field:distribution([(c.get('runtime') or {}).get(field) for c in calls])
                for field in ('prefill_time_ms','prefill_tokens','generate_time_ms','generate_tokens',
                              'first_output_ms','model_run_ms','generate_tokens_per_s','prefill_tokens_per_s','memory_usage_mb')}
            entry['model_calls'][purpose]['http_ms']=distribution([c.get('http_ms') for c in calls])
        output[name]=entry
    return output


def validate_target(base, expected_db, info=None):
    url=urlsplit(base)
    path=PurePosixPath(expected_db)
    if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost') or url.port==8081:
        raise ValueError('Benchmark requires a loopback non-production API')
    if (not str(path).startswith('/userdata/releases/') or 'benchmark' not in path.parts
            or path.name!='performance-benchmark.db' or '..' in path.parts):
        raise ValueError('Expected DB must be the dedicated release benchmark database')
    if info is not None and info.get('db',{}).get('path')!=str(path):
        raise ValueError('Server database is not the explicitly selected isolated benchmark DB')


def build_cases(catalog):
    items=[{'no':i['no'],'result':'fit','reasons':[],'other_text':''} for i in catalog]
    options={i['no']:i['opts'] for i in catalog}
    selected=deepcopy(items)
    by_no={i['no']:i for i in selected}
    by_no['1.9']['result']='na'
    for no, indices in [('1.7',[0,1]),('16.1',[31]),('16.6',[12])]:
        by_no[no].update(result='unfit',reasons=[options[no][index] for index in indices])
    natural=deepcopy(selected)
    next(i for i in natural if i['no']=='16.1').update(reasons=[],other_text='控制柜的散热风道被灰尘堵住，电气元件温度升高。')
    return [{'name':'all_fit','items':items},{'name':'selected_risks','items':selected},{'name':'natural_language','items':natural}]


def verify_before_login(client,base,expected_db):
    """Read-only identity check before authentication (which itself writes DB)."""
    response=client.get('/api/health')
    response.raise_for_status()
    validate_target(base,expected_db,{'db':{'path':response.json().get('benchmark_db')}})


def pending_work(cases,repeat,samples):
    completed=[(s['case'],s['index']) for s in samples if s.get('phase')=='measurement']
    if len(completed)!=len(set(completed)):
        raise ValueError('Duplicate measurement identities; preserve raw data and investigate')
    return [(case,index) for index in range(1,repeat+1) for case in cases
            if (case['name'],index) not in completed]


def resources():
    def read(path):
        try: return Path(path).read_text().strip()
        except OSError: return None
    memory={}
    for line in (read('/proc/meminfo') or '').splitlines():
        if line.split(':')[0] in ('MemAvailable','MemFree','SwapTotal','SwapFree'):
            key,value=line.split(':',1)
            memory[key+'_kb']=int(value.strip().split()[0])
    temps={}
    for path in Path('/sys/class/thermal').glob('thermal_zone*'):
        value=read(path/'temp')
        if value and value.lstrip('-').isdigit(): temps[read(path/'type') or path.name]=int(value)/1000
    frequencies={}
    for path in Path('/sys/devices/system/cpu/cpufreq').glob('policy*'):
        value=read(path/'scaling_cur_freq')
        if value and value.isdigit(): frequencies[path.name+'_khz']=int(value)
    for path in Path('/sys/class/devfreq').glob('*'):
        if 'npu' in path.name.lower():
            value=read(path/'cur_freq')
            if value and value.isdigit(): frequencies['npu_hz']=int(value)
    return {'memory':memory,'temperatures_c':temps,'frequencies':frequencies,'loadavg':read('/proc/loadavg')}


def run_sample(client,case,index,phase):
    sample={'case':case['name'],'index':index,'phase':phase,'utc':datetime.now(timezone.utc).isoformat(),
            'status':'error','before':resources()}
    started=time.perf_counter()
    try:
        created=client.post('/api/reports',json={})
        created.raise_for_status()
        report=created.json()['report']
        form={'clientName':'性能测试委托单位','userName':'性能测试使用单位','deviceCategory':'曳引驱动电梯',
              'productNo':'PERFORMANCE-SYNTHETIC','instruments':'/','basis':'/'}
        save_started=time.perf_counter()
        saved=client.put('/api/reports/'+report['id'],json={'form':form,'items':case['items'],'version':report['version']})
        saved.raise_for_status()
        sample['save_http_ms']=round((time.perf_counter()-save_started)*1000,3)
        started=time.perf_counter()
        response=client.post('/api/reports/'+report['id']+'/generate',json={'use_llm':True})
        sample['http_ms']=round((time.perf_counter()-started)*1000,3)
        sample['http_status']=response.status_code
        if response.is_success:
            generated=response.json()['report']
            sample.update(report_id=report['id'],performance=generated.get('performance',{}),
                          score=generated['score'],grade=generated['grade'],
                          llm_used=generated['provenance'].get('llm_used',False),
                          assessment_complete=generated['provenance'].get('assessment_complete',False))
            sample['status']='ok' if sample['llm_used'] and sample['assessment_complete'] else 'degraded'
            expected=100 if case['name']=='all_fit' else 0
            if generated['score']!=expected: sample['status']='wrong_result'
            sample['model_error_present']=bool(generated['provenance'].get('llm_error'))
        else:
            sample['failure_reason']='generation_http_error'
    except Exception as error:
        sample['http_ms']=round((time.perf_counter()-started)*1000,3)
        sample['error_type']=type(error).__name__
    sample['after']=resources()
    return sample


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',default='http://127.0.0.1:18083')
    parser.add_argument('--expected-db',required=True)
    parser.add_argument('--repeat',type=int,default=5)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true',help='Append only missing measurements; never retry recorded failures')
    args=parser.parse_args()
    validate_target(args.base,args.expected_db)
    if args.repeat<1: parser.error('repeat must be positive')
    if args.resume:
        samples=[json.loads(line) for line in (args.output/'samples.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    else:
        args.output.mkdir(parents=True,exist_ok=False)
        samples=[]
    run_id=uuid4().hex
    boot_path=Path('/proc/sys/kernel/random/boot_id')
    boot_id=boot_path.read_text().strip() if boot_path.exists() else None
    with httpx.Client(base_url=args.base,timeout=180,trust_env=False) as client:
        verify_before_login(client,args.base,args.expected_db)
        login=client.post('/api/auth/login',json={'username':os.environ.get('ELEVATOR_BENCH_USER','perf-benchmark'),
                         'password':os.environ.get('ELEVATOR_BENCH_PASSWORD','BoardPerf2026')})
        login.raise_for_status()
        client.headers['Authorization']='Bearer '+login.json()['token']
        info=client.get('/api/system/info')
        info.raise_for_status()
        validate_target(args.base,args.expected_db,info.json())
        catalog=client.get('/api/report/jte-items')
        catalog.raise_for_status()
        cases=build_cases(catalog.json()['items'])
        def record(sample):
            sample.update(run_id=run_id,boot_id=boot_id)
            samples.append(sample)
            with (args.output/'samples.jsonl').open('a',encoding='utf-8') as output:
                output.write(json.dumps(sample,ensure_ascii=False,allow_nan=False)+'\n')
                output.flush()
                os.fsync(output.fileno())
            (args.output/'summary.json').write_text(json.dumps(summarize(samples),ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({key:sample.get(key) for key in ('case','index','phase','status','http_ms','score')},ensure_ascii=False),flush=True)
        if not samples: record(run_sample(client,cases[0],0,'warmup'))
        for case,index in pending_work(cases,args.repeat,samples):
            print(json.dumps({'starting':case['name'],'index':index,'run_id':run_id}),flush=True)
            record(run_sample(client,case,index,'measurement'))
    print(json.dumps({'complete':len(samples),'summary':summarize(samples)},ensure_ascii=False),flush=True)


if __name__=='__main__': main()
