"""Request-local, response-only timings. No prompts, answers or credentials."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from uuid import uuid4

_active: ContextVar[Trace | None] = ContextVar('performance_trace', default=None)
_stack: ContextVar[tuple[str, ...]] = ContextVar('performance_stack', default=())


class Trace:
    def __init__(self, *, clock=perf_counter):
        self.clock = clock
        self.started = clock()
        self.trace_id = uuid4().hex
        self.stages: list[dict] = []
        self.model_calls: list[dict] = []

    def snapshot(self):
        return {'schema_version':1, 'trace_id':self.trace_id,
                'total_ms':round((self.clock()-self.started)*1000, 3),
                'stages':list(self.stages), 'model_calls':list(self.model_calls)}


def current_trace():
    return _active.get()


@contextmanager
def use_trace(trace):
    token = _active.set(trace)
    stack_token = _stack.set(())
    try:
        yield trace
    finally:
        _stack.reset(stack_token)
        _active.reset(token)


@contextmanager
def stage(name: str, **tags):
    trace = current_trace()
    if trace is None:
        yield
        return
    stack = _stack.get()
    token = _stack.set((*stack, name))
    started = trace.clock()
    status = 'ok'
    try:
        yield
    except BaseException:
        status = 'error'
        raise
    finally:
        trace.stages.append({'name':name, 'depth':len(stack), 'parent':stack[-1] if stack else None,
                             'start_ms':round((started-trace.started)*1000, 3),
                             'duration_ms':round((trace.clock()-started)*1000, 3),
                             'status':status, **tags})
        _stack.reset(token)


def record_model_call(value: dict):
    trace = current_trace()
    if trace is not None:
        trace.model_calls.append(dict(value))


def record_model_validation(purpose: str, *, error_code: str = ''):
    """Keep SDK evidence, but never count rejected business output as success."""
    trace = current_trace()
    if trace is None:
        return
    for call in reversed(trace.model_calls):
        if call.get('purpose') == purpose:
            if call.get('status') == 'ok':
                call['application_status'] = 'rejected' if error_code else 'accepted'
                if error_code:
                    call.update(status='error', error_code=error_code)
            break


def current_purpose():
    return next((name for name in reversed(_stack.get()) if name in ('match_risk','overview')), 'unspecified')


def traced_generation(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        trace = Trace()
        with use_trace(trace):
            result = await function(*args, **kwargs)
        result['performance'] = trace.snapshot()
        return result
    return wrapped
