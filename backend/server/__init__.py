"""Сервер TRIAD: конфигурация, авторизация, LLM-клиенты.

Обработчики HTTP и точка входа живут в :mod:`backend.server.http_server`; они
подключаются лениво, чтобы не создавать циклических импортов с
:mod:`backend.controls`.
"""
from .config import HOST, DEFAULT_PORT, PORT
from .llm import BridgeError, json_request, sse_events, verify_jwt
from .auth import State, LiveCall

__all__ = ["HOST", "DEFAULT_PORT", "PORT", "BridgeError", "json_request",
           "sse_events", "verify_jwt", "State", "LiveCall"]
