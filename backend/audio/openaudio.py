"""Local OpenAudio S1-mini worker; heavy dependencies stay in its private venv."""
import base64
import io
import json
import os
import sys
import threading
import time
import wave
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FISH_REVISION = '781bf1cd7afef831fc58928a6444a2161449dae5'
MODEL_REPO = 'fishaudio/openaudio-s1-mini'
MODEL_FILES = ('config.json', 'model.pth', 'codec.pth', 'tokenizer.tiktoken')
VOICES = ('default', 'voice-1', 'voice-2', 'voice-3')


def validate_request(data):
    text, voice, speed = data.get('text'), data.get('voice'), data.get('speed', 1)
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 450:
        raise ValueError('Текст должен содержать 1–450 символов')
    if voice not in VOICES:
        raise ValueError('Неизвестный голос OpenAudio')
    if type(speed) not in (int, float) or not .65 <= speed <= 1.7:
        raise ValueError('Скорость должна быть в пределах 0.65–1.7')
    return text.strip(), voice, float(speed)


def save_reference(root, data):
    voice, text, encoded = data.get('voice'), data.get('text'), data.get('audio')
    if voice not in VOICES[1:]:
        raise ValueError('Выбери один из трёх референсных голосов')
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
        raise ValueError('Укажи точную расшифровку референса (1–1000 символов)')
    if not isinstance(encoded, str) or len(encoded) > 8_000_000:
        raise ValueError('Референс WAV должен быть не больше 6 МБ')
    try:
        audio = base64.b64decode(encoded, validate=True)
        with wave.open(io.BytesIO(audio), 'rb') as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
            if (wav.getsampwidth() != 2 or wav.getnchannels() not in (1, 2)
                    or rate < 8000 or not 3 <= frames / rate <= 30
                    or len(wav.readframes(frames)) != frames * wav.getnchannels() * 2):
                raise ValueError('Нужен PCM WAV 16 бит длительностью 3–30 секунд')
    except (ValueError, EOFError, wave.Error) as exc:
        raise ValueError('Нужен корректный PCM WAV 16 бит длительностью 3–30 секунд') from exc
    # One atomic record prevents a new waveform from being paired with an old transcript.
    folder = root / 'references'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / (voice + '.json')
    import secrets
    temporary = folder / (voice + '.tmp-' + secrets.token_hex(6))
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump({'audio': encoded, 'text': text.strip()}, output)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {'voice': voice, 'saved': True}


def reference_status(root):
    return [voice for voice in VOICES[1:] if (root / 'references' / (voice + '.json')).is_file()]


