"""Repair RUAccent's partial Hugging Face downloads inside Kokoro RU's venv.

RUAccent skips downloads when a directory exists even if model.onnx is absent.
Download only the model files it actually uses, not unrelated omograph variants.
This script runs with the *isolated* Kokoro Python and never alters system Python.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

REPO = "ruaccent/accentuator"
FOLDERS = (
    "nn/nn_omograph/turbo3.1",
    "nn/nn_accent",
    "nn/nn_stress_usage_predictor",
    "nn/nn_yo_homograph_resolver",
    "dictionary",
    "koziev",
)
ESSENTIAL = (
    "nn/nn_omograph/turbo3.1/model.onnx",
    "nn/nn_accent/model.onnx",
    "nn/nn_stress_usage_predictor/model.onnx",
    "nn/nn_yo_homograph_resolver/model.onnx",
    "dictionary/omographs.json.gz",
    "dictionary/yo_words.json.gz",
    "dictionary/yo_homographs.json.gz",
    "dictionary/accents.json.gz",
)


def module_directory():
    spec = importlib.util.find_spec("ruaccent")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("RUAccent не установлен в окружении Kokoro RU")
    root = Path(list(spec.submodule_search_locations)[0]).resolve()
    if not root.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("RUAccent должен находиться внутри изолированного окружения")
    return root


def check_essential(directory):
    result = []
    for name in ESSENTIAL:
        target = directory / name
        # An LFS pointer / interrupted download is never a valid ONNX model.
        minimum = 100_000 if name.endswith(".onnx") else 100
        if not target.is_file() or target.stat().st_size < minimum:
            result.append(name)
    return result


def publish(progress_path, message, done=0, total=0, filename="", size=0):
    value = {"message": message, "done": done, "total": total,
             "filename": filename, "size": size}
    tmp = progress_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, progress_path)
    print(message, filename, flush=True)


def repair(progress_path):
    from huggingface_hub import HfApi, hf_hub_download
    from huggingface_hub.hf_api import RepoFile

    root = module_directory()
    api = HfApi()
    publish(progress_path, "Проверяем RUAccent: состав файлов")
    assets = {}
    for folder in FOLDERS:
        for item in api.list_repo_tree(REPO, path_in_repo=folder, recursive=True):
            if not isinstance(item, RepoFile):
                continue
            path = item.path
            # Never download files from outside the explicit allowlist.
            if path.startswith(folder + "/") and ".." not in Path(path).parts:
                assets[path] = item.size

    if not set(ESSENTIAL).issubset(assets):
        missing = sorted(set(ESSENTIAL) - set(assets))
        raise RuntimeError("Отсутствуют файлы в официальном RUAccent: " + ", ".join(missing))

    pending = []
    for name, size in sorted(assets.items()):
        target = root / name
        # Empty metadata placeholders are permitted only if the upstream
        # repository itself advertises size=0.
        minimum = 100_000 if name.endswith(".onnx") else (0 if size == 0 else 1)
        if not target.is_file() or target.stat().st_size < minimum or (
            size is not None and target.stat().st_size != size
        ):
            pending.append((name, size))

    if not pending:
        publish(progress_path, "RUAccent: все ресурсы на месте", 1, 1)
        return

    publish(progress_path, "RUAccent: скачиваем недостающие данные", 0, len(pending))
    for index, (name, size) in enumerate(pending):
        publish(progress_path, f"RUAccent: файл {index+1} из {len(pending)}",
                index, len(pending), name, size or 0)
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        result = Path(hf_hub_download(repo_id=REPO, filename=name,
                    local_dir=str(root), force_download=target.exists()))
        if not result.is_file() or result.stat().st_size < (
            100_000 if name.endswith(".onnx") else (0 if size == 0 else 1)
        ):
            raise RuntimeError("Неполная загрузка RUAccent: " + name)
        if size is not None and result.stat().st_size != size:
            raise RuntimeError("Неверный размер RUAccent: " + name)
    missing = check_essential(root)
    if missing:
        raise RuntimeError("RUAccent не готов; отсутствует " + ", ".join(missing))
    publish(progress_path, "RUAccent: зависимости восстановлены",
            len(pending), len(pending))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m yapdome.audio.ruaccent_repair <progress-json-path>")
    repair(Path(sys.argv[1]).resolve())
