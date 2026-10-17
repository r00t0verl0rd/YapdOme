"""Qwen3-TTS MLX sidecar (Apple Silicon) and shared custom-voice store.

The custom-voice folder is shared between the Pro (1.7B) and Lite (0.6B)
models: both sizes read and write the same directory under YapdOme app data.

The heavy ``mlx_audio`` import happens only inside :func:`worker`, so this
module can be imported by the bridge without installing MLX.
"""
import base64
import json
import platform
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_APP = (Path.home() / "Library" / "Application Support" / "YapdOme"
        if platform.system() == "Darwin"
        else Path.home() / ".local" / "share" / "YapdOme")

# Shared by Pro (1.7B) and Lite (0.6B): one folder, no per-size duplication.
QWEN3_VOICES_DIR = _APP / "qwen3-voices"

QWEN3_BUILTIN = (
    "Ryan", "Aiden", "Ethan", "Chelsie", "Serena", "Vivian",
    "Uncle_Fu", "Dylan", "Eric", "Ono_Anna", "Sohee",
)

# External repo model-folder layout. Each value is the HuggingFace snapshot
# folder the user must place inside <root>/models/.
QWEN3_MODEL_FOLDERS = {
    "pro": {
        "preset": "Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
        "design": "Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit",
        "clone": "Qwen3-TTS-12Hz-1.7B-Base-8bit",
    },
    "lite": {
        # The community never published a 0.6B VoiceDesign model, so Lite
        # only ships presets (CustomVoice) and cloning (Base).
        "preset": "Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
        "clone": "Qwen3-TTS-12Hz-0.6B-Base-8bit",
    },
}

QWEN3_MODES = ("preset", "design", "clone")

QWEN3_REPOS = {
    "pro": {
        "preset": "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit",
        "design": "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit",
        "clone": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
    },
    "lite": {
        "preset": "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
        "clone": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
    },
}


def slugify(name):
    value = re.sub(r"[^\w\-]+", "-", str(name).strip(), flags=re.UNICODE).strip("-")
    return value[:64] if value else None


class Qwen3Voices:
    """Filesystem store for reusable Qwen3 custom voices.

    Each voice is one JSON file; cloned voices additionally keep a reference
    WAV under ``refs/<id>.wav``. The store is intentionally stdlib-only so it
    can be unit-tested without MLX and shared between Pro and Lite.
    """

    def __init__(self, root):
        self.root = Path(root)

    def _refs_dir(self):
        return self.root / "refs"

    def _path(self, voice_id):
        return self.root / (voice_id + ".json")

    def ref_path(self, voice_id):
        return self._refs_dir() / (voice_id + ".wav")

    def list(self):
        if not self.root.is_dir():
            return []
        voices = []
        for path in self.root.glob("*.json"):
            try:
                item = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(item, dict) and item.get("id") == path.stem:
                voices.append(item)
        voices.sort(key=lambda v: (v.get("name") or "").casefold())
        return voices

    def get(self, voice_id):
        path = self._path(voice_id)
        if not path.is_file():
            return None
        try:
            item = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        return item if isinstance(item, dict) and item.get("id") == voice_id else None

    def create(self, spec):
        name = str(spec.get("name") or "").strip()
        if not 1 <= len(name) <= 64:
            raise ValueError("Имя голоса должно содержать 1–64 символа")
        voice_id = slugify(name)
        if not voice_id:
            raise ValueError("Некорректное имя голоса")
        mode = spec.get("mode")
        if mode not in QWEN3_MODES:
            raise ValueError("Неизвестный тип голоса")
        item = {"id": voice_id, "name": name[:64], "mode": mode}
        if mode == "preset":
            speaker = str(spec.get("speaker") or "").strip()
            if speaker not in QWEN3_BUILTIN:
                raise ValueError("Неизвестный встроенный голос")
            instruct = str(spec.get("instruct") or "Normal tone").strip()[:200]
            speed = spec.get("speed", 1.0)
            if type(speed) not in (int, float) or not 0.5 <= speed <= 2.0:
                raise ValueError("Некорректная скорость")
            item.update(speaker=speaker, instruct=instruct, speed=float(speed))
        elif mode == "design":
            instruct = str(spec.get("instruct") or "").strip()
            if not 1 <= len(instruct) <= 300:
                raise ValueError("Описание голоса должно содержать 1–300 символов")
            item["instruct"] = instruct
        else:  # clone
            ref_text = str(spec.get("ref_text") or "").strip()[:600]
            audio_b64 = spec.get("ref_audio_b64")
            existing = self.get(voice_id)
            if isinstance(audio_b64, str) and audio_b64:
                self.root.mkdir(parents=True, exist_ok=True)
                self._refs_dir().mkdir(parents=True, exist_ok=True)
                self.ref_path(voice_id).write_bytes(self._decode_audio(audio_b64))
            elif not (existing and self.ref_path(voice_id).is_file()):
                raise ValueError("Для клонирования нужен референсный аудиофайл")
            item["ref_text"] = ref_text
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(voice_id).write_text(json.dumps(item, ensure_ascii=False, indent=2), "utf-8")
        return item

    def delete(self, voice_id):
        removed = False
        if self._path(voice_id).is_file():
            self._path(voice_id).unlink()
            removed = True
        if self.ref_path(voice_id).is_file():
            self.ref_path(voice_id).unlink()
            removed = True
        return removed

    @staticmethod
    def _decode_audio(value):
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("Некорректный аудиофайл") from exc
        if not 200 <= len(raw) <= 12_000_000:
            raise ValueError("Аудиофайл должен быть 200 байт – 12 МиБ")
        return raw


