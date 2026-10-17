#!/bin/bash
# TRIAD v0.2.0 — локальный сервер и опциональные голосовые движки.
set -u
cd "$(dirname "$0")" || exit 1
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
# Порт настроен только в backend/server/config.py; импорт не запускает сервер.
if ! PORT="$(python3 -c 'from backend.server import PORT; print(PORT)')"; then
  echo 'Не удалось прочитать порт из backend/server/config.py.'
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
echo "http://127.0.0.1:${PORT}"
echo "Журнал ошибок: $LOG"
echo 'Для остановки: Ctrl+C'
set -o pipefail
python3 -u -m backend.server 2>&1 | tee -a "$LOG"
code=$?
echo "Сервер завершился с кодом $code. Журнал: $LOG"
read -r -p 'Нажми Enter для закрытия…' _
exit "$code"
