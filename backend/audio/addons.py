"""Локальные голосовые движки: изолированные установщики, отменяемые загрузки, воркеры.

Ничего не скачивается до явной установки; глобальный pip не меняется.
Kokoro RU использует свой KModel-воркер; Piper и Silero — этот модуль.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import platform

from .qwen3 import QWEN3_BUILTIN, QWEN3_MODEL_FOLDERS, QWEN3_VOICES_DIR
from .openaudio import FISH_REVISION, MODEL_FILES, VOICES as OPENAUDIO_VOICES

# Корень проекта нужен для запуска воркеров как модулей (python -m backend.audio.*).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Общая папка данных приложения; рядом живут остальные голосовые движки.
APP = (Path.home() / 'Library' / 'Application Support' / 'YapdOme'
       if platform.system() == 'Darwin'
       else Path.home() / '.local' / 'share' / 'YapdOme')

VOICE_NAMES = {
    "kokoro-ru": ("sveta", "masha", "dima"),
    "kokoro": ("af_heart", "af_bella", "af_sarah", "af_nicole", "af_sky",
               "am_adam", "am_michael", "am_echo", "am_puck",
               "bf_emma", "bf_isabella", "bm_george", "bm_lewis"),
    "piper": ("dmitri", "irina", "ruslan", "denis"),
    "silero": ("aidar", "baya", "kseniya", "xenia", "eugene"),
    "qwen3-tts": QWEN3_BUILTIN,
    "openaudio-s1-mini": OPENAUDIO_VOICES,
}
PIPER_ORIGIN = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
SILERO_ORIGIN = "https://models.silero.ai/models/tts/ru/v5_ru.pt"
KOKORO_ORIGIN = "https://huggingface.co/zaakirio/kokoro-ru/resolve/main/"
EN_KOKORO_ORIGIN = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"
# Minimal acute-aware espeak-ng data used by Russian phonemization.
# Fetch individual files instead of snapshot_download(espeak-data/**), which
# requests hundreds of irrelevant dictionaries and may hit anonymous HF limits.
RU_ESPEAK_FILES = (
    "espeak-data/phontab",
    "espeak-data/phonindex",
    "espeak-data/phondata",
    "espeak-data/intonations",
    "espeak-data/ru_dict",
    "espeak-data/lang/zle/ru",
)
RU_FILES = ("kokoro-ru-v2-base.pth", "kokoro-ru-v2-dima.pth",
            "voices/sveta.pt", "voices/masha.pt", "voices/dima.pt",
            "ru_g2p.py", "kokoro-config.json") + RU_ESPEAK_FILES


def ruaccent_location(model_root):
    """Find RUAccent only in Kokoro's venv, never the system site-packages."""
    base = model_root / "venv"
    for directory in (base / "lib", base / "lib64"):
        for package in directory.glob("python*/site-packages/ruaccent"):
            if package.is_dir():
                return package
    return None


def ruaccent_ready(model_root):
    location = ruaccent_location(model_root)
    if location is None:
        return False
    from .ruaccent_repair import check_essential
    return not check_essential(location)


def complete_asset(root, name):
    """Small espeak language definitions can legitimately be under 1 KiB."""
    target = root / name
    try:
        minimum = 1 if name.startswith("espeak-data/lang/") else (64 if name == "espeak-data/intonations" else 1024)
        return target.is_file() and target.stat().st_size >= minimum
    except OSError:
        return False
PYTHON_CANDIDATES = ("python3.12", "python3.11", "python3.13", "python3.10")


def safe_directory(value, kind):
    """Never install into arbitrary system, repo or application-code directories."""
    if not isinstance(value, str) or not value.strip() or len(value) > 1024 or "\x00" in value:
        raise ValueError("Укажи папку установки")
    root = Path(os.path.expandvars(value.strip())).expanduser().resolve()
    home = Path.home().resolve()
    volumes = Path("/Volumes")
    if not root.is_absolute() or root in (home, volumes, APP.resolve()):
        raise ValueError("Выбери отдельную папку внутри домашнего каталога или /Volumes")
    try:
        allowed = root.is_relative_to(home) or root.is_relative_to(volumes)
    except ValueError:
        allowed = False
    if not allowed or len(root.parts) < 4:
        raise ValueError("Каталог должен находиться в домашней папке или на /Volumes")
    if root.is_file() or (root / ".git").exists() or (root / "backend").is_dir():
        raise ValueError("Нельзя устанавливать модель в каталог исходного кода")
    if root.exists() and any(root.iterdir()):
        # Switching back to an existing model installation is allowed.
        known = any((root / n).exists() for n in ("venv", ".voice-engine", "worker.log",
                    "kokoro-ru-v2-base.pth", "kokoro-v1.0.int8.onnx", "v5_ru.pt", "ru_RU-dmitri-medium.onnx"))
        if not known:
            raise ValueError("Папка не пуста; выбери пустой каталог модели")
        marker = root / ".voice-engine"
        if marker.exists() and marker.read_text().strip() != kind:
            raise ValueError("Папка уже используется другим звуковым движком")
    return root


