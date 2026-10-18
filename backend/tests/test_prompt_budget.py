"""Real tiny tokenizer fixtures exercise the guard; not evidence of RKLLM calibration."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.prompt_budget import PromptBudget, ModelInputError, calibration_profile, PROBE_GROUPS


class PromptBudgetTests(unittest.TestCase):
    def setUp(self):
        from tokenizers import Tokenizer, models, pre_tokenizers
        self.temp = tempfile.TemporaryDirectory(prefix='token-budget-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'tokenizer.json'
        tokenizer = Tokenizer(models.WordLevel({'[UNK]':0, 'x':1}, unk_token='[UNK]'))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer.save(str(self.path))
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.profile_path = self.root / 'calibration.json'
        self.samples = [dict(group=group, text_sha256='a'*64, input_tokens=2,
                             sdk_input_tokens=3, sdk_finished=True) for group in PROBE_GROUPS]
        self.profile = calibration_profile(self.samples, tokenizer_sha256=self.sha,
                                           model_id='fixture-model', context_size=20, template_reserve=8)
        self.profile_path.write_text(json.dumps(self.profile), encoding='utf8')

    def budget(self, **overrides):
        args=dict(tokenizer_path=self.path, profile_path=self.profile_path,
                  expected_sha256=self.sha, model_id='fixture-model', context_size=20,
                  output_tokens=4, template_reserve=8)
        args.update(overrides)
        return PromptBudget(**args)

    def test_exact_boundary_counts_final_text_without_truncation(self):
        budget=self.budget()
        self.assertEqual(budget.check(' '.join(['x']*8))['input_tokens'],8)
        with self.assertRaises(ModelInputError) as raised:
            budget.check(' '.join(['x']*9))
        self.assertEqual(raised.exception.code,'context_budget_exceeded')
        self.assertEqual(raised.exception.details['input_tokens'],9)

    def test_token_count_is_not_character_count(self):
        self.assertEqual(self.budget().check('abcde')['input_tokens'],1)

    def test_missing_asset_or_profile_fails_closed(self):
        for key in ('tokenizer_path','profile_path'):
            with self.subTest(key=key), self.assertRaises(ModelInputError):
                self.budget(**{key:self.root/'absent'}).check('x')

    def test_tokenizer_integrity_mismatch_is_rejected(self):
        with self.assertRaises(ModelInputError) as raised:
            self.budget(expected_sha256='0'*64).check('x')
        self.assertEqual(raised.exception.code,'tokenizer_mismatch')

    def test_corrupt_or_wrong_model_profile_is_rejected(self):
        for value in ('invalid json', json.dumps({**self.profile,'model_id':'wrong'}),
                      json.dumps({**self.profile,'tokenizer_sha256':'0'*64}),
                      json.dumps({**self.profile,'context_size':4096})):
            with self.subTest(value=value), self.assertRaises(ModelInputError):
                self.profile_path.write_text(value,encoding='utf8')
                self.budget().check('x')

    def test_invalid_configuration_and_bool_are_rejected(self):
        for params in ({'output_tokens':0},{'output_tokens':True},{'template_reserve':-1},
                       {'context_size':12},{'context_size':20.5}):
            with self.subTest(params=params), self.assertRaises(ModelInputError):
                self.budget(**params).check('x')

    def test_model_identity_must_match_calibrated_model(self):
        budget=self.budget()
        budget.verify_model_id(['fixture-model'])
        with self.assertRaises(ModelInputError) as raised:
            budget.verify_model_id(['different-model'])
        self.assertEqual(raised.exception.code,'model_mismatch')

    def test_insufficient_or_failed_sdk_calibration_never_produces_profile(self):
        for samples in (self.samples[:-1], [{**r,'sdk_finished':False} for r in self.samples],
                        [{**r,'sdk_input_tokens':100} for r in self.samples],
                        [{**r,'sdk_input_tokens':True} for r in self.samples]):
            with self.subTest(samples=samples), self.assertRaises(ModelInputError):
                calibration_profile(samples, tokenizer_sha256=self.sha,model_id='fixture-model',
                                    context_size=20,template_reserve=8)

    def test_profile_retains_numeric_evidence_but_not_text_or_credentials(self):
        samples=[{**r,'prompt':'secret content','token':'secret credential'} for r in self.samples]
        value=calibration_profile(samples,tokenizer_sha256=self.sha,model_id='fixture-model',context_size=20,template_reserve=8)
        self.assertNotIn('secret',json.dumps(value))
        self.assertEqual(value['status'],'calibrated')


if __name__=='__main__': unittest.main()
