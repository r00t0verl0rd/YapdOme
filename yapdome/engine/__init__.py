"""Диалоговый контроллер TRIAD.

Публичная точка входа — :class:`Engine`:

- ``names()`` / ``state()`` / ``event()`` / ``complete_to()`` / ``audit()``;
- снимки в JSON-совместимых словарях со строковыми ярлыками;
- отклонённые и устаревшие события не меняют состояние.

Слои:

- :mod:`yapdome.engine.enums` — числовые коды и строковые ярлыки;
- :mod:`yapdome.engine.routing` — текстовый роутинг (TO-токены, имена, цитаты);
- :mod:`yapdome.engine.state` — машина состояний и журнал аудита;
- :mod:`yapdome.engine.api` — валидирующий фасад :class:`Engine`.
"""

from .enums import MODES, KINDS, ACTIONS, ROUTE_REASONS
from .api import Engine, Snapshot, AuditEntry, as_json

__all__ = ["Engine", "Snapshot", "AuditEntry", "as_json",
           "MODES", "KINDS", "ACTIONS", "ROUTE_REASONS"]
