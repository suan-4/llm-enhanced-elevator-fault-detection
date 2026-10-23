"""Observability for the existing single-inference RKLLM server; no ctypes ABI changes."""
import json
import math
from time import perf_counter
from uuid import uuid4

_clock = perf_counter
_sample = None
_request_started = None
_load_started = None
_model_load_ms = None
_SDK_FIELDS = ('prefill_time_ms','prefill_tokens','generate_time_ms','generate_tokens','memory_usage_mb')


class InferenceMetrics:
    def __init__(self, *, clock=perf_counter):
        self.clock = clock
        self.started = None
        self.ended = None
        self.first = None
        self.run_status = 'not_started'
        self.inference_id = uuid4().hex
        self.sdk = {key:None for key in _SDK_FIELDS}

    def start(self):
        self.started = self.clock()
        self.run_status = 'running'

    def first_text(self, text):
        if self.first is None and text:
            self.first = self.clock()

    def finish(self, stat=None):
        self.ended = self.clock()
        self.run_status = 'finished'
        if stat is None:
            return
        try:
            values = {key:getattr(stat,key) for key in _SDK_FIELDS}
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v < 0 for v in values.values()):
                return
            if values['prefill_tokens'] <= 0 or values['prefill_time_ms'] <= 0:
                return
            if any(not isinstance(values[key],int) for key in ('prefill_tokens','generate_tokens')):
                return
            self.sdk = values
        except (AttributeError,TypeError,ValueError):
            return

    def snapshot(self):
        def elapsed(end):
            return round((end-self.started)*1000,3) if end is not None and self.started is not None else None
        def rate(tokens,duration):
            return round(tokens*1000/duration,3) if tokens is not None and duration is not None and duration > 0 else None
        return {**self.sdk, 'inference_id':self.inference_id, 'first_output_ms':elapsed(self.first),
                'model_run_ms':elapsed(self.ended), 'run_status':self.run_status,
                'prefill_tokens_per_s':rate(self.sdk['prefill_tokens'],self.sdk['prefill_time_ms']),
                'generate_tokens_per_s':rate(self.sdk['generate_tokens'],self.sdk['generate_time_ms']),
                'perf_source':'rkllm_runtime' if self.sdk['prefill_tokens'] is not None else 'unavailable'}


def begin_model_load():
    global _load_started
    _load_started = _clock()


def finish_model_load():
    global _model_load_ms
    if _load_started is not None:
        _model_load_ms = round((_clock()-_load_started)*1000,3)


def begin_request():
    global _request_started, _sample
    _request_started = _clock()
    _sample = None


def start_inference():
    global _sample
    _sample = InferenceMetrics(clock=_clock)
    _sample.start()


def observe(result, state):
    """Never let Python observation errors unwind through the C callback."""
    try:
        sample = _sample
        if sample is None:
            return
        if state == 0 and result:
            sample.first_text(result.contents.text)
        elif state == 2:
            sample.finish(result.contents.perf if result else None)
        elif state == 3:
            sample.run_status = 'error'
    except Exception:
        return


def finish_inference():
    try:
        if _sample is not None:
            _sample.ended = _clock()
            if _sample.run_status == 'running':
                _sample.run_status = 'no_finish_callback'
            # Observation must never replace a successful result or original error.
            print('ELEVATOR_PERF ' + json.dumps(_sample.snapshot(),allow_nan=False),flush=True)
    except Exception:
        pass


def attach_response(response):
    result = dict(response)
    sample = _sample.snapshot() if _sample is not None else InferenceMetrics().snapshot()
    sample['model_load_ms'] = _model_load_ms
    sample['request_total_ms'] = round((_clock()-_request_started)*1000,3) if _request_started is not None else None
    result['performance'] = sample
    prompt, completion = sample['prefill_tokens'], sample['generate_tokens']
    result['usage'] = {'prompt_tokens':prompt,'completion_tokens':completion,
                       'total_tokens':prompt+completion if prompt is not None and completion is not None else None}
    return result
