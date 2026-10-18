"""性能观测不得改变报告结果、错误和事务语义；仅使用隔离临时库。"""
import asyncio
import sys
import unittest
import httpx
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import performance as perf
from app.services import report_workflow as wf
from tests._tempdb import TempDB
from tests.test_report_workflow import _actor, _items, FORM
from app.services.llm_service import LLMService
from app.services.prompt_budget import ModelInputError
from tests.test_model_guard import BudgetFixture
from unittest.mock import patch


class Clock:
    value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class PerformanceTests(unittest.TestCase):
    def test_invalid_model_overview_is_not_a_successful_model_measurement(self):
        for content in ('not JSON','{"overview_keys":["finding","score","invented"]}'):
            async def execute():
                service=LLMService()
                service._budget=BudgetFixture()
                service._client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:
                    httpx.Response(200,json={'data':[{'id':'fixture-model'}]}) if req.method=='GET' else
                    httpx.Response(200,json={'choices':[{'message':{'content':content}}],
                        'performance':{'run_status':'finished','prefill_tokens':100,'generate_tokens':5}})))
                try:
                    with TempDB():
                        actor=_actor()
                        report=wf.create_draft(actor=actor)
                        wf.save_content(report['id'],form=FORM,items=_items(),actor=actor)
                        with patch.object(wf,'llm_service',service):
                            return await wf.generate(report['id'],use_llm=True,actor=actor)
                finally:
                    await service.close()
            with self.subTest(content=content):
                result=asyncio.run(execute())
                self.assertFalse(result['provenance']['llm_used'])
                call=result['performance']['model_calls'][0]
                self.assertEqual(call['runtime']['run_status'],'finished')
                self.assertEqual(call['status'],'error')
                self.assertEqual(call['error_code'],'model_response_invalid')

    def test_nested_stages_have_explicit_depth_and_milliseconds(self):
        clock = Clock()
        trace = perf.Trace(clock=clock)
        with perf.use_trace(trace):
            with perf.stage('prepare'):
                clock.advance(.1)
                with perf.stage('prompt'):
                    clock.advance(.2)
                clock.advance(.1)
        result = trace.snapshot()
        self.assertAlmostEqual(result['total_ms'], 400)
        by_name = {s['name']:s for s in result['stages']}
        self.assertAlmostEqual(by_name['prepare']['duration_ms'], 400)
        self.assertAlmostEqual(by_name['prompt']['duration_ms'], 200)
        self.assertEqual(by_name['prepare']['depth'], 0)
        self.assertEqual(by_name['prompt']['depth'], 1)

    def test_parallel_requests_do_not_share_metrics(self):
        @perf.traced_generation
        async def run(label):
            with perf.stage(label):
                await asyncio.sleep(0)
                perf.record_model_call({'purpose':label,'http_ms':1})
            return {'label':label}

        async def both():
            return await asyncio.gather(run('a'),run('b'))

        results = asyncio.run(both())
        for result in results:
            metrics = result['performance']
            self.assertEqual([s['name'] for s in metrics['stages']], [result['label']])
            self.assertEqual(metrics['model_calls'][0]['purpose'],result['label'])
        self.assertNotEqual(results[0]['performance']['trace_id'],results[1]['performance']['trace_id'])
        self.assertIsNone(perf.current_trace())

    def test_original_error_propagates_and_context_is_reset(self):
        error = ValueError('original business error')

        @perf.traced_generation
        async def bad():
            with perf.stage('validate'):
                raise error

        with self.assertRaises(ValueError) as raised:
            asyncio.run(bad())
        self.assertIs(raised.exception,error)
        self.assertIsNone(perf.current_trace())

    def test_stages_are_harmless_without_observer(self):
        with perf.stage('legacy'):
            perf.record_model_call({'purpose':'legacy'})
        self.assertIsNone(perf.current_trace())

    def test_real_report_total_includes_final_commit(self):
        with TempDB():
            actor = _actor()
            report = wf.create_draft(actor=actor)
            wf.save_content(report['id'],form=FORM,items=_items(),actor=actor)
            result = asyncio.run(wf.generate(report['id'],actor=actor))
            self.assertEqual(result['status'],'generated')
            self.assertEqual(result['score'],100)
            metrics = result['performance']
            names = [s['name'] for s in metrics['stages']]
            for expected in ['db_read','catalog_load','validate','risk_assessment','score','db_commit']:
                self.assertIn(expected,names)
            roots = [s for s in metrics['stages'] if s['depth']==0]
            self.assertGreaterEqual(metrics['total_ms']+.01,sum(s['duration_ms'] for s in roots))
            stored = wf.get_report(report['id'])
            self.assertNotIn('performance',stored, 'response-only timing must not add a second DB write')
            self.assertIn('elapsed_ms',stored['provenance'])

    def test_model_metrics_use_runtime_not_space_based_usage(self):
        async def run(with_runtime):
            payload = {'choices':[{'message':{'content':'original answer'}}],
                       'usage':{'prompt_tokens':2,'completion_tokens':2},
                       'performance':{'run_status':'finished','prefill_tokens':123,'generate_tokens':20,
                                      'prefill_time_ms':500,'generate_time_ms':400,
                                      'prompt':'must not be copied'} if with_runtime else None}
            client = LLMService()
            client._budget = BudgetFixture()
            client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200,
                json={'data':[{'id':'fixture-model'}]} if req.method=='GET' else payload)))
            trace = perf.Trace()
            try:
                with perf.use_trace(trace), perf.stage('overview'):
                    if with_runtime:
                        answer = await client.generate('{"system":"instruction","data":{"x":"中文材料"}}')
                        self.assertEqual(answer,'original answer')
                    else:
                        with self.assertRaises(ModelInputError):
                            await client.generate('{"system":"instruction","data":{"x":"中文材料"}}')
            finally:
                await client.close()
            calls = trace.snapshot()['model_calls']
            self.assertEqual(len(calls),1,'every model HTTP call must have a timing record')
            return calls[0]

        real = asyncio.run(run(True))
        self.assertEqual(real['purpose'],'overview')
        self.assertEqual(real['runtime']['prefill_tokens'],123)
        self.assertNotIn('prompt',real['runtime'])
        self.assertGreater(real['input_utf8_bytes'],real['input_chars'])
        self.assertIsNone(asyncio.run(run(False))['runtime'])

    def test_model_http_failure_is_timed_and_still_fails(self):
        async def run():
            client = LLMService()
            client._budget = BudgetFixture()
            client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req:
                httpx.Response(200,json={'data':[{'id':'fixture-model'}]}) if req.method=='GET'
                else httpx.Response(503,json={'error':'busy'})))
            trace = perf.Trace()
            try:
                with perf.use_trace(trace), perf.stage('match_risk'):
                    with self.assertRaises(RuntimeError):
                        await client.generate('{}')
            finally:
                await client.close()
            calls = trace.snapshot()['model_calls']
            self.assertEqual(len(calls),1,'failed model HTTP calls must also be timed')
            return calls[0]
        call = asyncio.run(run())
        self.assertEqual(call['status'],'error')
        self.assertEqual(call['http_status'],503)
        self.assertGreaterEqual(call['http_ms'],0)


if __name__ == '__main__':
    unittest.main()
