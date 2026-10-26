"""Offline input engines. No cloud requests and no business database writes."""
from array import array
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from uuid import uuid4
import wave

BASE = Path(os.environ.get('ELEVATOR_INPUT_DIR', '/userdata/elevator/input'))
RUNTIME = BASE / 'runtime'
MODEL = BASE / 'sensevoice'
PY = '/usr/bin/python3'
DESKTOP = ['runuser', '-u', 'user', '--', 'env',
           'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1002/bus', 'XDG_RUNTIME_DIR=/run/user/1002']
_pinyin_lock = threading.Lock()


def offline_pinyin_ready():
    try:
        config = Path('/home/user/.config/fcitx5/conf/pinyin.conf').read_text()
        return Path('/usr/bin/fcitx5-remote').is_file() and bool(re.search(r'^CloudPinyinEnabled=False\s*$', config, re.M))
    except OSError:
        return False


def validate_actions(actions):
    if not isinstance(actions, list) or len(actions) > 160:
        raise ValueError('拼音输入过长，请先选择候选词')
    for action in actions:
        if not isinstance(action, dict) or len(action) != 1:
            raise ValueError('无效输入动作')
        if 'key' in action:
            key = action['key']
            if not isinstance(key, str) or not (re.fullmatch("[a-z' ]", key) or key == 'BackSpace'):
                raise ValueError('无效拼音按键')
        elif 'candidate' in action:
            text = action['candidate']
            if not isinstance(text, str) or not 1 <= len(text) <= 80:
                raise ValueError('无效候选词')
        elif action != {'page': 'next'}:
            raise ValueError('无效输入动作')
    return actions


def pinyin(actions):
    validate_actions(actions)
    if not offline_pinyin_ready():
        raise ValueError('离线拼音未就绪，请检查输入法并关闭云候选')
    with _pinyin_lock:
        try:
            # Candidate releases can be root-only directories; send trusted source as argv,
            # and user input only through stdin, so the desktop user need not read releases.
            source = Path(__file__).with_name('fcitx_worker.py').read_text(encoding='utf-8')
            result = subprocess.run(DESKTOP + [PY, '-c', source],
                                    input=json.dumps(actions), text=True, capture_output=True, timeout=9)
            data = json.loads(result.stdout)
            if result.returncode or data.get('error'):
                raise ValueError('本机拼音输入暂不可用，请重试')
            return data
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            raise ValueError('本机拼音输入暂不可用，请重试') from None


def capture_command():
    try:
        result = subprocess.run(DESKTOP + ['pactl', 'list', 'short', 'sources'],
                                capture_output=True, text=True, timeout=3, check=True)
        sources = [line.split()[1] for line in result.stdout.splitlines()
                   if len(line.split()) >= 2 and not line.split()[1].endswith('.monitor')]
        if not sources:
            raise ValueError('未发现麦克风，请连接录音设备')
        return DESKTOP + ['/usr/bin/parec', '--device=' + sources[0], '--raw',
                          '--rate=16000', '--channels=1', '--format=s16le', '--latency-msec=60']
    except (OSError, subprocess.SubprocessError):
        raise ValueError('录音设备未就绪') from None


def pcm_samples(content):
    if len(content) < 6400 or len(content) > 16000 * 2 * 31 or len(content) % 2:
        raise ValueError('录音太短或超出30秒，请重新录入')
    samples = array('h', content)
    peak = max(abs(x) for x in samples)
    rms = (sum(x * x for x in samples) / len(samples)) ** .5
    if peak < 120 or rms < 20:
        raise ValueError('未录到清晰声音，请检查麦克风后重试')
    return len(samples) / 16000, peak


def transcribe(path):
    binary = RUNTIME / 'bin/sherpa-onnx-offline'
    model = MODEL / 'model.int8.onnx'
    if not binary.is_file() or not model.is_file():
        raise ValueError('离线语音模型尚未安装')
    env = dict(os.environ, LD_LIBRARY_PATH=str(RUNTIME / 'lib'))
    args = [str(binary), '--sense-voice-model=' + str(model), '--tokens=' + str(MODEL / 'tokens.txt'),
            '--sense-voice-language=auto', '--sense-voice-use-itn=true', '--num-threads=2', str(path)]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=60, env=env)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith('{'):
                    text = json.loads(line).get('text', '').strip()
                    text = re.sub(r'<\|[^>]*\|>', '', text).strip()
                    if text:
                        return text
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    raise ValueError('未能识别出文字，请靠近麦克风重新录入')


class VoiceCapture:
    def __init__(self, temp_root=None):
        self.temp_root = temp_root
        self.lock = threading.RLock()
        self.process = None
        self.folder = None
        self.output = None
        self.timer = None
        self.expiry = None
        self.id = ''

    def start(self):
        with self.lock:
            if self.id:
                raise ValueError('已有录音进行中，请先结束录音')
            self.folder = Path(tempfile.mkdtemp(prefix='elevator-voice-', dir=self.temp_root))
            try:
                self.output = (self.folder / 'audio.pcm').open('wb')
                self.process = subprocess.Popen(capture_command(), stdout=self.output, stderr=subprocess.DEVNULL,
                                                start_new_session=True)
                self.id = uuid4().hex
                # Stop capture at 30s; discard abandoned audio after another 30s.
                self.timer = threading.Timer(30, self._halt)
                self.timer.daemon = True
                self.timer.start()
                current_id = self.id
                self.expiry = threading.Timer(60, lambda: self._expire(current_id))
                self.expiry.daemon = True
                self.expiry.start()
                return {'id': self.id, 'max_seconds': 30}
            except Exception:
                self._cleanup()
                raise ValueError('麦克风无法开启，请检查录音设备') from None

    def _halt(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                try:
                    if os.name == 'posix':
                        os.killpg(self.process.pid, signal.SIGTERM)
                    else:
                        self.process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name == 'posix':
                        os.killpg(self.process.pid, signal.SIGKILL)
                    else:
                        self.process.kill()
                    self.process.wait(timeout=2)
            if self.output:
                self.output.close()

    def _expire(self, record_id):
        with self.lock:
            if self.id == record_id:
                self._halt()
                self._cleanup()

    def _cleanup(self):
        for timer in (self.timer, self.expiry):
            if timer:
                timer.cancel()
        if self.output:
            self.output.close()
        if self.folder:
            shutil.rmtree(self.folder, ignore_errors=True)
        self.id, self.folder, self.output = '', None, None

    def _check(self, record_id):
        if not record_id or record_id != self.id:
            raise ValueError('这次录音已结束，请重新开始')

    def cancel(self, record_id):
        with self.lock:
            self._check(record_id)
            self._halt()
            self._cleanup()

    def stop(self, record_id):
        with self.lock:
            self._check(record_id)
            try:
                self._halt()
                content = (self.folder / 'audio.pcm').read_bytes()
                duration, _ = pcm_samples(content)
                path = self.folder / 'audio.wav'
                with wave.open(str(path), 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(content)
                start = time.monotonic()
                text = transcribe(path)
                return {'text': text, 'duration_seconds': round(duration, 2),
                        'recognition_ms': round((time.monotonic() - start) * 1000)}
            finally:
                self._cleanup()


voice = VoiceCapture()


def status():
    return {'offline': True, 'keyboard': Path('/usr/bin/fcitx5-remote').is_file(),
            'pinyin': offline_pinyin_ready(),
            'voice': (RUNTIME / 'bin/sherpa-onnx-offline').is_file() and (MODEL / 'model.int8.onnx').is_file(),
            'max_seconds': 30}
