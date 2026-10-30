"""Публичный фасад движка: валидация входных данных, строковые ярлыки, потоки.

Машина состояний живёт в :class:`backend.engine.state.StateMachine`; здесь —
проверки аргументов и преобразование снимка в JSON-совместимый вид.
"""

import threading

from . import enums as E
from .state import StateMachine


class Snapshot:
    """Плоский снимок состояния эфира (только поля)."""

    fields = ("status", "agent", "next_agent", "turns", "max_turns", "revision",
              "ticket", "passes", "kind", "result", "errors", "timeout_ms")

    def __init__(self, **values):
        for field in self.fields:
            setattr(self, field, values.get(field, 0))


class AuditEntry:
    """Запись журнала аудита (только поля)."""

    fields = ("sequence", "monotonic_ms", "action", "actor", "result",
              "status_before", "status_after", "speaker_before", "speaker_after",
              "next_agent", "ticket", "revision")

    def __init__(self, **values):
        for field in self.fields:
            setattr(self, field, values.get(field, 0))


def as_json(snapshot, route_reason=-1):
    """Переводит числовой снимок в словарь с человекочитаемыми ярлыками."""
    return {
        "status": E.MODES[snapshot["status"]],
        "agent": snapshot["agent"],
        "next_agent": snapshot["next_agent"],
        "turns": snapshot["turns"],
        "max_turns": snapshot["max_turns"],
        "revision": snapshot["revision"],
        "ticket": snapshot["ticket"],
        "passes": snapshot["passes"],
        "kind": E.KINDS[snapshot["kind"]],
        "accepted": snapshot["result"] == E.OK,
        "result": snapshot["result"],
        "errors": snapshot["errors"],
        "timeout_ms": snapshot["timeout_ms"],
        "route_reason": E.ROUTE_REASONS.get(route_reason, "none"),
    }


class Engine:
    """Валидирующий публичный API контроллера эфира."""

    def __init__(self):
        self._engine = StateMachine()
        self.lock = threading.RLock()

    # ----------------------------------------------------------------- helpers

    def _state(self):
        return as_json(self._engine.snapshot(E.OK), self._engine.route_reason)

    # -------------------------------------------------------------------- API

    def names(self, names):
        if not isinstance(names, list) or len(names) not in (3, 5):
            raise ValueError("Требуются три или пять имён агентов")
        if not all(isinstance(n, str) and "\0" not in n and n.strip()
                   and len(n) <= 30 and len(n.encode("utf-8")) <= 120
                   for n in names):
            raise ValueError("Имя агента должно содержать 1–30 символов")
        with self.lock:
            stripped = [n.strip() for n in names]
            if not self._engine.set_names(stripped):
                raise ValueError("Имена агентов должны быть уникальными и непустыми")
            return self._state()

    def state(self):
        with self.lock:
            return self._state()

    def event(self, action, agent=-1, ticket=0, max_turns=0, text=""):
        if action not in E.ACTIONS:
            raise ValueError("Неизвестное действие ядра")
        if type(agent) is not int or agent < -1 or agent >= len(self._engine.names):
            raise ValueError("Неверный номер агента")
        if type(ticket) is not int or ticket < 0 or ticket > 0xFFFFFFFF:
            raise ValueError("Некорректный идентификатор хода")
        if type(max_turns) is not int or not (0 <= max_turns <= 200):
            raise ValueError("Некорректный лимит ходов")
        if not isinstance(text, str) or "\0" in text or len(text) > 4000:
            raise ValueError("Слишком длинный текст или NUL в тексте")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Некорректный текст (недопустимый Unicode)") from None
        with self.lock:
            snapshot = self._engine.event(E.ACTIONS[action], agent, ticket,
                                          max_turns, text)
            return as_json(snapshot, self._engine.route_reason)

    def complete_to(self, agent, ticket, text, target_agent=-1):
        if type(agent) is not int or not 0 <= agent < len(self._engine.names):
            raise ValueError("Неверный номер агента")
        if type(target_agent) is not int or not -1 <= target_agent < len(self._engine.names) or target_agent == agent:
            raise ValueError("Неверный адресат")
        if type(ticket) is not int or not 0 <= ticket <= 0xFFFFFFFF:
            raise ValueError("Неверный ticket")
        if not isinstance(text, str) or "\0" in text or len(text) > 4000:
            raise ValueError("Неверный текст")
        with self.lock:
            snapshot = self._engine.complete_to(agent, ticket, text, target_agent)
            return as_json(snapshot, self._engine.route_reason)

    def audit(self, limit=128):
        if type(limit) is not int or not 0 <= limit <= 128:
            raise ValueError("Неверный лимит")
        with self.lock:
            return self._engine.audit_read(limit)

    def close(self):
        with self.lock:
            self._engine.closed = True
