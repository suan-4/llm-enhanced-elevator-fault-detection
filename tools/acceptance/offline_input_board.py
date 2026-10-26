"""Actual board input engine smoke; never touches production report/account rows."""
from pathlib import Path
import json
import sys
import time

candidate = Path(sys.argv[1]).resolve()
assert candidate.parent.parent == Path('/userdata/releases')
sys.path.insert(0, str(candidate / 'backend'))
from app.services import offline_input as engine

status = engine.status()
assert status['pinyin'] and status['voice'] and status['offline']
start = time.monotonic()
actions = [{'key': ch} for ch in 'zhidongqi']
result = engine.pinyin(actions)
assert '制动器' in result['candidates']
pinyin_ms = round((time.monotonic() - start) * 1000)
selected = engine.pinyin([*actions, {'candidate': '制动器'}])
assert selected['committed'] == '制动器'
start = time.monotonic()
text = engine.transcribe(engine.MODEL / 'test_wavs/zh.wav')
asr_ms = round((time.monotonic() - start) * 1000)
assert text == '开放时间早上9点至下午5点。', text
capture = engine.VoiceCapture()
record = capture.start()
try:
    time.sleep(.4)
    process = capture.process
    folder = capture.folder
    captured_bytes = (folder / 'audio.pcm').stat().st_size
finally:
    capture.cancel(record['id'])
assert process.poll() is not None and not folder.exists()
report = {'scope': 'offline input engines; report/export source unchanged',
          'status': status, 'pinyin_ms': pinyin_ms, 'selected': selected['committed'],
          'asr_text': text, 'asr_total_ms_including_load': asr_ms,
          'mic_capture_bytes_in_400ms': captured_bytes,
          'recording_cancel_cleans_process_and_audio': True,
          'human_mic_intelligibility': 'not tested; requires onsite speech',
          'passed': True}
target = candidate / 'output/terminal-ui-acceptance/board-smoke.json'
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False))