class DownloadProgress:
    """Atomic progress snapshots, including heartbeats while the network is idle."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.started = self.activity = time.monotonic()
        self.last_write = 0
        self.samples = []
        self.transfer_started = False
        self.total = self.done = self.checked = self.count = 0
        self.current_size = self.received = self.verified = 0
        self.state = dict(percent=None, step='models', message='Подключение к Hugging Face; получение списка файлов',
                          filename='', files_done=0, files_total=0)

    def __enter__(self):
        self.write(force=True)
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=2)

    def _heartbeat(self):
        while not self.stop.wait(1):
            self.write(force=True)

    def begin(self, name, size, total, count, index):
        with self.lock:
            self.total, self.count, self.current_size = total, count, size
            self.received = self.verified = 0
            self.samples = [(time.monotonic(), 0)]
            self.transfer_started = False
            self.activity = time.monotonic()
            self.state.update(filename=name, message='Скачивание файла', step='models',
                              files_done=index, files_total=count)
            self.write(force=True)

    def transfer(self, received):
        with self.lock:
            received = min(self.current_size, max(0, int(received)))
            if not self.transfer_started:
                self.samples = [(time.monotonic(), received)]
                self.transfer_started = True
            if received != self.received:
                self.activity = time.monotonic()
                self.received = received
                self.samples.append((self.activity, received))
            self.write()

    def verify(self, checked):
        with self.lock:
            if checked != self.verified or self.state['step'] != 'verify':
                self.activity = time.monotonic()
            self.verified = checked
            self.state.update(step='verify', message='Проверка SHA-256',)
            self.write()

    def complete(self):
        with self.lock:
            self.done += self.current_size
            self.checked += self.current_size
            self.received = self.verified = self.current_size = 0
            self.state['files_done'] += 1
            self.activity = time.monotonic()
            self.write(force=True)

    def write(self, force=False):
        with self.lock:
            now = time.monotonic()
            if not force and now - self.last_write < .25:
                return
            self.last_write = now
            while len(self.samples) > 1 and self.samples[1][0] < now - 10:
                self.samples.pop(0)
            speed = 0
            if self.state['step'] == 'models' and self.samples and now - self.activity < 15:
                at, amount = self.samples[0]
                speed = max(0, (self.received - amount) / max(.1, now - at))
            percent = (30 + 60 * (self.done + self.received) / self.total
                       + 4 * (self.checked + self.verified) / self.total) if self.total else None
            payload = dict(self.state, percent=min(94, int(percent)) if percent is not None else None,
                           size=self.current_size, downloaded_bytes=self.received,
                           verified_bytes=self.verified, overall_bytes=self.done + self.received,
                           overall_size=self.total, speed_bytes=int(speed),
                           eta_seconds=int((self.current_size-self.received)/speed) if speed else 0,
                           elapsed_seconds=int(now-self.started), idle_seconds=int(now-self.activity))
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(payload))
            temporary.replace(self.path)


@contextmanager
def hub_progress(report):
    # hf_hub_download has no public per-byte callback. Scope its tqdm adapter to this
    # dedicated downloader process; keep both HTTP and Xet transport and resume support.
    import importlib
    from huggingface_hub import constants
    module = importlib.import_module('huggingface_hub.utils.tqdm')
    original = module.tqdm
    original_chunk = constants.DOWNLOAD_CHUNK_SIZE

    class ReportingTqdm(original):
        def __init__(self, *args, **kwargs):
            self.received = kwargs.get('initial', 0)
            kwargs['disable'] = True
            super().__init__(*args, **kwargs)
            report(self.received)

        def update(self, n=1):
            self.received += n
            report(self.received)
            return super().update(n)

        def reset(self, total=None):
            self.received = 0
            report(0)
            return super().reset(total)

    module.tqdm = ReportingTqdm
    # The default 10 MiB buffer can hide continued HTTP traffic for many seconds.
    constants.DOWNLOAD_CHUNK_SIZE = 512 * 1024
    try:
        yield
    finally:
        module.tqdm = original
        constants.DOWNLOAD_CHUNK_SIZE = original_chunk


def download(root, progress_path=None):
    with DownloadProgress(progress_path) if progress_path else nullcontext() as progress:
        _download(root, progress)


def _download(root, progress):
    """Pin the model snapshot and verify every selected asset before marking it installed."""
    from huggingface_hub import HfApi, hf_hub_download
    import hashlib
    api = HfApi()
    info = api.model_info(MODEL_REPO, files_metadata=True)
    revision = info.sha
    entries = {item.rfilename: item for item in info.siblings}
    manifest = {'revision': revision, 'source_revision': FISH_REVISION, 'files': {}}
    marker = root / 'models' / 'installed.json'
    marker.unlink(missing_ok=True)
    selected = (*MODEL_FILES, *(['special_tokens.json'] if 'special_tokens.json' in entries else []))
    total = sum(entries[name].size for name in selected)
    for index, name in enumerate(selected):
        entry = entries[name]
        # An interrupted Xet reconstruction can leave a sparse temporary file.
        # HTTPS resume may preserve its holes, so retry once from scratch only
        # when the authoritative size/hash check proves the result is invalid.
        for attempt in range(2):
            if progress:
                progress.begin(name, entry.size, total, len(selected), index)
            options = {'force_download': True} if attempt else {}
            with hub_progress(progress.transfer) if progress else nullcontext():
                path = Path(hf_hub_download(MODEL_REPO, name, revision=revision,
                                           local_dir=root / 'models', **options))
            if path.stat().st_size != entry.size:
                if attempt == 0:
                    print('Incomplete file; downloading again: ' + name, flush=True)
                    continue
                raise RuntimeError('Неполный файл модели: ' + name)
            if progress:
                progress.transfer(entry.size)
                progress.verify(0)
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.stat().st_size < 1_000_000 else None
            lfs = entry.lfs
            if lfs:
                sha = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        sha.update(chunk)
                        if progress:
                            progress.verify(stream.tell())
                digest = sha.hexdigest()
                if digest != lfs.sha256:
                    if attempt == 0:
                        print('Checksum mismatch; downloading again: ' + name, flush=True)
                        continue
                    raise RuntimeError('Контрольная сумма модели не совпадает: ' + name)
            break
        manifest['files'][name] = {'size': entry.size, 'sha256': digest}
        if progress:
            progress.complete()
        print('Downloaded and verified: ' + name, flush=True)
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest))
    temporary.replace(marker)


def worker(root, port):
    # Pinned upstream is placed ahead of this application's packages only in the worker.
    source = root / 'fish-speech'
    sys.path.insert(0, str(source))
    import numpy as np
    import soundfile as sf
    import torch
    import librosa
    from fish_speech.inference_engine import TTSInferenceEngine
    from fish_speech.models.dac.inference import load_model
    from fish_speech.models.text2semantic.inference import launch_thread_safe_queue
    from fish_speech.utils.schema import ServeTTSRequest, ServeReferenceAudio
    from backend.audio.addons import valid_wav

    torch.set_num_threads(min(8, os.cpu_count() or 1))
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    # Float32 CPU avoids unsupported/slow bf16 kernels. MPS is not claimed as supported.
    precision = torch.bfloat16 if device == 'cuda' else torch.float32
    models = root / 'models'
    queue = launch_thread_safe_queue(checkpoint_path=models, device=device,
                                    precision=precision, compile=False)
    decoder = load_model('modded_dac_vq', str(models / 'codec.pth'), device=device)
    engine = TTSInferenceEngine(llama_queue=queue, decoder_model=decoder,
                                precision=precision, compile=False)
    lock = threading.Lock()

    def infer(data):
        text, voice, speed = validate_request(data)
        references = []
        if voice != 'default':
            path = root / 'references' / (voice + '.json')
            if not path.is_file():
                raise ValueError('Сначала загрузи WAV и расшифровку для выбранного голоса')
            reference = json.loads(path.read_text())
            references = [ServeReferenceAudio(audio=base64.b64decode(reference['audio']), text=reference['text'])]
        request = ServeTTSRequest(text=text, references=references, format='wav',
                                  streaming=False, use_memory_cache='off', max_new_tokens=1024)
        final = None
        for result in engine.inference(request):
            if result.code == 'error':
                raise RuntimeError(str(result.error))
            if result.code == 'final':
                final = result.audio
        if final is None:
            raise RuntimeError('OpenAudio не вернула аудио')
        rate, samples = final
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if speed != 1:
            samples = librosa.effects.time_stretch(samples, rate=speed)
        output = io.BytesIO()
        sf.write(output, samples, rate, format='WAV', subtype='PCM_16')
        audio = output.getvalue()
        if not valid_wav(audio):
            raise RuntimeError('OpenAudio вернула пустой или неслышимый WAV')
        return audio

    # Readiness means the complete model has generated real, audible PCM.
    with lock:
        infer({'text': 'Hello.', 'voice': 'default'})

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, kind, body):
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if not self.guard():
                return
            if self.path == '/health':
                self.reply(200, 'application/json', b'{"status":"ok"}')
            else:
                self.reply(404, 'application/json', b'{}')

        def do_POST(self):
            if not self.guard():
                return
            if self.path != '/speak':
                return self.reply(404, 'application/json', b'{}')
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 1 <= size <= 10000:
                    raise ValueError('Некорректный размер запроса')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('Ожидался JSON-объект')
                with lock:
                    audio = infer(data)
                self.reply(200, 'audio/wav', audio)
            except (ValueError, OSError, RuntimeError) as exc:
                code = 400 if isinstance(exc, ValueError) else 503
                self.reply(code, 'application/json', json.dumps({'error': str(exc)[:300]}).encode())

        def guard(self):
            if (self.headers.get('Host') != f'127.0.0.1:{port}' or self.headers.get('Origin')
                    or self.headers.get('Sec-Fetch-Site', '') not in ('', 'none')):
                self.reply(403, 'application/json', b'{"error":"Local backend requests only"}')
                return False
            return True

    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()


def check_runtime(root):
    sys.path.insert(0, str(root / 'fish-speech'))
    import librosa
    import soundfile
    import torch
    from fish_speech.inference_engine import TTSInferenceEngine
    from fish_speech.models.dac.inference import load_model
    from fish_speech.models.text2semantic.inference import launch_thread_safe_queue
    from fish_speech.utils.schema import ServeTTSRequest, ServeReferenceAudio
    print('Fish Speech inference dependencies OK; CUDA:', torch.cuda.is_available(), flush=True)


def download_command(root, progress_path=None):
    # Apply before importing huggingface_hub: its transport constants are read once.
    # Keep an explicit operator override; TLS, gated access and checksums stay intact.
    os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
    os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '30')
    from huggingface_hub import get_token
    from huggingface_hub.utils import GatedRepoError
    try:
        download(root, progress_path) if progress_path else download(root)
        return 0
    except GatedRepoError:
        # Keep these lines short: the installer surfaces the final three log lines.
        print('Hugging Face ограничивает доступ к S1-mini.', file=sys.stderr)
        print('Прими условия: https://huggingface.co/fishaudio/openaudio-s1-mini', file=sys.stderr)
        if get_token():
            print('Токен найден: проверь одобрение доступа и права fine-grained токена. Инструкция — в панели S1-mini.', file=sys.stderr)
        else:
            print('Выполни hf auth login в окружении модели (см. README), затем повтори установку.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    if sys.argv[1] == '--download':
        raise SystemExit(download_command(Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else None))
    elif sys.argv[1] == '--worker':
        worker(Path(sys.argv[2]), int(sys.argv[3]))
    elif sys.argv[1] == '--check-runtime':
        check_runtime(Path(sys.argv[2]))
    else:
        raise SystemExit('Use --download ROOT or --worker ROOT PORT')