def pick_directory(kind):
    if sys.platform != "darwin":
        raise ValueError("Выбор папки через Finder доступен только на macOS")
    labels = {"kokoro-ru": "Kokoro RU", "kokoro": "Kokoro 82M", "piper": "Piper", "silero": "Silero",
              "openaudio-s1-mini": "OpenAudio S1-mini"}
    name = kind.replace("-", "_")
    script = 'POSIX path of (choose folder with prompt "Папка установки ' + labels[kind] + '")'
    done = subprocess.run(["/usr/bin/osascript", "-e", script],
                          text=True, capture_output=True, timeout=180)
    if done.returncode:
        raise ValueError("Папка не выбрана")
    base = Path(done.stdout.strip()).expanduser()
    if base.name != name:
        base = base / name
    return str(safe_directory(str(base), kind))

def valid_wav(blob):
    """Detect empty or nearly silent synthesis using only the Python stdlib."""
    import array
    try:
        with wave.open(io.BytesIO(blob), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                return False
            if wav.getframerate() < 8000 or wav.getnframes() < 1600:
                return False
            frames = wav.getnframes()
            raw = wav.readframes(frames)
            if len(raw) != frames * 2:
                return False
        samples = array.array("h")
        samples.frombytes(raw)
        if sys.byteorder != "little":
            samples.byteswap()
        return any(abs(samples[i]) > 20 for i in range(0, len(samples), 19))
    except (OSError, ValueError, EOFError, wave.Error):
        return False



class Cancelled(Exception):
    pass


class Addon:
    startup_timeout = 120

    def __init__(self, kind):
        self.kind = kind
        self.root = APP / kind
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._child = None
        self._process = None
        self._started_at = 0.0
        self._last_failure = ""
        self._health_at = 0.0
        self._health_result = False
        self._last_exit = None
        self.port = {"kokoro-ru": 8768, "kokoro": 8767, "piper": 8769, "silero": 8770, "qwen3-tts": 8771, "openaudio-s1-mini": 8772}[kind]
        self.progress = {"running": False, "percent": None, "message": "", "error": "",
                         "filename": "", "downloaded_bytes": 0, "total_bytes": 0,
                         "step": "", "speed_bytes": 0, "eta_seconds": 0,
                         "files_done": 0, "files_total": 0}
        self._install_size = None
        self._restore_root()

    def _settings_file(self):
        return APP / (self.kind + "-directory.json")

    def _restore_root(self):
        try:
            value = json.loads(self._settings_file().read_text())["directory"]
            self.root = safe_directory(value, self.kind)
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def _save_root(self):
        APP.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self._settings_file()
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps({"directory": str(self.root)}))
        os.chmod(temp, 0o600)
        temp.replace(path)

    def expected_files(self):
        if self.kind == "kokoro-ru":
            return RU_FILES
        if self.kind == "kokoro":
            return ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
        if self.kind == "silero":
            return ("v5_ru.pt",)
        return tuple(n for voice in VOICE_NAMES["piper"] for n in
                     ("ru_RU-" + voice + "-medium.onnx",
                      "ru_RU-" + voice + "-medium.onnx.json"))

    @property
    def installed(self):
        files_ready = (self.root / "venv/bin/python").is_file() and all(
            complete_asset(self.root, name) for name in self.expected_files())
        if self.kind == "kokoro-ru":
            return files_ready and ruaccent_ready(self.root)
        return files_ready

    def _log_tail(self):
        """Read a bounded diagnostic tail; never load an unlimited traceback into RAM."""
        try:
            with (self.root / "worker.log").open("rb") as log:
                log.seek(0, 2)
                size = log.tell()
                log.seek(max(0, size - 4096))
                lines = log.read().decode("utf-8", "replace").strip().splitlines()
            return " | ".join(line.strip()[:250] for line in lines[-4:])[:650]
        except OSError:
            return ""

    def _poll_process(self):
        child = self._process
        if child is None:
            return None
        exit_code = child.poll()
        if exit_code is not None:
            if self._last_exit is None:
                self._last_exit = exit_code
                message = self._log_tail()
                self._last_failure = (
                    f"Движок {self.kind} завершился (код {exit_code}). "
                    + (message or "Смотри worker.log в папке модели.")
                )[:750]
            self._health_result = False
            return exit_code
        return None

    def _health(self):
        # Never accept an unrelated localhost process as a healthy voice worker.
        if self._process is None or self._poll_process() is not None:
            return False
        now = time.monotonic()
        if now - self._health_at < .6:
            return self._health_result
        ready = False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=.4) as response:
                ready = (response.status == 200
                         and json.loads(response.read(128)).get("status") == "ok")
        except (OSError, ValueError):
            pass
        self._health_at = time.monotonic()
        self._health_result = ready
        return ready

    def status(self):
        with self._lock:
            state = dict(self.progress)
            child = self._process
            exit_code = self._poll_process()
            failure = self._last_failure
            started = self._started_at
        present = self.installed
        ready = self._health() if present and child is not None and exit_code is None else False
        if ready:
            status = "ready"
        elif state["running"]:
            status = "installing"
        elif not present:
            status = "missing"
        elif exit_code is not None or failure:
            status = "error"
        elif child is not None:
            status = "starting"
        else:
            status = "stopped"
        # Heavy PyTorch startup gets 120 seconds; no endless spinner.
        if status == "starting" and started and time.monotonic() - started > self.startup_timeout:
            self.stop()
            self._last_failure = (
                f"Модель {self.kind} не ответила за {self.startup_timeout} секунд. "
                + (self._log_tail() or "Проверь worker.log.")
            )[:750]
            status = "error"
            failure = self._last_failure
        return {"engine": self.kind, "installed": present, "ready": ready and status == "ready",
                "status": status, "error": failure if status == "error" else "",
                "installation": state, "directory": str(self.root),
                "voices": VOICE_NAMES[self.kind], "pid": child.pid if child and exit_code is None else None}

    def start(self, *, force=False):
        with self._lock:
            if not self.installed:
                self._last_failure = "Модель не установлена полностью."
                return False
            if self._process is not None:
                exit_code = self._poll_process()
                if exit_code is None:
                    return True
                if not force:
                    # Never mask the real traceback with an infinite restart loop.
                    return False
            if self._last_failure and not force:
                return False
            self._last_failure = ""
            self._last_exit = None
            self._health_at = 0.0
            self._health_result = False
            command = self._worker_command()
            try:
                with (self.root / "worker.log").open("ab") as log:
                    log.write(("\\n--- " + time.strftime("%Y-%m-%d %H:%M:%S")
                               + " starting " + self.kind + " ---\\n").encode())
                    self._process = subprocess.Popen(command, cwd=PROJECT_ROOT,
                           stdin=subprocess.DEVNULL, stdout=log, stderr=log)
                self._started_at = time.monotonic()
                return True
            except OSError as exc:
                self._last_failure = ("Не удалось запустить " + self.kind + ": " + str(exc))[:400]
                return False

    def await_ready(self, timeout=120):
        """Wait for cold model loading once, never restart a crashed worker."""
        if not self.start():
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._poll_process() is not None:
                return False
            if self._health():
                return True
            if self._cancel.is_set():
                return False
            time.sleep(.3)
        self._last_failure = (
            f"{self.kind}: превышено время загрузки модели ({int(timeout)} с). "
            + (self._log_tail() or "Смотри worker.log.")
        )[:750]
        self.stop()
        return False

    def install(self, directory=None, size=None):
        with self._lock:
            if self.progress["running"]:
                return self.status()
            target = safe_directory(directory or str(self.root), self.kind)
            if target != self.root:
                self.stop()
            self.root = target
            self._last_failure = ""
            self._last_exit = None
            self._process = None
            self._cancel.clear()
            self._install_size = size
            self.progress = {"running": True, "percent": 0, "message": "Подготовка",
                             "error": "", "filename": "", "downloaded_bytes": 0, "total_bytes": 0,
                             "step": "prepare", "speed_bytes": 0, "eta_seconds": 0,
                             "files_done": 0, "files_total": 0}
            threading.Thread(target=self._install, daemon=True).start()
        return self.status()

    def cancel(self):
        self._cancel.set()
        with self._lock:
            child = self._child
            if child is not None and child.poll() is None:
                child.terminate()
        return self.status()

    def _check(self):
        if self._cancel.is_set():
            raise Cancelled()

    def _update(self, **items):
        with self._lock:
            self.progress.update(items)

    def _read_progress(self, path):
        if path is None or not path.is_file():
            return
        try:
            progress = json.loads(path.read_text())
            if "percent" in progress:
                percent = progress["percent"]
                percent = min(100, int(percent)) if percent is not None else None
            else:
                done, total = progress.get("done", 0), progress.get("total", 0)
                percent = 94 + int(4 * done / total) if total else 94
            self._update(percent=percent, message=progress.get("message", "Подготовка"),
                         filename=progress.get("filename", ""), total_bytes=progress.get("size", 0),
                         downloaded_bytes=progress.get("downloaded_bytes", 0), step=progress.get("step", ""),
                         speed_bytes=progress.get("speed_bytes", 0), eta_seconds=progress.get("eta_seconds", 0),
                         files_done=progress.get("files_done", 0), files_total=progress.get("files_total", 0),
                         verified_bytes=progress.get("verified_bytes", 0),
                         overall_bytes=progress.get("overall_bytes", 0), overall_size=progress.get("overall_size", 0),
                         elapsed_seconds=progress.get("elapsed_seconds", 0), idle_seconds=progress.get("idle_seconds", 0))
        except (OSError, ValueError, TypeError, ZeroDivisionError):
            pass

    def _run(self, args, timeout=600, progress_file=None, cwd=None):
        self._check()
        with (self.root / "install.log").open("ab") as log:
            child = subprocess.Popen(args, cwd=cwd or self.root, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT)
            with self._lock:
                self._child = child
            try:
                start = time.monotonic()
                while child.poll() is None:
                    self._check()
                    self._read_progress(progress_file)
                    if time.monotonic() - start > timeout:
                        child.terminate()
                        raise TimeoutError("Таймаут установки; подробности в install.log")
                    time.sleep(.2)
                self._read_progress(progress_file)
                if child.returncode:
                    # Surface the immediate dependency failure instead of another
                    # opaque "install.log" instruction or a 120s retry loop.
                    try:
                        with (self.root / "install.log").open("rb") as log:
                            log.seek(0, 2)
                            log.seek(max(0, log.tell() - 3000))
                            tail = log.read().decode("utf-8", "replace").strip().splitlines()
                        detail = " | ".join(line[:130] for line in tail[-3:])[:370]
                    except OSError:
                        detail = ""
                    raise RuntimeError("Ошибка подготовки среды: " +
                                       (detail or "проверь install.log в папке модели"))
            finally:
                with self._lock:
                    self._child = None

    def _python(self):
        for name in PYTHON_CANDIDATES:
            candidate = shutil.which(name)
            if candidate:
                return candidate
        if (3, 10) <= sys.version_info[:2] <= (3, 13):
            return sys.executable
        return None

    def _venv(self):
        env = self.root / "venv"
        if (env / "bin/python").is_file():
            vpy = env / "bin/python"
            check = subprocess.run([str(vpy), "-m", "pip", "--version"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if check.returncode == 0:
                return vpy
            # Recover an unseeded uv environment from a previous installation.
            installer = shutil.which("uv") or str(APP / ".uv-bootstrap/bin/uv")
            if Path(installer).is_file():
                self._run([installer, "pip", "install", "--python", str(vpy), "pip"], 180)
            else:
                self._run([str(vpy), "-m", "ensurepip", "--upgrade"], 180)
            return vpy
        python = self._python()
        if python:
            self._update(message="Создание отдельного окружения Python", percent=5, step="python")
            self._run([python, "-m", "venv", str(env)], 180)
        else:
            # On Macs running only Python 3.14, opt-in installation downloads
            # isolated uv then lets uv obtain Python 3.12. Never changes system Python.
            self._update(message="Подготовка Python 3.12 через uv", percent=3, step="python")
            uv = shutil.which("uv")
            if not uv:
                bootstrap = APP / ".uv-bootstrap"
                py = bootstrap / "bin/python"
                if not py.is_file():
                    self._run([sys.executable, "-m", "venv", str(bootstrap)], 180)
                self._run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "uv"], 360)
                uv = str(bootstrap / "bin/uv")
            self._run([uv, "venv", "--seed", "--python", "3.12", str(env)], 420)
        return env / "bin/python"

    def _worker_module(self):
        if self.kind == "kokoro-ru":
            return "backend.audio.kokoro_ru"
        if self.kind == "kokoro":
            return "backend.audio.kokoro"
        return "backend.audio.addons"

    def _worker_command(self):
        python = str(self.root / "venv/bin/python")
        command = [python, "-m", self._worker_module(), "--worker",
                   self.kind, str(self.root), str(self.port)]
        if self.kind in ("kokoro-ru", "kokoro"):
            command = [python, "-m", self._worker_module(),
                       "--worker", str(self.root), str(self.port)]
        return command

    def _url(self, name):
        if self.kind == "kokoro-ru":
            return KOKORO_ORIGIN + name
        if self.kind == "kokoro":
            return EN_KOKORO_ORIGIN + name
        if self.kind == "silero":
            return SILERO_ORIGIN
        voice = name.split("-")[1]
        return PIPER_ORIGIN + f"ru/ru_RU/{voice}/medium/{name}"

    def _download(self, name, i, total):
        self._check()
        target = self.root / name
        if complete_asset(self.root, name):
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        existing = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "YapdOme-LocalVoice/0.2.0"}
        if existing:
            headers["Range"] = "bytes=" + str(existing) + "-"
        request = urllib.request.Request(self._url(name), headers=headers)
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=100) as resp:
            if existing and resp.status != 206:
                existing = 0
            total_size = int(resp.headers.get("Content-Length", "0") or 0) + existing
            with part.open("ab" if existing else "wb") as out:
                done = existing
                while True:
                    self._check()
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    fraction = done / total_size if total_size else 0
                    percent = 40 + round(55 * (i + fraction) / total)
                    elapsed = max(.001, time.monotonic() - started)
                    speed = (done - existing) / elapsed
                    remaining = total_size - done
                    eta = remaining / speed if speed > 0 else 0
                    self._update(percent=percent, step="models",
                                 message=f"Загрузка {name} ({i + 1}/{total})",
                                 filename=name, downloaded_bytes=done, total_bytes=total_size,
                                 speed_bytes=round(speed), eta_seconds=round(eta),
                                 files_done=i, files_total=total)
        if part.stat().st_size < (1 if name.startswith("espeak-data/lang/") else (64 if name == "espeak-data/intonations" else 1024)):
            raise RuntimeError("Загружен неполный или пустой файл " + name)
        part.replace(target)

    def _install(self):
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / ".voice-engine").write_text(self.kind)
            self._save_root()
            py = self._venv()
            self._check()
            self._update(percent=15, message="Установка зависимостей", step="deps")
            if self.kind == "kokoro-ru":
                packages = ("kokoro>=0.9.4,<1.0", "ruaccent", "huggingface_hub")
            elif self.kind == "piper":
                packages = ("piper-tts",)
            elif self.kind == "kokoro":
                packages = ("kokoro-onnx>=0.3.8,<1.0",)
            else:
                # Installed Silero V5 imports scipy when unpickled.
                packages = ("torch", "numpy", "scipy")
            self._run([str(py), "-m", "pip", "install", "--disable-pip-version-check", *packages], 900)
            self._check()
            files = self.expected_files()
            missing = [name for name in files if not complete_asset(self.root, name)]
            if missing:
                self._update(message="Восстановление недостающих файлов модели",
                             percent=40, filename=missing[0], step="models")
            # Keep existing weights: no snapshot, no thousands of HF requests,
            # no restart until EVERY required data file has been checked.
            for i, name in enumerate(files):
                self._download(name, i, len(files))
            missing = [name for name in files if not complete_asset(self.root, name)]
            if missing:
                raise RuntimeError("Файлы Kokoro не загружены: " + ", ".join(missing[:5]))
            if self.kind == "kokoro-ru":
                try:
                    config = json.loads((self.root / "kokoro-config.json").read_text())
                    if not isinstance(config.get("vocab"), dict):
                        raise ValueError("Поле vocab отсутствует")
                except (OSError, ValueError, TypeError) as exc:
                    raise RuntimeError("Неправильный kokoro-config.json: " + str(exc)) from exc
                # RUAccent may leave a half-downloaded turbo3.1 directory:
                # its built-in downloader then skips model.onnx forever.
                self._update(percent=94, message="Восстановление моделей RUAccent",
                             filename="", downloaded_bytes=0, total_bytes=0, step="repair")
                progress_file = self.root / ".ruaccent-repair-progress.json"
                if progress_file.exists():
                    progress_file.unlink()
                helper = Path(__file__).resolve().parent / "ruaccent_repair.py"
                self._run([str(py), str(helper), str(progress_file)], timeout=1800,
                          progress_file=progress_file)
                if not ruaccent_ready(self.root):
                    raise RuntimeError("RUAccent не готов после загрузки; проверь install.log")
            self._check()
            self._update(percent=98, message="Загрузка модели в память",
                         filename="", downloaded_bytes=0, total_bytes=0, step="load")
            self._last_failure = ""
            self._last_exit = None
            if not self.await_ready(timeout=120):
                raise RuntimeError(self._last_failure or "Модель не смогла запуститься")
            self._update(percent=100, message="Модель готова к синтезу", step="done")
        except Cancelled:
            self._update(message="Установка отменена; можно продолжить позже", percent=None)
        except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError,
                urllib.error.URLError) as exc:
            self._update(error=str(exc)[:280], message="Ошибка установки")
        finally:
            self._update(running=False)

    def warmup(self, voice):
        """Preload the selected Piper speaker; synthesis itself stays sequential."""
        if voice not in VOICE_NAMES[self.kind]:
            raise ValueError("Неизвестный голос")
        if self.kind != "piper" or not self._health():
            return {"ready": self._health()}
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/warmup",
            data=json.dumps({"voice": voice}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read(4096))

    def synthesize(self, data):
        voice, text = data.get("voice"), data.get("text")
        speed = data.get("speed", 1.0)
        if voice not in VOICE_NAMES[self.kind]:
            raise ValueError("Некорректный голос")
        if not isinstance(text, str) or not (1 <= len(text.strip()) <= 450):
            raise ValueError("Текст должен содержать 1–450 символов")
        if type(speed) not in (float, int) or not .65 <= speed <= 1.7:
            raise ValueError("Скорость должна быть в пределах 0.65–1.7")
        if not self._health():
            if not self.await_ready(timeout=90):
                raise RuntimeError(self._last_failure or "Модель не запустилась; проверь worker.log.")
        payload = json.dumps({"text": text, "voice": voice, "speed": speed}, ensure_ascii=False).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/speak",
                                         data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=35 if self.kind == "piper" else 90) as response:
            audio = response.read(12_000_000)
        if not valid_wav(audio):
            raise RuntimeError(self.kind + ": получен пустой или неслышный WAV")
        return audio

    def stop(self):
        with self._lock:
            if self._process is not None:
                if self._process.poll() is None:
                    self._process.terminate()
                try:
                    self._process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
            # Keep ownership if waiting fails; never overlap a replacement worker.
            self._process = None
            self._started_at = 0
            self._health_result = False
            self._health_at = 0


