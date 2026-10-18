import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.llm_service import LLMService, build_content
from app.services.prompt_budget import ModelInputError
from app.services.performance import Trace, use_trace, stage


class BudgetFixture:
    """Transport contract fixture, not genuine tokenizer or board evidence."""
    output_tokens=512
    def __init__(self, reject=False): self.checked=None; self.reject=reject
    def check(self,text):
        self.checked=text
        if self.reject: raise ModelInputError('context_budget_exceeded','超过输入预算')
        return {'input_tokens':10,'reserved_output_tokens':512}
    def verify_model_id(self,ids):
        if 'fixture-model' not in ids: raise ModelInputError('model_mismatch','模型不匹配')


class ModelGuardTests(unittest.TestCase):
    def run_call(self, response=None, *, blocked=False, models=None):
        requests=[]
        budget=BudgetFixture(blocked)
        def transport(req):
            requests.append(req)
            if req.method=='GET':
                return httpx.Response(200,json={'data':[{'id':value} for value in (models or ['fixture-model'])]})
            return httpx.Response(200,json=response or {'choices':[{'message':{'content':'{"ok":true}'}}],
                  'performance':{'run_status':'finished','prefill_tokens':15,'generate_tokens':3}})
        async def execute():
            client=LLMService()
            client._client=httpx.AsyncClient(transport=httpx.MockTransport(transport))
            trace=Trace()
            try:
                with patch.object(client,'_budget',budget), use_trace(trace), stage('overview'):
                    try: result=await client.generate('{"system":"指令","data":{"x":"中文"}}')
                    except RuntimeError as error: result=error
            finally: await client.close()
            return result,trace.snapshot()['model_calls']
        result,calls=asyncio.run(execute())
        return result,calls,requests,budget

    def test_content_builder_is_compact_and_preserves_original_text(self):
        self.assertEqual(build_content('{"system":"指令","data":{"x":"中文"}}'),'指令\n\n{"x":"中文"}')

    def test_budget_checks_the_exact_content_sent_and_reserves_output(self):
        result,calls,requests,budget=self.run_call()
        self.assertIsInstance(result,str)
        payload=json.loads(next(req.content for req in requests if req.method=='POST'))
        self.assertEqual(payload['messages'][0]['content'],budget.checked)
        self.assertEqual(payload['max_tokens'],512)
        self.assertEqual(calls[0]['input_tokens'],10)

    def test_blocked_input_never_calls_server_and_is_not_success(self):
        result,calls,requests,_=self.run_call(blocked=True)
        self.assertEqual(requests,[])
        self.assertEqual(result.code,'context_budget_exceeded')
        self.assertEqual(calls[0]['status'],'error')
        self.assertEqual(calls[0]['error_code'],'context_budget_exceeded')
        self.assertIsNone(calls[0]['http_status'])

    def test_model_identity_mismatch_prevents_inference(self):
        result,calls,requests,_=self.run_call(models=['wrong'])
        self.assertEqual(result.code,'model_mismatch')
        self.assertTrue(all(req.method=='GET' for req in requests))

    def test_empty_or_failed_or_unfinished_sdk_result_is_not_model_success(self):
        for response in (
            {'choices':[{'message':{'content':''}}],'performance':{'run_status':'finished'}},
            {'choices':[{'message':{'content':'text'}}],'performance':{'run_status':'error'}},
            {'choices':[{'message':{'content':'text'}}],'performance':{'run_status':'running'}},
            {'choices':[{'message':{'content':'text'}}]},
        ):
            with self.subTest(response=response):
                result,calls,_,_=self.run_call(response)
                self.assertIsInstance(result,ModelInputError)
                self.assertEqual(calls[0]['status'],'error')


if __name__=='__main__': unittest.main()
