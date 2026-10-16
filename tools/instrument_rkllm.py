"""Idempotent, fail-closed metrics patch for the board's existing RKLLM 1.3 Flask server.

Only writes the explicitly selected output, never deploys/restarts by itself.
"""
import argparse
import ast
from pathlib import Path

MARKER = '# elevator-performance-profile-v1'


def instrument(source: str) -> str:
    source = source.replace('\r\n','\n')
    ast.parse(source)
    required = ('_elevator_metrics.observe(result, state)', '_elevator_metrics.attach_response(response)',
                '_elevator_metrics.start_inference()', '_elevator_metrics.finish_inference()',
                '_elevator_metrics.begin_model_load()', '_elevator_metrics.finish_model_load()',
                '_elevator_metrics.begin_request()')
    if MARKER in source:
        if all(source.count(item) == 1 for item in required):
            return source
        raise ValueError('Partially instrumented or incompatible model server; refusing to modify')

    def replace_once(old,new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError('Model server source does not match the reviewed RKLLM 1.3 anchors: ' + old[:70])
        source = source.replace(old,new,1)

    replace_once('import re\n','import re\nimport rkllm_metrics as _elevator_metrics  ' + MARKER + '\n')
    replace_once('    global global_text, global_state, split_byte_data\n',
                 '    global global_text, global_state, split_byte_data\n    _elevator_metrics.observe(result, state)\n')
    native = '        self.rkllm_run(self.handle, ctypes.byref(rkllm_input), ctypes.byref(self.rkllm_infer_params), None)'
    replace_once(native, '        _elevator_metrics.start_inference()\n        try:\n    ' + native + '\n        finally:\n            _elevator_metrics.finish_inference()')
    init = '        ret = self.rkllm_init(ctypes.byref(self.handle), ctypes.byref(rkllm_param), ctypes.byref(self.callback))'
    replace_once(init,'        _elevator_metrics.begin_model_load()\n' + init + '\n        _elevator_metrics.finish_model_load()')
    replace_once('    global global_text, global_state, system_prompt, is_blocking\n',
                 '    global global_text, global_state, system_prompt, is_blocking\n    _elevator_metrics.begin_request()\n')
    replace_once('                return jsonify(response)',
                 '                return jsonify(_elevator_metrics.attach_response(response))') if '                return jsonify(response)' in source else replace_once(
                     '    return jsonify(response)','    return jsonify(_elevator_metrics.attach_response(response))')
    compile(source,'instrumented_flask_server.py','exec')
    return source


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve():
        parser.error('Source and output must differ; deployment must take its own backup')
    args.output.write_text(instrument(args.source.read_text(encoding='utf-8')),encoding='utf-8')