class Qwen3Addon(Addon):
    """Qwen3-TTS MLX engine: user-provided model folders + pip-installed MLX."""

    def __init__(self):
        super().__init__("qwen3-tts")

    @property
    def installed(self):
        if not (self.root / "venv" / "bin" / "python").is_file():
            return False
        models = self.root / "models"
        folders = [f for group in QWEN3_MODEL_FOLDERS.values() for f in group.values()]
        return any((models / f).is_dir() for f in folders)

    def expected_files(self):
        return tuple(f for group in QWEN3_MODEL_FOLDERS.values() for f in group.values())

    def _worker_module(self):
        return "backend.audio.qwen3"

    def _worker_command(self):
        return [str(self.root / "venv/bin/python"), "-m", "backend.audio.qwen3",
                "--worker", str(self.root), str(self.port), str(QWEN3_VOICES_DIR)]

    def _install(self):
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / ".voice-engine").write_text(self.kind)
            (self.root / "models").mkdir(parents=True, exist_ok=True)
            self._save_root()
            py = self._venv()
            self._check()
            self._update(percent=10, message="Установка MLX и Qwen3-TTS", step="deps")
            packages = (
                "mlx", "mlx-metal", "transformers", "numpy",
                "mlx-audio @ git+https://github.com/Blaizzy/mlx-audio.git@9349644ccbd62eb10900852228f7b952c566def3",
            )
            self._run([str(py), "-m", "pip", "install", "--disable-pip-version-check", *packages], 1800)
            self._check()
            size = self._install_size or "lite"
            self._update(percent=20, message="Скачивание моделей Qwen3 (" + size + ")", step="models")
            progress_file = self.root / ".qwen3-download-progress.json"
            if progress_file.exists():
                progress_file.unlink()
            self._run([str(py), "-m", "backend.audio.qwen3", "--download", size,
                       str(self.root / "models"), str(progress_file)],
                      timeout=7200, progress_file=progress_file, cwd=PROJECT_ROOT)
            self._check()
            if not self.installed:
                raise RuntimeError("Модели Qwen3 не загрузились; проверь install.log")
            self._update(percent=98, message="Проверка Qwen3", step="load")
            self._last_failure = ""
            self._last_exit = None
            if not self.await_ready(timeout=300):
                raise RuntimeError(self._last_failure or "Qwen3 не ответил; проверь worker.log")
            self._update(percent=100, message="Qwen3 готов к синтезу", step="done")
        except Cancelled:
            self._update(message="Установка отменена; можно продолжить позже", percent=None)
        except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError,
                urllib.error.URLError) as exc:
            self._update(error=str(exc)[:280], message="Ошибка установки")
        finally:
            self._update(running=False)

    def warmup(self, voice):
        return {"ready": self._health()}

    def synthesize(self, data):
        text = data.get("text")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 600:
            raise ValueError("Текст должен содержать 1–600 символов")
        voice = data.get("voice")
        if not isinstance(voice, str) or not voice.strip():
            raise ValueError("Выбери голос")
        size = data.get("size", "lite")
        if size not in QWEN3_MODEL_FOLDERS:
            raise ValueError("Неизвестный размер модели")
        speed = data.get("speed", 1.0)
        if type(speed) not in (float, int) or not 0.5 <= speed <= 2.0:
            raise ValueError("Скорость должна быть в пределах 0.5–2.0")
        if not self._health():
            if not self.await_ready(timeout=300):
                raise RuntimeError(self._last_failure or "Qwen3 не запустился; проверь worker.log")
        payload = json.dumps({"text": text.strip(), "voice": voice.strip(),
                              "size": size, "speed": float(speed)}, ensure_ascii=False).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/speak",
                                         data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                audio = response.read(24_000_000)
        except urllib.error.HTTPError as exc:
            # Preserve the worker's actual error instead of collapsing every
            # failure into a generic "empty WAV". 4xx is permanent config/input
            # error; 5xx is a transient synthesis failure worth retrying.
            detail = ""
            try:
                detail = json.loads(exc.read().decode("utf-8", "replace")).get("error", "")
            except (OSError, ValueError, AttributeError):
                pass
            message = "Qwen3: " + (detail or str(exc))
            if exc.code and 400 <= exc.code < 500:
                raise ValueError(message)
            raise RuntimeError(message)
        if not valid_wav(audio):
            raise RuntimeError("Qwen3: получен пустой или неслышный WAV")
        return audio


