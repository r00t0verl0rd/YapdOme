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

DEFAULT_NAMES = ("архитектор", "скептик", "экспериментатор")


def now_ms():
    """Монотонное время в миллисекундах (аналог clock_gettime в C-ядре)."""
    return int(time.monotonic() * 1000)


class StateMachine:
    """Конечный автомат эфира. Публичная обёртка — yapdome.engine.api.Engine."""

    def __init__(self):
        self.status = E.IDLE
        self.agent = -1
        self.next_agent = 0
        self.turns = 0
        self.max_turns = 0
        self.passes = 0
        self.kind = E.NORMAL
        self.cooldown_until = 0
        self.errors = 0
        self.reviewing = 0
        self.pending_reply = -1
        self.revision = 0
        self.ticket = 0
        self.review_ticket = 0
        self.deadline_ms = 0
        self.review_deadline_ms = 0
        self.names = list(DEFAULT_NAMES)        # lowercased display names
        self.route_override = -1
        self.route_reason = E.ROUTE_NONE
        self.last_turn = [-1, -1, -1]
        self._audit = deque(maxlen=E.AUDIT_CAPACITY)
        self._audit_sequence = 0
        self.lock = threading.RLock()
        self.closed = False

    # ------------------------------------------------------------------ снимок

    def snapshot(self, result=E.OK):
        review_ms = 0
        if self.reviewing:
            review_ms = max(0, self.review_deadline_ms - now_ms())
        timeout_ms = 0
        if self.deadline_ms and self.status in (E.REVIEW, E.WAIT_USER):
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
            "cooldown_until": self.cooldown_until,
            "errors": self.errors,
            "timeout_ms": int(timeout_ms),
            "reviewing": bool(self.reviewing),
            "review_ticket": self.review_ticket,
            "review_ms": int(review_ms),
        }

    # ------------------------------------------------------------------- имена

    def set_names(self, names):
        lowered = [lower_text(name) for name in names]
        if any(not name for name in lowered) or len(set(lowered)) != 3:
            return False
        if lowered != list(self.names):
            self.names = lowered
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

    def event(self, action, agent=-1, ticket=0, max_turns=0, auto_interrupt=False, text=""):
        with self.lock:
            return self._event(action, agent, ticket, max_turns, auto_interrupt, text)

    def _expired(self):
        return bool(self.deadline_ms) and now_ms() >= self.deadline_ms

    def _event(self, action, agent, ticket, max_turns, auto_interrupt, text):
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
        if self.ticket == E.UINT_MAX or self.review_ticket == E.UINT_MAX:
            if self.status != E.ERROR or self.agent != -1 or self.reviewing:
                self.revision += 1
            self.status = E.ERROR
            self.agent = -1
            self.reviewing = 0
            self.deadline_ms = 0
            self.review_deadline_ms = 0
            return self.snapshot(E.REJECT)

        # Просроченные решения не применяются, даже если TICK ещё не пришёл.
        if self.status in (E.WAIT_USER, E.REVIEW) and self._expired():
            self.status = E.RUNNING
            self.agent = -1
            self.deadline_ms = 0
            self.ticket += 1
            self.revision += 1
            self.passes = 0
            self.kind = E.IGNORE

        # Классификация доната — отдельная неблокирующая линия, речь не глушит.
        if self.reviewing and now_ms() >= self.review_deadline_ms:
            self.reviewing = 0
            self.review_deadline_ms = 0
            self.kind = E.IGNORE
            self.revision += 1

        previous_kind = self.kind
        if action != E.TICK:
            self.kind = E.NORMAL
        result = self._apply(action, agent, ticket, max_turns, auto_interrupt, text)
        if result != E.OK:
            self.kind = previous_kind
        if self.reviewing and self.status != E.RUNNING:
            self.reviewing = 0
            self.review_deadline_ms = 0
            self.review_ticket += 1

        self._record_audit(action, agent, result, before_status, before_speaker)
        return self.snapshot(result)

    def _apply(self, action, agent, ticket, max_turns, auto_interrupt, text):
        if action == E.START:
            self.status = E.RUNNING
            self.agent = -1
            self.next_agent = 0
            self.turns = 0
            self.max_turns = max_turns if 0 <= max_turns <= 200 else 0
            self.passes = 0
            self.cooldown_until = 0
            self.deadline_ms = 0
            self.errors = 0
            self.reviewing = 0
            self.review_deadline_ms = 0
            self.review_ticket += 1
            self.pending_reply = -1
            self.route_reason = E.ROUTE_ROTATION
            self.last_turn = [-1, -1, -1]
            self.revision += 1
            self.ticket += 1
            return E.OK

        if action == E.CLAIM:
            if self.status != E.RUNNING or self.agent != -1:
                return E.REJECT
            if self.next_agent < 0 or self.next_agent > 2:
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
            if 0 <= self.route_override < 3 and self.route_override != self.agent:
                self.next_agent = self.route_override
                reason = E.ROUTE_OVERRIDE
            else:
                self.next_agent, reason = route_from_text(
                    self.names, self.last_turn, text, self.agent, False)
            self.route_reason = reason
            # Прерванный спикер сохраняет право ответа, если явно не передал слово.
            if self.pending_reply >= 0:
                if reason == E.ROUTE_ROTATION:
                    self.next_agent = self.pending_reply
                    self.route_reason = E.ROUTE_PENDING
                self.pending_reply = -1
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
                self.reviewing = 0
            # Завершение хода инвалидирует его ticket: поздние события
            # директора/слушателей не действуют на межходовое состояние.
            self.ticket += 1
            self.revision += 1
            return E.OK

        if action == E.USER:
            if self.status in (E.IDLE, E.STOPPED, E.LIMIT, E.ERROR, E.PAUSED):
                return E.REJECT
            self.kind = user_kind(text)
            speaker = self.agent if self.agent >= 0 else (self.next_agent + 2) % 3
            self.next_agent, reason = route_from_text(
                self.names, self.last_turn, text, speaker, True)
            self.route_reason = reason
            self.pending_reply = -1
            self.agent = -1
            self.ticket += 1
            self.revision += 1
            self.passes = 0
            self.deadline_ms = 0
            self.reviewing = 0
            self.review_ticket += 1
            self.review_deadline_ms = 0
            # Текст — разговорный ввод, а не команда бессрочной остановки.
            self.status = E.RUNNING
            return E.OK

        if action == E.PAUSE:
            if self.status not in (E.RUNNING, E.WAIT_USER, E.REVIEW):
                return E.REJECT
            if self.agent >= 0:
                self.next_agent = self.agent
            self.agent = -1
            self.status = E.PAUSED
            self.deadline_ms = 0
            self.reviewing = 0
            self.revision += 1
            self.ticket += 1
            self.review_ticket += 1
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
            self.reviewing = 0
            self.pending_reply = -1
            self.revision += 1
            self.ticket += 1
            self.review_ticket += 1
            return E.OK

        if action == E.INTERRUPT:
            if (self.status != E.RUNNING or agent < 0 or agent > 2
                    or agent == self.agent):
                return E.REJECT
            if ticket != self.ticket:
                return E.STALE
            if self.agent < 0:
                # Между текстовыми ходами браузер ещё может озвучивать буфер.
                # Только явный операторский override перенаправляет этот хвост.
                if auto_interrupt:
                    return E.REJECT
                self.next_agent = agent
                self.pending_reply = -1
                self.route_reason = E.ROUTE_OVERRIDE
                self.revision += 1
                self.ticket += 1
                return E.OK
            if self.max_turns > 0 and self.turns >= self.max_turns:
                return E.REJECT
            if auto_interrupt and self.turns < self.cooldown_until:
                return E.REJECT
            if auto_interrupt:
                self.cooldown_until = self.turns + 2
            self.pending_reply = self.agent
            self.next_agent = agent
            self.agent = -1
            self.passes = 0
            self.route_reason = E.ROUTE_INTERRUPT
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
            self.cooldown_until = 0
            self.errors = 0
            self.reviewing = 0
            self.pending_reply = -1
            self.route_reason = E.ROUTE_NONE
            self.last_turn = [-1, -1, -1]
            self.revision += 1
            self.ticket += 1
            self.review_ticket += 1
            return E.OK

        if action == E.FAIL:
            if self.status != E.RUNNING or self.ticket != ticket:
                return E.STALE
            self.agent = -1
            self.status = E.ERROR
            self.reviewing = 0
            self.review_deadline_ms = 0
            self.review_ticket += 1
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
                self.reviewing = 0
                self.review_ticket += 1     # не жечь подписку бесконечно
            elif self.max_turns > 0 and self.turns >= self.max_turns:
                self.status = E.LIMIT
            return E.OK

        if action == E.SOCIAL:
            # Социальный пол может переопределить ТОЛЬКО обычную ротацию
            # между завершёнными ходами и с корректным ticket поколения.
            if (self.status != E.RUNNING or self.agent != -1
                    or ticket != self.ticket
                    or self.route_reason != E.ROUTE_ROTATION
                    or agent < 0 or agent > 2
                    or self.last_turn[agent] == self.turns):
                return E.REJECT
            self.next_agent = agent
            self.route_reason = E.ROUTE_SOCIAL
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
            self.pending_reply = -1
            self.route_reason = E.ROUTE_DONATION
            self.passes = 0
            self.ticket += 1
            self.revision += 1
            return E.OK

        if action == E.DONATION:
            if (self.status not in (E.RUNNING, E.WAIT_USER)) or self.reviewing:
                return E.REJECT
            self.reviewing = 1
            self.review_deadline_ms = now_ms() + E.DONATION_REVIEW_MS
            self.review_ticket += 1
            self.revision += 1
            self.kind = E.DONATION_INPUT
            return E.OK

        if action == E.DECISION:
            if not self.reviewing or self.review_ticket != ticket:
                return E.STALE
            if text == "focus":
                self.kind = E.FOCUS
            elif text == "brief":
                self.kind = E.BRIEF
            else:
                self.kind = E.IGNORE
            self.reviewing = 0
            self.review_deadline_ms = 0
            self.revision += 1
            self.review_ticket += 1
            if self.status == E.WAIT_USER and self.kind != E.IGNORE:
                self.status = E.RUNNING
                self.deadline_ms = 0
                self.passes = 0
            return E.OK

        if action == E.TICK:
            # Авторитетны только entry-time переходы по дедлайнам выше.
            return E.OK

        return E.INVALID

    # -------------------------------------------------------- structured route

    def complete_to(self, agent, ticket, text, target_agent):
        """Стабильный способ адресовать завершённый ход; -1 — прежний парсинг."""
        if target_agent < -1 or target_agent > 2 or target_agent == agent:
            return self.snapshot(E.INVALID)
        self.route_override = target_agent
        snapshot = self._event(E.COMPLETE, agent, ticket, 0, 0, text)
        self.route_override = -1
        return snapshot