def download_models(size, models_dir, progress_file):
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

    repos = QWEN3_REPOS.get(size)
    if not repos:
        raise RuntimeError("Неизвестный размер модели Qwen3")
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    progress_file = Path(progress_file)
    items = list(repos.items())
    total = len(items)

    def publish(message, percent, filename=""):
        tmp = progress_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"message": message, "percent": percent,
                                   "filename": filename, "step": "models"}, ensure_ascii=False))
        tmp.replace(progress_file)

    for i, (mode, repo_id) in enumerate(items):
        folder = QWEN3_MODEL_FOLDERS[size][mode]
        publish(f"Скачивание {folder} ({i + 1}/{total})", 20 + round(70 * i / total), folder)
        try:
            snapshot_download(repo_id=repo_id, local_dir=str(models_dir / folder),
                              local_dir_use_symlinks=False, token=False)
        except RepositoryNotFoundError as exc:
            raise RuntimeError(
                f"Репозиторий {repo_id} не найден или приватный. "
                "Проверь название: вероятно, для этого размера модель не опубликована. "
                f"Детали: {exc}"
            ) from exc
        except GatedRepoError as exc:
            raise RuntimeError(
                f"Репозиторий {repo_id} закрыт (gated). Выполни 'huggingface-cli login' "
                "с токеном, у которого есть доступ, и повтори установку. "
                f"Детали: {exc}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Не удалось анонимно скачать {repo_id}. "
                "Проверь доступ к интернету и что репозиторий публичный. "
                f"Детали: {exc}"
            ) from exc
    publish("Модели Qwen3 загружены", 90)