class OpenAudioAddon(Addon):
    """Isolated, pinned Fish Speech runtime and verified S1-mini weights."""

    startup_timeout = 600

    def __init__(self):
        super().__init__("openaudio-s1-mini")

    def _python(self):
        # NumPy 1.26 wheels used by this Fish Speech revision stop at Python 3.12.
        for name in ("python3.12", "python3.11", "python3.10"):
            if candidate := shutil.which(name):
                return candidate
        return sys.executable if (3, 10) <= sys.version_info[:2] <= (3, 12) else None

    def install(self, directory=None, size=None):
        with self._lock:
            if not self.progress["running"]:
                self.stop()
            return super().install(directory, size)

    def expected_files(self):
        return tuple("models/" + name for name in MODEL_FILES)

    @property
    def installed(self):
        if not (self.root / "venv/bin/python").is_file():
            return False
        try:
            manifest = json.loads((self.root / "models/installed.json").read_text())
            return (manifest["source_revision"] == FISH_REVISION
                    and all((self.root / "models" / name).stat().st_size == manifest["files"][name]["size"]
                            and manifest["files"][name]["size"] > 0 for name in MODEL_FILES)
                    and (self.root / "fish-speech/fish_speech").is_dir())
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _worker_command(self):
        return [str(self.root / "venv/bin/python"), "-m", "backend.audio.openaudio",
                "--worker", str(self.root), str(self.port)]

    def status(self):
        from .openaudio import reference_status
        result = super().status()
        result["references"] = reference_status(self.root)
        return result

    def _install(self):
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / ".voice-engine").write_text(self.kind)
            self._save_root()
            py = self._venv()
            source = self.root / "fish-speech"
            self._update(percent=8, message="Подготовка Fish Speech", step="deps")
            if not source.exists():
                self._run(["git", "clone", "--filter=blob:none", "--no-checkout",
                           "https://github.com/fishaudio/fish-speech.git", str(source)], 900)
            self._run(["git", "-C", str(source), "fetch", "--depth=1", "origin", FISH_REVISION], 900)
            self._run(["git", "-C", str(source), "checkout", "--detach", FISH_REVISION], 180)
            # Only inference dependencies: no microphone, browser UI, or training dataset install.
            self._update(percent=12, message="Установка PyTorch и зависимостей S1-mini", step="deps")
            torch_args = [str(py), "-m", "pip", "install", "--disable-pip-version-check",
                          "torch==2.8.0", "torchaudio==2.8.0"]
            if platform.system() == "Linux" and not shutil.which("nvidia-smi"):
                torch_args += ["--index-url", "https://download.pytorch.org/whl/cpu"]
            self._run(torch_args, 2400)
            self._run([str(py), "-m", "pip", "install", "--disable-pip-version-check",
                       "numpy==1.26.4", "transformers==4.51.3", "huggingface_hub==0.36.2",
                       "hydra-core==1.3.2", "pydantic==2.9.2", "einx[torch]==0.2.2",
                       "librosa==0.10.2.post1", "lightning==2.5.1", "pyrootutils==1.0.4",
                       "loralib==0.1.2", "natsort==8.4.0", "tiktoken==0.9.0",
                       "loguru", "soundfile", "rich", "cachetools", "ormsgpack", "click",
                       "descript-audio-codec", "descript-audiotools"], 2400)
            self._check()
            self._run([str(py), "-m", "backend.audio.openaudio", "--check-runtime", str(self.root)],
                      timeout=120, cwd=PROJECT_ROOT)
            self._update(percent=None, message="Подключение к Hugging Face; получение списка файлов", step="models")
            progress_file = self.root / ".openaudio-download-progress.json"
            progress_file.unlink(missing_ok=True)
            self._run([str(py), "-m", "backend.audio.openaudio", "--download", str(self.root), str(progress_file)],
                      timeout=7200, cwd=PROJECT_ROOT, progress_file=progress_file)
            if not self.installed:
                raise RuntimeError("S1-mini загружена не полностью; проверь install.log")
            self._update(percent=95, message="Загрузка S1-mini и пробный синтез; CPU может работать медленно", step="load",
                         filename="", total_bytes=0, speed_bytes=0, eta_seconds=0, idle_seconds=0)
            self._last_failure = ""
            self._last_exit = None
            if not self.await_ready(timeout=self.startup_timeout):
                raise RuntimeError(self._last_failure or "S1-mini не ответила; проверь worker.log")
            self._update(percent=100, message="OpenAudio S1-mini готова", step="done")
        except Cancelled:
            self.stop()
            self._update(message="Установка отменена; можно продолжить позже", percent=None)
        except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
            self._update(error=str(exc)[:350], message="Ошибка установки")
        finally:
            self._update(running=False)

    def synthesize(self, data):
        from .openaudio import validate_request
        text, voice, speed = validate_request(data)
        if voice != "default" and voice not in self.status()["references"]:
            raise ValueError("Сначала загрузи WAV и расшифровку для выбранного голоса")
        if not self.await_ready(timeout=self.startup_timeout):
            raise RuntimeError(self._last_failure or "S1-mini не запустилась; проверь worker.log")
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/speak",
                    data=json.dumps({"text": text, "voice": voice, "speed": speed}).encode(),
                    headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                audio = response.read(24_000_001)
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise ValueError("OpenAudio: некорректный запрос или референс голоса") from None
            raise RuntimeError("OpenAudio: ошибка синтеза; проверь worker.log") from None
        if len(audio) > 24_000_000 or not valid_wav(audio):
            raise RuntimeError("OpenAudio вернула пустой или неслышимый WAV")
        return audio


