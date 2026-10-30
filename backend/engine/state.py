"""Детерминированный контроллер разговора.

Один экземпляр :class:`StateMachine` — единственный источник истины о том,
кто говорит следующим. Все мутации происходят внутри :meth:`StateMachine.event`;
отклонённые и устаревшие события не меняют состояние. Сетевого доступа и
доступа к моделям здесь нет.
"""

import threading
import time
from collections import deque

from . import enums as E
from .routing import (lower_text, output_kind, user_kind, route_from_text,
                      default_target)

DEFAULT_NAMES = ("норман", "глитч", "джесси", "вольт", "луна")


def now_ms():
    """Монотонное время в миллисекундах."""
    return int(time.monotonic() * 1000)


class StateMachine:
    """Конечный автомат эфира. Публичная обёртка — backend.engine.api.Engine."""

    def __init__(self):
        self.status = E.IDLE
        self.agent = -1
        self.next_agent = 0
        self.turns = 0
        self.max_turns = 0
        self.passes = 0
        self.kind = E.NORMAL
        self.errors = 0
        self.revision = 0
        self.ticket = 0
        self.deadline_ms = 0
        self.names = list(DEFAULT_NAMES)        # lowercased display names
        self.route_override = -1
        self.route_reason = E.ROUTE_NONE
        self.last_turn = [-1] * len(self.names)
        self._audit = deque(maxlen=E.AUDIT_CAPACITY)
        self._audit_sequence = 0
        self.lock = threading.RLock()
        self.closed = False

    # ------------------------------------------------------------------ снимок

    def snapshot(self, result=E.OK):
        timeout_ms = 0
        if self.deadline_ms and self.status == E.WAIT_USER:
            timeout_ms = max(0, min(60000, self.deadline_ms - now_ms()))
        return {
            "status": self.status,
            "agent": self.agent,
            "next_agent": self.next_agent,
            "turns": self.turns,
            "max_turns": self.max_turns,
            "revision": self.revision,
            "ticket": self.ticket,
            "passes": self.passes,
            "kind": self.kind,
            "result": result,
            "errors": self.errors,
            "timeout_ms": int(timeout_ms),
        }

    # ------------------------------------------------------------------- имена

    def set_names(self, names):
        lowered = [lower_text(name) for name in names]
        if any(not name for name in lowered) or len(lowered) not in (3, 5) or len(set(lowered)) != len(lowered):
            return False
        if lowered != list(self.names):
            self.names = lowered
            self.last_turn = [-1] * len(lowered)
            if self.next_agent >= len(lowered):
                self.next_agent = 0
            self.revision += 1
        return True

    # ------------------------------------------------------------------- аудит

    def audit_read(self, capacity=E.AUDIT_CAPACITY):
        count = min(len(self._audit), max(0, capacity))
        entries = list(self._audit)
        return entries[-count:] if count else []

    def _record_audit(self, action, actor, result, status_before, speaker_before):
        self._audit_sequence += 1
        self._audit.append({
            "sequence": self._audit_sequence,
            "monotonic_ms": now_ms(),
            "action": action,
            "actor": actor,
            "result": result,
            "status_before": status_before,
            "status_after": self.status,
            "speaker_before": speaker_before,
            "speaker_after": self.agent,
            "next_agent": self.next_agent,
            "ticket": self.ticket,
            "revision": self.revision,
        })

    # ----------------------------------------------------------- события ядра

    def event(self, action, agent=-1, ticket=0, max_turns=0, text=""):
        with self.lock:
            return self._event(action, agent, ticket, max_turns, text)

    def _expired(self):
        return bool(self.deadline_ms) and now_ms() >= self.deadline_ms

    def _event(self, action, agent, ticket, max_turns, text):
        before_status = self.status
        before_speaker = self.agent

        try:
            raw = text.encode("utf-8")
        except UnicodeEncodeError:
            return self.snapshot(E.INVALID)
        if len(raw) > E.TEXT_BYTES:
            return self.snapshot(E.INVALID)

        # 32-битные поколения: отказ закрытым способом, а не переиспользование
        # токена, который может нести задержанный колбэк.
        if self.ticket == E.UINT_MAX:
            if self.status != E.ERROR or self.agent != -1:
                self.revision += 1
            self.status = E.ERROR
            self.agent = -1
            self.deadline_ms = 0
            return self.snapshot(E.REJECT)

        # Просроченные решения не применяются, даже если TICK ещё не пришёл.
        if self.status == E.WAIT_USER and self._expired():
            self.status = E.RUNNING
            self.agent = -1
            self.deadline_ms = 0
            self.ticket += 1
            self.revision += 1
            self.passes = 0
            self.kind = E.NORMAL

        previous_kind = self.kind
        if action != E.TICK:
            self.kind = E.NORMAL
        result = self._apply(action, agent, ticket, max_turns, text)
        if result != E.OK:
            self.kind = previous_kind

        self._record_audit(action, agent, result, before_status, before_speaker)
        return self.snapshot(result)

    def _apply(self, action, agent, ticket, max_turns, text):
        if action == E.START:
            self.status = E.RUNNING
            self.agent = -1
            self.next_agent = 0
            self.turns = 0
            self.max_turns = max_turns if 0 <= max_turns <= 200 else 0
            self.passes = 0
            self.deadline_ms = 0
            self.errors = 0
            self.route_reason = E.ROUTE_ROTATION
            self.last_turn = [-1] * len(self.names)
            self.revision += 1
            self.ticket += 1
            return E.OK

        if action == E.CLAIM:
            if self.status != E.RUNNING or self.agent != -1:
                return E.REJECT
            if self.next_agent < 0 or self.next_agent >= len(self.names):
                return E.REJECT
            if self.max_turns > 0 and self.turns >= self.max_turns:
                self.status = E.LIMIT
                self.revision += 1
                return E.OK
            if self.turns >= E.INT_MAX - 2:
                self.status = E.LIMIT
                self.revision += 1
                return E.OK
            self.agent = self.next_agent
            self.turns += 1
            self.ticket += 1
            self.revision += 1
            self.last_turn[self.agent] = self.turns
            return E.OK

        if action == E.COMPLETE:
            if (self.status != E.RUNNING or self.agent < 0
                    or self.ticket != ticket or self.agent != agent):
                return E.STALE
            self.kind = output_kind(text)
            reason = E.ROUTE_ROTATION
            if 0 <= self.route_override < len(self.names) and self.route_override != self.agent:
                self.next_agent = self.route_override
                reason = E.ROUTE_OVERRIDE
            else:
                self.next_agent, reason = route_from_text(
                    self.names, self.last_turn, text, self.agent, False)
            self.route_reason = reason
            self.agent = -1
            self.errors = 0
            if self.kind in (E.WAIT, E.PASS):
                self.passes = min(3, self.passes + 1)
            else:
                self.passes = 0
            # Финальный лимит авторитетнее добровольного WAIT модели.
            if self.max_turns > 0 and self.turns >= self.max_turns:
                self.status = E.LIMIT
                self.deadline_ms = 0
            # Завершение хода инвалидирует его ticket: поздние события не действуют на межходовое состояние.
            self.ticket += 1
            self.revision += 1
            return E.OK

        if action == E.USER:
            if self.status in (E.IDLE, E.STOPPED, E.LIMIT, E.ERROR, E.PAUSED):
                return E.REJECT
            self.kind = user_kind(text)
            speaker = self.agent if self.agent >= 0 else (self.next_agent + len(self.names) - 1) % len(self.names)
            self.next_agent, reason = route_from_text(
                self.names, self.last_turn, text, speaker, True)
            self.route_reason = reason
            self.agent = -1
            self.ticket += 1
            self.revision += 1
            self.passes = 0
            self.deadline_ms = 0
            # Текст — разговорный ввод, а не команда бессрочной остановки.
            self.status = E.RUNNING
            return E.OK

        if action == E.PAUSE:
            if self.status not in (E.RUNNING, E.WAIT_USER):
                return E.REJECT
            if self.agent >= 0:
                self.next_agent = self.agent
            self.agent = -1
            self.status = E.PAUSED
            self.deadline_ms = 0
            self.revision += 1
            self.ticket += 1
            return E.OK

        if action == E.RESUME:
            if self.status not in (E.PAUSED, E.WAIT_USER):
                return E.REJECT
            self.status = E.RUNNING
            self.deadline_ms = 0
            self.passes = 0
            self.revision += 1
            return E.OK

        if action == E.STOP:
            if self.status in (E.IDLE, E.STOPPED):
                return E.REJECT
            self.status = E.STOPPED
            self.agent = -1
            self.deadline_ms = 0
            self.revision += 1
            self.ticket += 1
            return E.OK


        if action == E.RESET:
            if self.status == E.IDLE:
                return E.REJECT
            self.status = E.IDLE
            self.agent = -1
            self.next_agent = 0
            self.turns = 0
            self.passes = 0
            self.deadline_ms = 0
            self.errors = 0
            self.route_reason = E.ROUTE_NONE
            self.last_turn = [-1] * len(self.names)
            self.revision += 1
            self.ticket += 1
            return E.OK

        if action == E.FAIL:
            if self.status != E.RUNNING or self.ticket != ticket:
                return E.STALE
            self.agent = -1
            self.status = E.ERROR
            self.revision += 1
            self.ticket += 1
            return E.OK

        if action == E.RECOVER:
            if self.status != E.RUNNING or self.agent < 0 or self.ticket != ticket:
                return E.STALE
            self.next_agent = default_target(self.last_turn, self.agent)
            self.route_reason = E.ROUTE_ROTATION
            self.agent = -1
            self.passes = 0
            self.errors += 1
            self.ticket += 1
            self.revision += 1
            if self.errors >= 3:
                self.status = E.ERROR
            elif self.max_turns > 0 and self.turns >= self.max_turns:
                self.status = E.LIMIT
            return E.OK

        if action == E.SOCIAL:
            # Социальный пол может переопределить ТОЛЬКО обычную ротацию
            # между завершёнными ходами и с корректным ticket поколения.
            if (self.status != E.RUNNING or self.agent != -1
                    or ticket != self.ticket
                    or self.route_reason != E.ROUTE_ROTATION
                    or agent < 0 or agent >= len(self.names)
                    or self.last_turn[agent] == self.turns):
                return E.REJECT
            self.next_agent = agent
            self.route_reason = E.ROUTE_SOCIAL
            self.ticket += 1
            self.revision += 1
            return E.OK

        if action == E.SOCIAL_RETURN:
            # End a bounded two-person exchange. This may supersede a model's
            # repeated TO marker, but never a live donation or an active speaker.
            if (self.status != E.RUNNING or self.agent != -1
                    or ticket != self.ticket
                    or self.route_reason not in (
                        E.ROUTE_ROTATION, E.ROUTE_TOKEN, E.ROUTE_ADDRESS,
                        E.ROUTE_DIRECTOR, E.ROUTE_SOCIAL
                    )
                    or agent < 0 or agent > 2):
                return E.REJECT
            self.next_agent = agent
            self.route_reason = E.ROUTE_SOCIAL_RETURN
            self.ticket += 1
            self.revision += 1
            return E.OK

        if action == E.DIRECTOR:
            # Директор может улучшить только обычную ротацию между ходами.
            # Явный TO/адрес, вмешательства и pending replies выигрывают.
            # Полномочий STOP/PAUSE/DONATION/перебивания у него нет.
            if (self.status != E.RUNNING or self.agent != -1
                    or ticket != self.ticket
                    or self.route_reason != E.ROUTE_ROTATION
                    or agent < 0 or agent > 2
                    or self.last_turn[agent] == self.turns):
                return E.REJECT
            self.next_agent = agent
            self.route_reason = E.ROUTE_DIRECTOR
            self.ticket += 1
            self.revision += 1
            return E.OK

        if action == E.PRIORITY_DONATION:
            # Оператор отдаёт локально принятый донат; его текст в роутинг не
            # попадает. Донат приоритетнее обычной/явной/директорской
            # маршрутизации, но не может перебить говорящего или PAUSE/STOP.
            if (self.status != E.RUNNING or self.agent != -1
                    or agent < 0 or agent > 2):
                return E.REJECT
            self.next_agent = agent
            self.route_reason = E.ROUTE_DONATION
            self.passes = 0
            self.ticket += 1
            self.revision += 1
            return E.OK

        if action == E.TICK:
            # Авторитетны только entry-time переходы по дедлайнам выше.
            return E.OK

        return E.INVALID

    # -------------------------------------------------------- structured route

    def complete_to(self, agent, ticket, text, target_agent):
        """Стабильный способ адресовать завершённый ход; -1 — прежний парсинг."""
        if target_agent < -1 or target_agent >= len(self.names) or target_agent == agent:
            return self.snapshot(E.INVALID)
        self.route_override = target_agent
        snapshot = self._event(E.COMPLETE, agent, ticket, 0, text)
        self.route_override = -1
        return snapshot
