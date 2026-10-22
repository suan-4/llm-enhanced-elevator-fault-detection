import sys
import unittest
import asyncio
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'tools/acceptance'))
import performance_benchmark as benchmark
from performance_benchmark import summarize, validate_target, build_cases, pending_work


class BenchmarkTests(unittest.TestCase):
    def test_read_only_health_identity_is_omitted_for_production(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from app.main import health_check,settings
        for path,expected in [('/userdata/elevator/elevator.db',None),
                              ('/userdata/releases/test/benchmark/performance-benchmark.db','/userdata/releases/test/benchmark/performance-benchmark.db')]:
            with patch.object(settings,'sqlite_path',path):
                self.assertEqual(asyncio.run(health_check()).get('benchmark_db'),expected)

    def test_preflight_rejects_production_before_any_login(self):
        calls=[]
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'status':'ok'}
        class Client:
            def get(self,path): calls.append(path); return Response()
            def post(self,*args,**kwargs): self.fail('Must not log in')
        with self.assertRaises(ValueError):
            benchmark.verify_before_login(Client(),'http://127.0.0.1:18083','/userdata/releases/test/benchmark/performance-benchmark.db')
        self.assertEqual(calls,['/api/health'])

    def test_resume_skips_recorded_attempts_even_when_they_failed(self):
        cases=[{'name':name} for name in ('a','b','c')]
        samples=[{'case':'a','index':1,'phase':'measurement','status':'ok'},
                 {'case':'b','index':1,'phase':'measurement','status':'error'}]
        self.assertEqual([(case['name'],index) for case,index in pending_work(cases,2,samples)],
                         [('c',1),('a',2),('b',2),('c',2)])
        with self.assertRaises(ValueError): pending_work(cases,2,samples+samples[:1])

    def test_summary_excludes_warmup_and_failures_from_success_latency(self):
        rows = [
            {'case':'a','phase':'measurement','status':'ok','http_ms':100},
            {'case':'a','phase':'measurement','status':'ok','http_ms':200},
            {'case':'a','phase':'measurement','status':'ok','http_ms':600},
            {'case':'a','phase':'measurement','status':'degraded','http_ms':9000},
            {'case':'a','phase':'measurement','status':'error','http_ms':10000},
            {'case':'a','phase':'warmup','status':'ok','http_ms':100000},
        ]
        result = summarize(rows)['a']
        self.assertEqual(result['attempts'],5)
        self.assertEqual(result['successful'],3)
        self.assertEqual(result['degraded'],1)
        self.assertEqual(result['failed'],1)
        self.assertEqual(result['success_rate'],.6)
        self.assertEqual(result['http_ms']['mean'],300)
        self.assertEqual(result['http_ms']['median'],200)
        self.assertEqual(result['http_ms']['min'],100)
        self.assertEqual(result['http_ms']['max'],600)

    def test_production_or_unverified_targets_are_rejected(self):
        expected='/userdata/releases/test/benchmark/performance-benchmark.db'
        validate_target('http://127.0.0.1:18083',expected,{'db':{'path':expected}})
        for base,path,info in [
            ('http://127.0.0.1:8081',expected,{'db':{'path':expected}}),
            ('http://remote:18083',expected,{'db':{'path':expected}}),
            ('http://127.0.0.1:18083',expected,{'db':{'path':'/userdata/elevator/elevator.db'}}),
            ('http://127.0.0.1:18083','/userdata/elevator/elevator.db',{'db':{'path':'/userdata/elevator/elevator.db'}}),
        ]:
            with self.assertRaises(ValueError): validate_target(base,path,info)

    def test_cases_keep_same_list_risks_except_the_free_text_substitution(self):
        catalog=[{'no':no,'opts':[f'{no}risk{i}' for i in range(35)]} for no in ('1.7','1.9','16.1','16.6')]
        cases=build_cases(catalog)
        self.assertEqual([c['name'] for c in cases],['all_fit','selected_risks','natural_language'])
        self.assertTrue(all(i['result']=='fit' for i in cases[0]['items']))
        for case in cases[1:]:
            by_no={i['no']:i for i in case['items']}
            self.assertEqual(by_no['1.9']['result'],'na')
            self.assertEqual(len(by_no['1.7']['reasons']),2)
            self.assertEqual(by_no['16.6']['reasons'],['16.6risk12'])
        self.assertTrue(cases[1]['items'][2]['reasons'])
        self.assertFalse(cases[2]['items'][2]['reasons'])
        self.assertTrue(cases[2]['items'][2]['other_text'])


if __name__=='__main__': unittest.main()
