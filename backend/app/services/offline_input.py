"""Offline input engines. No cloud requests and no business database writes."""
from array import array
import base64
import json
import os
import socket
import struct
from pathlib import Path
import re
import shutil
import select
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
_pinyin_worker = None
_pinyin_source = ''


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


def _stop_pinyin_worker():
    global _pinyin_worker
    proc = _pinyin_worker
    _pinyin_worker = None
    if proc is not None:
        try:
            proc.kill()
        except OSError:
            pass


def _ensure_pinyin_worker():
    global _pinyin_worker, _pinyin_source
    if _pinyin_worker is not None and _pinyin_worker.poll() is None:
        return _pinyin_worker
    # Candidate releases can be root-only directories; send trusted source as argv,
    # and user input only through stdin, so the desktop user need not read releases.
    _pinyin_source = Path(__file__).with_name('fcitx_worker.py').read_text(encoding='utf-8')
    _pinyin_worker = subprocess.Popen(
        DESKTOP + [PY, '-u', '-c', _pinyin_source],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1, start_new_session=True,
    )
    return _pinyin_worker


def pinyin(actions):
    validate_actions(actions)
    if not offline_pinyin_ready():
        raise ValueError('离线拼音未就绪，请检查输入法并关闭云候选')
    with _pinyin_lock:
        try:
            for _ in range(2):
                proc = _ensure_pinyin_worker()
                if proc.stdin is None or proc.stdout is None:
                    raise OSError('pinyin worker pipe unavailable')
                proc.stdin.write(json.dumps(actions, ensure_ascii=False) + '\n')
                proc.stdin.flush()
                ready, _, _ = select.select([proc.stdout], [], [], 9)
                if not ready:
                    raise TimeoutError('pinyin worker timeout')
                line = proc.stdout.readline()
                if not line:
                    raise OSError('pinyin worker exited')
                data = json.loads(line)
                if data.get('error'):
                    raise ValueError('本机拼音输入暂不可用，请重试')
                return data
            raise ValueError('本机拼音输入暂不可用，请重试')
        except (OSError, TimeoutError, subprocess.SubprocessError, json.JSONDecodeError):
            _stop_pinyin_worker()
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


ASR_PORT = 6007
_ASR_SERVER = RUNTIME / 'bin/sherpa-onnx-offline-websocket-server'
_ASR_PROC = None
_ASR_LOCK = threading.RLock()
_ASR_IDLE = None
_ASR_LAST = 0.0


