"""模型指标/补丁契约测试；这里的假原生函数不作为真实性能证据。"""
import importlib.util
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / 'kiosk'))
sys.path.insert(0,str(ROOT / 'tools'))

import rkllm_metrics as metrics
from instrument_rkllm import instrument


class Clock:
    value = 0.0
    def __call__(self): return self.value
    def advance(self,value): self.value += value


class ModelMetricsTests(unittest.TestCase):
    def test_logging_failure_is_harmless_and_missing_finish_is_terminal(self):
        metrics.begin_request()
        metrics.start_inference()
        with patch('builtins.print',side_effect=BrokenPipeError):
            metrics.finish_inference()
        self.assertEqual(metrics.attach_response({})['performance']['run_status'],'no_finish_callback')

    def test_prefill_generation_and_first_text_are_distinct(self):
        clock = Clock()
        sample = metrics.InferenceMetrics(clock=clock)
        sample.start()
        sample.first_text(b'')
        self.assertIsNone(sample.snapshot()['first_output_ms'])
        clock.advance(.2)
        sample.first_text('首字'.encode())
        clock.advance(.3)
        sample.first_text(b'next')
        clock.advance(.5)
        sample.finish(SimpleNamespace(prefill_time_ms=500,prefill_tokens=100,
                                      generate_time_ms=400,generate_tokens=20,memory_usage_mb=1500))
        result = sample.snapshot()
        self.assertEqual(result['first_output_ms'],200)
        self.assertEqual(result['model_run_ms'],1000)
        self.assertEqual(result['prefill_tokens_per_s'],200)
        self.assertEqual(result['generate_tokens_per_s'],50)

    def test_missing_or_invalid_runtime_numbers_are_not_estimated(self):
        for raw in [None,SimpleNamespace(prefill_time_ms=float('nan'),prefill_tokens=100,
                    generate_time_ms=1,generate_tokens=20,memory_usage_mb=500),
                    SimpleNamespace(prefill_time_ms=0,prefill_tokens=0,
                    generate_time_ms=0,generate_tokens=0,memory_usage_mb=0)]:
            sample = metrics.InferenceMetrics()
            sample.start()
            sample.first_text(b'answer with spaces')
            sample.finish(raw)
            result = sample.snapshot()
            self.assertIsNone(result['prefill_tokens'])
            self.assertIsNone(result['generate_tokens'])
            self.assertIsNone(result['generate_tokens_per_s'])
            self.assertEqual(result['perf_source'],'unavailable')

    def test_null_callback_and_observation_errors_never_escape(self):
        metrics.begin_request()
        metrics.start_inference()
        metrics.observe(None,2)
        metrics.observe(SimpleNamespace(contents=SimpleNamespace(text=None)),0)
        metrics.finish_inference()
        response = metrics.attach_response({'choices':[{'message':{'content':'kept'}}],
                                            'usage':{'prompt_tokens':999,'completion_tokens':999}})
        self.assertEqual(response['choices'][0]['message']['content'],'kept')
        self.assertIsNone(response['usage']['prompt_tokens'])
        self.assertIsNone(response['usage']['completion_tokens'])


FIXTURE = '''import re
import ctypes
global_text, global_state, system_prompt, is_blocking = [], -1, '', False
def callback_impl(result, userdata, state):
    global global_text, global_state, split_byte_data
    if state == 2:
        global_state = state
    return 0
class RKLLM:
    def __init__(self):
        self.handle = ctypes.c_void_p()
        rkllm_param = ctypes.c_int()
        self.callback = ctypes.c_int()
        self.rkllm_init = lambda *a: 0
        ret = self.rkllm_init(ctypes.byref(self.handle), ctypes.byref(rkllm_param), ctypes.byref(self.callback))
        self.rkllm_run = lambda *a: 0
        self.rkllm_infer_params = ctypes.c_int()
    def run(self):
        rkllm_input = ctypes.c_int()
        self.rkllm_run(self.handle, ctypes.byref(rkllm_input), ctypes.byref(self.rkllm_infer_params), None)
def chat_completions():
    global global_text, global_state, system_prompt, is_blocking
    response = {'choices': [{'message': {'content': 'unchanged'}}]}
    return jsonify(response)
def jsonify(value): return value
'''


class InstrumentTests(unittest.TestCase):
    def test_instrumented_server_still_returns_original_content(self):
        changed = instrument(FIXTURE)
        namespace = {}
        exec(compile(changed,'fixture','exec'),namespace)
        model = namespace['RKLLM']()
        model.run()
        response = namespace['chat_completions']()
        self.assertEqual(response['choices'][0]['message']['content'],'unchanged')
        self.assertIn('performance',response)
        self.assertIsNone(response['usage']['total_tokens'])

    def test_patch_is_idempotent_and_rejects_source_drift(self):
        changed = instrument(FIXTURE)
        self.assertEqual(instrument(changed),changed)
        with self.assertRaises(ValueError): instrument(FIXTURE.replace('return jsonify(response)','return another(response)'))
        with self.assertRaises(ValueError): instrument('# elevator-performance-profile-v1\n'+FIXTURE)

    def test_partial_import_or_moved_injection_is_rejected(self):
        changed=instrument(FIXTURE)
        for broken in (changed.replace('import rkllm_metrics as _elevator_metrics  ',''),
                       changed.replace('    _elevator_metrics.observe(result, state)\n','')+'\n_elevator_metrics.observe(result, state)\n'):
            with self.assertRaises(ValueError): instrument(broken)


if __name__ == '__main__': unittest.main()
