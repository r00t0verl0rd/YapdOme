#!/bin/bash
# TRIAD v0.2.0 — локальный сервер и опциональные голосовые движки.
set -u

# Resolve the project root. Finder, Terminal and nested ZIP extraction can
# produce different working directories, so do not rely on the caller's cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1
ROOT=""
for candidate in "$SCRIPT_DIR" "$SCRIPT_DIR/YapdOme" "$SCRIPT_DIR/YapdOme-main"; do
  if [ -f "$candidate/backend/__init__.py" ] && [ -f "$candidate/backend/server/config.py" ]; then
    ROOT="$candidate"
    break
  fi
done
if [ -z "$ROOT" ]; then
  echo "Не найдена папка backend рядом с START.command."
  echo "Путь запуска: $SCRIPT_DIR"
  echo "Распакуй весь архив проекта и запускай START.command из корневой папки YapdOme."
  read -r -p 'Нажми Enter для закрытия…' _
  exit 1
fi
cd "$ROOT" || exit 1
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

LOGDIR="$HOME/Library/Logs/YapdOme"
if ! mkdir -p "$LOGDIR"; then
  echo 'Не удалось создать каталог журнала. Проверь права доступа к домашней папке.'
  read -r -p 'Нажми Enter для закрытия…' _; exit 1
fi
LOG="$LOGDIR/triad-launch.log"
# Журнал ограниченного размера, чтобы не расти без границ.
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG" 2>/dev/null || wc -c < "$LOG")" -gt 2000000 ]; then
  mv -f "$LOG" "$LOG.old" 2>/dev/null || true
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Не найден Python 3. Установи Python 3 и проверь команду python3.'
  read -r -p 'Нажми Enter для закрытия…' _; exit 1
fi
# Verify both the package path and import using the exact interpreter used below.
if ! PORT="$(PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 -c 'from backend.server import PORT; print(PORT)')"; then
  echo "Не удалось импортировать backend из: $ROOT"
  echo "Проверь, что backend/__init__.py и backend/server/config.py существуют."
  read -r -p 'Нажми Enter для закрытия…' _; exit 1
fi
# Ждём готовности сервера перед открытием браузера.
(
  for attempt in {1..40}; do
    if curl --silent --fail --max-time 1 "http://127.0.0.1:${PORT}/api/version" | grep -q '"version": "0.2.0"'; then
      open "http://127.0.0.1:${PORT}/"
      break
    fi
    sleep 0.5
  done
) &
echo 'TRIAD v0.2.0 — локальный сервер + опциональные голосовые движки'
echo "Корень проекта: $ROOT"
echo "http://127.0.0.1:${PORT}"
echo "Журнал ошибок: $LOG"
echo 'Для остановки: Ctrl+C'
set -o pipefail
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 -u -m backend.server 2>&1 | tee -a "$LOG"
code=$?
echo "Сервер завершился с кодом $code. Журнал: $LOG"
read -r -p 'Нажми Enter для закрытия…' _
exit "$code"