def preset_speakers(models_dir, size):
    """Встроенные голоса пресет-модели из config.json, без загрузки модели.

    Возвращает список имён в стиле QWEN3_BUILTIN или None, если прочитать
    конфиг не удалось. Список различается у разных размеров модели.
    """
    folder = QWEN3_MODEL_FOLDERS.get(size, {}).get("preset")
    if not folder:
        return None
    full = Path(models_dir) / folder
    if not full.is_dir():
        return None
    snapshots = full / "snapshots"
    if snapshots.is_dir():
        subfolders = [p for p in snapshots.iterdir() if not p.name.startswith(".")]
        if subfolders:
            full = subfolders[0]
    try:
        config = json.loads((full / "config.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    speakers = config.get("talker_config", {}).get("spk_id")
    if not isinstance(speakers, dict) or not speakers:
        return None
    return [str(name).strip().title() for name in speakers if str(name).strip()]


def worker(root, port, voices_dir):
    from mlx_audio.tts.utils import load_model
    from mlx_audio.tts.generate import generate_audio
    import mlx.core as mx

    root = Path(root)
    voices = Qwen3Voices(voices_dir)
    models_dir = root / "models"
    loaded = {}
    model_lock = threading.RLock()
    synthesis_lock = threading.Lock()

    def smart_path(folder):
        full = models_dir / folder
        if not full.is_dir():
            return None
        snapshots = full / "snapshots"
        if snapshots.is_dir():
            subfolders = [p for p in snapshots.iterdir() if not p.name.startswith(".")]
            if subfolders:
                return subfolders[0]
        return full

    def model_for(size, mode):
        if size not in QWEN3_MODEL_FOLDERS or mode not in QWEN3_MODEL_FOLDERS[size]:
            raise ValueError("Неизвестная модель Qwen3")
        key = (size, mode)
        if key in loaded:
            return loaded[key]
        with model_lock:
            if key not in loaded:
                folder = QWEN3_MODEL_FOLDERS[size][mode]
                path = smart_path(folder)
                if path is None:
                    raise RuntimeError("Модель Qwen3 не найдена: " + folder)
                loaded[key] = load_model(path)
        return loaded[key]

    def resolve(voice_id):
        if voice_id in QWEN3_BUILTIN:
            return {"mode": "preset", "speaker": voice_id,
                    "instruct": "Normal tone", "speed": 1.0}
        item = voices.get(voice_id)
        if item is None:
            raise ValueError("Неизвестный голос")
        return item

    def synthesize(payload):
        text = str(payload.get("text") or "")
        if not 1 <= len(text) <= 600:
            raise ValueError("Текст должен содержать 1–600 символов")
        size = payload.get("size", "lite")
        if size not in QWEN3_MODEL_FOLDERS:
            raise ValueError("Неизвестный размер модели")
        spec = resolve(payload.get("voice"))
        mode = spec["mode"]
        if mode not in QWEN3_MODEL_FOLDERS[size]:
            raise ValueError(
                "Дизайн голоса доступен только для Pro (1.7B): у Lite (0.6B) нет "
                "модели VoiceDesign. Переключи размер или выбери пресет/клонирование."
            )
        model = model_for(size, mode)
        with tempfile.TemporaryDirectory(dir=str(root)) as tmp:
            kwargs = {"model": model, "text": text, "output_path": tmp,
                      "max_tokens": 1200, "verbose": False}
            if mode == "preset":
                speaker = spec["speaker"]
                # Реальный список спикеров живёт в модели: у Lite и Pro он
                # разный, а захардкоженный QWEN3_BUILTIN — только фолбэк.
                supported = getattr(model, "supported_speakers", None) or []
                if supported and speaker.lower() not in (s.lower() for s in supported):
                    raise ValueError(
                        "Голос '" + speaker + "' не поддерживается этой моделью. "
                        "Доступные: " + ", ".join(supported))
                kwargs["voice"] = speaker
                kwargs["instruct"] = spec.get("instruct", "Normal tone")
                speed = payload.get("speed", spec.get("speed", 1.0))
                if type(speed) not in (int, float) or not 0.5 <= speed <= 2.0:
                    raise ValueError("Некорректная скорость")
                kwargs["speed"] = float(speed)
            elif mode == "design":
                kwargs["instruct"] = spec["instruct"]
            else:  # clone
                ref = voices.ref_path(spec["id"])
                if not ref.is_file():
                    raise RuntimeError("Отсутствует референсный аудиофайл голоса")
                kwargs["ref_audio"] = str(ref)
                kwargs["ref_text"] = spec.get("ref_text", "") or "."
            with synthesis_lock:
                generate_audio(**kwargs)
                output = Path(tmp) / "audio_000.wav"
                if not output.is_file():
                    raise RuntimeError("Qwen3 не создал аудиофайл")
                audio = output.read_bytes()
            # The shared MLX model is not thread-safe and Metal memory grows
            # across turns; serialize generation and free the cache each time.
            try:
                try:
                    mx.metal.clear_cache()
                except Exception:
                    pass
                mx.clear_cache()
            except Exception:
                pass
            return audio

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, payload, mime):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, b'{"status":"ok"}', "application/json")
            elif self.path == "/voices":
                builtin = {}
                for size in QWEN3_MODEL_FOLDERS:
                    builtin[size] = preset_speakers(models_dir, size) or list(QWEN3_BUILTIN)
                body = json.dumps({"builtin": builtin,
                                   "custom": voices.list()}, ensure_ascii=False).encode()
                self.reply(200, body, "application/json")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/speak":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16_384:
                    raise ValueError("Некорректный размер запроса")
                payload = json.loads(self.rfile.read(size))
                self.reply(200, synthesize(payload), "audio/wav")
            except (ValueError, TypeError, KeyError) as exc:
                self.reply(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            except Exception:
                import traceback
                traceback.print_exc()
                self.reply(503, b'{"error":"Qwen3 synthesis error; see worker.log"}', "application/json")

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
    elif len(sys.argv) == 5 and sys.argv[1] == "--download":
        download_models(sys.argv[2], sys.argv[3], sys.argv[4])
