import json
from pathlib import Path
import sys
import unittest

import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from calibrate_tokenizer import run_calibration, synthetic_probes
from app.services.prompt_budget import ModelInputError,PROBE_GROUPS


class CalibrationToolTests(unittest.TestCase):
    def test_synthetic_probes_cover_all_groups_without_business_database(self):
        probes = synthetic_probes()
        self.assertEqual({group for group, _ in probes}, PROBE_GROUPS)
        self.assertTrue(all(isinstance(text, str) and text for _, text in probes))

    def test_real_encoding_and_sdk_observations_are_bound_before_profile_is_written(self):
        from tokenizers import Tokenizer,models,pre_tokenizers
        tokenizer=Tokenizer(models.WordLevel({'[UNK]':0,'x':1},unk_token='[UNK]'))
        tokenizer.pre_tokenizer=pre_tokenizers.Whitespace()
        records=[]
        def transport(req):
            if req.method=='GET': return httpx.Response(200,json={'data':[{'id':'fixture-model'}]})
            self.assertEqual(json.loads(req.content)['max_tokens'],1)
            return httpx.Response(200,json={'performance':{'run_status':'finished','prefill_tokens':3}})
        with httpx.Client(base_url='http://127.0.0.1:18080',transport=httpx.MockTransport(transport)) as client:
            result=run_calibration(client,tokenizer,model_id='fixture-model',expected_sha='a'*64,
                context_size=20,template_reserve=8,probes=[(g,'x x') for g in PROBE_GROUPS],record=records.append)
        self.assertEqual(result['status'],'calibrated')
        self.assertEqual(len(records),len(PROBE_GROUPS))
        self.assertTrue(all(row['input_tokens']==2 and row['sdk_input_tokens']==3 for row in records))
        self.assertNotIn('x x',json.dumps(result))

    def test_bad_sdk_observation_cannot_be_calibrated(self):
        from tokenizers import Tokenizer,models
        tokenizer=Tokenizer(models.WordLevel({'[UNK]':0},unk_token='[UNK]'))
        def transport(req):
            return httpx.Response(200,json={'data':[{'id':'fixture-model'}]} if req.method=='GET'
                else {'performance':{'run_status':'running','prefill_tokens':None}})
        with httpx.Client(base_url='http://127.0.0.1:18080',transport=httpx.MockTransport(transport)) as client:
            with self.assertRaises(ModelInputError):
                run_calibration(client,tokenizer,model_id='fixture-model',expected_sha='a'*64,
                    context_size=20,template_reserve=8,probes=[(g,'x') for g in PROBE_GROUPS],record=lambda row:None)


if __name__=='__main__': unittest.main()
