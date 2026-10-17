"""Конфигурация локального сервера: адрес и порт.

Порт меняется в одном месте — здесь. Лаунчер и тесты читают его отсюда.
"""

import os

HOST = "127.0.0.1"
DEFAULT_PORT = 13180
PORT = int(os.environ.get("TRIAD_PORT", DEFAULT_PORT))
if not 1 <= PORT <= 65535:
    raise ValueError("Порт должен быть числом от 1 до 65535")