ADDONS = {kind: (Qwen3Addon() if kind == "qwen3-tts" else
                 OpenAudioAddon() if kind == "openaudio-s1-mini" else Addon(kind)) for kind in VOICE_NAMES}


def worker_main(kind, root, port):
    import numpy as np
    if kind == "piper":
        from piper import PiperVoice, SynthesisConfig
        loaded = {}
        voice_lock = threading.RLock()
        def preload(voice):
            if voice not in VOICE_NAMES[kind]:
                raise ValueError("Unknown Piper voice")
            if voice in loaded:
                return loaded[voice]
            with voice_lock:
                if voice not in loaded:
                    prefix = root / ("ru_RU-" + voice + "-medium.onnx")
                    loaded[voice] = PiperVoice.load(str(prefix),
                        config_path=str(prefix) + ".json")
            return loaded[voice]
        # Prepare the first persona's default voice before reporting /health.
        first = preload("dmitri")
        # /health becomes ready only after a *non-silent* actual WAV.
        test_audio = io.BytesIO()
        with wave.open(test_audio, "wb") as probe:
            first.synthesize_wav("Привет.", probe)
        if not valid_wav(test_audio.getvalue()):
            raise RuntimeError("Piper started but its sample WAV is silent or invalid")
        def infer(p):
            voice = p["voice"]
            model = preload(voice)
            output = io.BytesIO()
            config = SynthesisConfig(length_scale=1 / float(p["speed"]))
            with wave.open(output, "wb") as wav:
                model.synthesize_wav(p["text"], wav, syn_config=config)
            audio = output.getvalue()
            if not valid_wav(audio):
                raise RuntimeError("Piper generated an empty or silent WAV")
            return audio
    elif kind == "silero":
        def preload(voice):
            if voice not in VOICE_NAMES[kind]:
                raise ValueError("Unknown Silero voice")
            return None
        import torch
        torch.set_num_threads(3)
        model = torch.package.PackageImporter(str(root / "v5_ru.pt")).load_pickle("tts_models", "model")
        model.to(torch.device("cpu"))
        with torch.inference_mode():
            sound = model.apply_tts(text="Привет.", speaker="aidar", sample_rate=24000)
        import numpy as np
        samples = sound.detach().cpu().numpy() if hasattr(sound, "detach") else np.asarray(sound)
        if samples.size < 1600 or not np.any(np.abs(samples[::17]) > .0006):
            raise RuntimeError("Silero started but returned an empty or silent audio sample")
        def infer(p):
            audio = model.apply_tts(text=p["text"], speaker=p["voice"], sample_rate=24000)
            samples = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
                wav.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
            return output.getvalue()
    else:
        raise ValueError("Unknown engine")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def respond(self, code, body, mime):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            if self.path == "/health":
                self.respond(200, b'{"status":"ok"}', "application/json")
            else:
                self.send_error(404)
        def do_POST(self):
            if self.path not in ("/speak", "/warmup"):
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    raise ValueError("Bad request size")
                p = json.loads(self.rfile.read(size))
                if p.get("voice") not in VOICE_NAMES[kind]:
                    raise ValueError("Invalid voice")
                if self.path == "/warmup":
                    preload(p["voice"])
                    return self.respond(200, b'{"ready":true}', "application/json")
                if not isinstance(p.get("text"), str) or not 0 < len(p["text"]) <= 450:
                    raise ValueError("Invalid text")
                if type(p.get("speed")) not in (float, int) or not .65 <= p["speed"] <= 1.7:
                    raise ValueError("Invalid speed")
                self.respond(200, infer(p), "audio/wav")
            except (ValueError, TypeError, KeyError) as err:
                self.respond(400, json.dumps({"error": str(err)}).encode(), "application/json")
            except Exception:
                import traceback
                traceback.print_exc()
                self.respond(503, b'{"error":"Voice inference failed, see worker.log"}', "application/json")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__" and len(sys.argv) == 5 and sys.argv[1] == "--worker":
    worker_main(sys.argv[2], Path(sys.argv[3]), int(sys.argv[4]))