def _asr_port_open(timeout=0.3):
    try:
        with socket.create_connection(('127.0.0.1', ASR_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _stop_asr_server():
    global _ASR_PROC
    with _ASR_LOCK:
        proc = _ASR_PROC
        _ASR_PROC = None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


def _schedule_asr_idle():
    global _ASR_IDLE
    if _ASR_IDLE:
        _ASR_IDLE.cancel()
    timer = threading.Timer(120, _stop_asr_server)
    timer.daemon = True
    _ASR_IDLE = timer
    timer.start()


def _start_asr_server():
    global _ASR_PROC
    with _ASR_LOCK:
        if _asr_port_open():
            _schedule_asr_idle()
            return True
        if _ASR_PROC and _ASR_PROC.poll() is None:
            return True
        if not _ASR_SERVER.is_file():
            return False
        env = dict(os.environ, LD_LIBRARY_PATH=str(RUNTIME / 'lib'))
        args = [str(_ASR_SERVER), '--port=' + str(ASR_PORT),
                '--num-work-threads=2', '--max-batch-size=1',
                '--max-utterance-length=30',
                '--sense-voice-model=' + str(MODEL / 'model.int8.onnx'),
                '--tokens=' + str(MODEL / 'tokens.txt'),
                '--sense-voice-language=auto', '--sense-voice-use-itn=true']
        log = open('/tmp/elevator-asr.log', 'ab')
        _ASR_PROC = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                                     env=env, start_new_session=True)
        _schedule_asr_idle()
        return True


def warm_asr_server():
    """录音开始时在后台加载常驻模型，避免松开后才开始 7 秒模型加载。"""
    if _asr_port_open():
        return
    try:
        _start_asr_server()
    except OSError:
        pass


def _ensure_asr_server(wait=4.0):
    if _asr_port_open():
        _schedule_asr_idle()
        return True
    try:
        if not _start_asr_server():
            return False
    except OSError:
        return False
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if _asr_port_open():
            _schedule_asr_idle()
            return True
        time.sleep(0.1)
    return False


def _ws_send(sock, data, opcode=2):
    mask = os.urandom(4)
    n = len(data)
    if n < 126:
        header = bytes([0x80 | opcode, 0x80 | n])
    elif n < 65536:
        header = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack('!H', n)
    else:
        header = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack('!Q', n)
    sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def _ws_recv(sock):
    head = sock.recv(2)
    if len(head) < 2:
        return b''
    n = head[1] & 0x7f
    if n == 126:
        n = struct.unpack('!H', sock.recv(2))[0]
    elif n == 127:
        n = struct.unpack('!Q', sock.recv(8))[0]
    return sock.recv(n)


def _ws_transcribe(content):
    samples = content
    if len(samples) % 2:
        samples = samples[:-1]
    pcm = array('h', samples)
    floats = array('f', (x / 32768.0 for x in pcm))
    payload = struct.pack('<i', 16000) + struct.pack('<i', len(floats) * 4) + floats.tobytes()
    with socket.create_connection(('127.0.0.1', ASR_PORT), timeout=10) as sock:
        key = base64.b64encode(os.urandom(16)).decode()
        req = '\r\n'.join([
            'GET / HTTP/1.1',
            'Host: 127.0.0.1:%d' % ASR_PORT,
            'Upgrade: websocket',
            'Connection: Upgrade',
            'Sec-WebSocket-Key: %s' % key,
            'Sec-WebSocket-Version: 13',
            '', '',
        ]).encode()
        sock.sendall(req)
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += sock.recv(4096)
        if b'101' not in buf.split(b'\r\n', 1)[0]:
            raise ValueError('asr handshake failed')
        for i in range(0, len(payload), 10240):
            _ws_send(sock, payload[i:i + 10240])
        raw = _ws_recv(sock)
        try:
            _ws_send(sock, b'Done', 1)
        except OSError:
            pass
    data = json.loads(raw.decode('utf8'))
    return str(data.get('text') or '').strip()


def transcribe(path, cancel=None):
    binary = RUNTIME / 'bin/sherpa-onnx-offline'
    model = MODEL / 'model.int8.onnx'
    if not binary.is_file() or not model.is_file():
        raise ValueError('离线语音模型尚未安装')
    try:
        content = Path(path).read_bytes()
    except OSError:
        content = b''
    if content and _ensure_asr_server(wait=1.5):
        try:
            text = _ws_transcribe(content)
            if text:
                _schedule_asr_idle()
                return text
        except Exception:
            pass
    env = dict(os.environ, LD_LIBRARY_PATH=str(RUNTIME / 'lib'))
    args = [str(binary), '--sense-voice-model=' + str(model), '--tokens=' + str(MODEL / 'tokens.txt'),
            '--sense-voice-language=auto', '--sense-voice-use-itn=true', '--num-threads=2', str(path)]
    try:
        result = _decode(args, env, cancel)
        if result.returncode == 0:
            for line in (result.stdout + '\n' + result.stderr).splitlines():
                if line.startswith('{'):
                    try:
                        data = json.loads(line)
                    except ValueError:
                        continue
                    text = data.get('text', '') if isinstance(data, dict) else ''
                    if not isinstance(text, str):
                        continue
                    text = text.strip()
                    text = re.sub(r'<\|[^>]*\|>', '', text).strip()
                    if text:
                        return text
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    raise ValueError('未能识别出文字，请靠近麦克风重新录入')


def _decode(args, env, cancel):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, env=env)
    started = time.monotonic()
    try:
        while True:
            if (cancel and cancel.is_set()) or time.monotonic() - started > 60:
                raise ValueError('语音识别已取消或超时')
            try:
                stdout, stderr = process.communicate(timeout=.1)
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()


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
        self.canceled = threading.Event()
        self.decoding = False

    def start(self):
        with self.lock:
            if self.id:
                raise ValueError('已有录音进行中，请先结束录音')
            self.canceled = threading.Event()
            self.decoding = False
            self.folder = Path(tempfile.mkdtemp(prefix='elevator-voice-', dir=self.temp_root))
            try:
                self.output = (self.folder / 'audio.pcm').open('wb')
                self.process = subprocess.Popen(capture_command(), stdout=self.output, stderr=subprocess.DEVNULL,
                                                start_new_session=True)
                # 录音期间后台预热常驻模型；松开时通常已可做 200ms 级识别。
                threading.Thread(target=warm_asr_server, daemon=True).start()
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
        self.canceled.set()
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
            if self.decoding:
                raise ValueError('正在识别，请稍候')
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
                canceled = self.canceled
                self.decoding = True
            except Exception:
                self._cleanup()
                raise
        try:
            start = time.monotonic()
            text = transcribe(path, canceled)
            if canceled.is_set():
                raise ValueError('语音识别已取消')
            return {'text': text, 'duration_seconds': round(duration, 2),
                    'recognition_ms': round((time.monotonic() - start) * 1000)}
        finally:
            with self.lock:
                if self.id == record_id:
                    self._cleanup()


voice = VoiceCapture()


def status():
    return {'offline': True, 'keyboard': Path('/usr/bin/fcitx5-remote').is_file(),
            'pinyin': offline_pinyin_ready(),
            'voice': (RUNTIME / 'bin/sherpa-onnx-offline').is_file() and (MODEL / 'model.int8.onnx').is_file(),
            'max_seconds': 30}
