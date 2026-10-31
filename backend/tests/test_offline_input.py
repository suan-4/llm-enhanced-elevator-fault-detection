import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.offline_input import VoiceCapture, validate_actions, pcm_samples, transcribe, _decode
from app.api.input import require_local


class OfflineInputTests(unittest.TestCase):
    def test_cancel_terminates_real_decoder_process(self):
        canceled = threading.Event()
        timer = threading.Timer(.15, canceled.set)
        timer.start()
        try:
            with self.assertRaises(ValueError):
                _decode([sys.executable, '-c', 'import time; time.sleep(60)'], dict(os.environ), canceled)
        finally:
            timer.cancel()

    def test_cancel_during_recognition_is_prompt_and_removes_audio(self):
        entered, release = threading.Event(), threading.Event()
        def decoding(path, cancel=None):
            entered.set(); release.wait(3)
            return 'old transcript'
        with tempfile.TemporaryDirectory() as folder:
            capture = VoiceCapture(temp_root=Path(folder))
            with patch('app.services.offline_input.capture_command', return_value=[sys.executable, '-c', 'import time; time.sleep(60)']):
                record_id = capture.start()['id']
            (capture.folder / 'audio.pcm').write_bytes(b'\x00\x10' * 16000)
            failures = []
            def stop():
                try: capture.stop(record_id)
                except ValueError: failures.append('canceled')
            with patch('app.services.offline_input.transcribe', side_effect=decoding):
                worker = threading.Thread(target=stop); worker.start()
                self.assertTrue(entered.wait(2))
                cancel = threading.Thread(target=lambda: capture.cancel(record_id)); cancel.start()
                try:
                    cancel.join(.5)
                    self.assertFalse(cancel.is_alive(), 'Cancel must not wait for model inference')
                    self.assertEqual(list(Path(folder).iterdir()), [])
                finally:
                    release.set(); worker.join(4); cancel.join(4)
            self.assertEqual(failures, ['canceled'])

    def test_decoder_accepts_json_on_stderr_among_diagnostic_lines(self):
        result = SimpleNamespace(returncode=0, stdout='', stderr='loading model\n{invalid diagnostic}\n{"text":"<|zh|>制动器未打开"}\n')
        with patch('pathlib.Path.is_file', return_value=True), patch('app.services.offline_input._decode', return_value=result):
            self.assertEqual(transcribe(Path('sample.wav')), '制动器未打开')

    def test_rejects_command_like_pinyin_and_limits_replay(self):
        for actions in ([{'key': ';rm -rf /'}], [{'candidate': 'x' * 81}], [{'key': 'a'}] * 161):
            with self.assertRaises(ValueError):
                validate_actions(actions)
        self.assertEqual(validate_actions([{'key': 'z'}, {'candidate': '制动器'}]),
                         [{'key': 'z'}, {'candidate': '制动器'}])

    def test_rejects_remote_and_cross_origin_even_on_localhost(self):
        from fastapi import HTTPException
        def request(host, origin):
            return SimpleNamespace(client=SimpleNamespace(host=host),
                                   headers={'host': '127.0.0.1:8081', 'origin': origin,
                                            'x-elevator-input': '1'})
        for req in (request('192.168.1.5', ''), request('127.0.0.1', 'https://evil.example')):
            with self.assertRaises(HTTPException):
                require_local(req)
        require_local(request('127.0.0.1', 'http://127.0.0.1:8081'))

    def test_silence_and_empty_recordings_are_not_transcripts(self):
        for content in (b'', b'\0\0' * 8000):
            with self.assertRaises(ValueError):
                pcm_samples(content)
        duration, peak = pcm_samples(b'\x00\x10' * 16000)
        self.assertEqual(duration, 1)
        self.assertGreater(peak, 0)

    def test_cancel_stops_real_child_and_deletes_temporary_audio(self):
        command = [sys.executable, '-c', 'import time; time.sleep(60)']
        with tempfile.TemporaryDirectory() as folder:
            capture = VoiceCapture(temp_root=Path(folder))
            with patch('app.services.offline_input.capture_command', return_value=command):
                result = capture.start()
            process = capture.process
            self.assertTrue(any(Path(folder).iterdir()))
            capture.cancel(result['id'])
            self.assertIsNotNone(process.poll())
            self.assertEqual(list(Path(folder).iterdir()), [])
            with self.assertRaises(ValueError):
                capture.cancel(result['id'])


if __name__ == '__main__':
    unittest.main()
