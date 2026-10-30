"""Стабильные числовые коды конечного автомата TRIAD.

Строковые ярлыки для HTTP/UI лежат в :data:`MODES`, :data:`KINDS`,
:data:`ACTIONS` и :data:`ROUTE_REASONS`. Числовые значения — внутренний
контракт машины состояний; менять их можно только вместе с логикой.
"""

# Статусы эфира (snapshot.status)
IDLE = 0
RUNNING = 1
PAUSED = 2
WAIT_USER = 3   # зарезервировано: текущие переходы в этот режим не входят
STOPPED = 4
LIMIT = 5
ERROR = 6
MODES = ["IDLE", "RUNNING", "PAUSED", "WAIT_USER", "STOPPED", "LIMIT", "ERROR"]

# Тип хода (snapshot.kind)
NORMAL = 0
PASS = 1
WAIT = 2
USER_PAUSE = 3
USER_RESUME = 4
KINDS = ["normal", "pass", "wait", "user_pause", "user_resume"]

# Почему роутер выбрал next_agent (диагностика; решение принимает сам роутер)
ROUTE_NONE = -1
ROUTE_ROTATION = 0
ROUTE_TOKEN = 1
ROUTE_ADDRESS = 2
ROUTE_OVERRIDE = 4
ROUTE_DIRECTOR = 6
ROUTE_DONATION = 7
ROUTE_SOCIAL = 8
ROUTE_SOCIAL_RETURN = 9
ROUTE_REASONS = {-1: "none", 0: "rotation", 1: "token", 2: "address",
                 4: "override", 6: "director", 7: "donation", 8: "social",
                 9: "social_return"}

# Действия (публичные имена -> числовые коды)
ACTIONS = {"start": 1, "claim": 2, "complete": 3, "user": 4, "pause": 5,
           "resume": 6, "stop": 7, "reset": 9, "fail": 10,
           "tick": 13, "recover": 14,
           "director": 15, "priority_donation": 16, "social": 17,
           "social_return": 18}

START = 1
CLAIM = 2
COMPLETE = 3
USER = 4
PAUSE = 5
RESUME = 6
STOP = 7

RESET = 9
FAIL = 10
TICK = 13
RECOVER = 14
DIRECTOR = 15
PRIORITY_DONATION = 16
SOCIAL = 17
SOCIAL_RETURN = 18

# Результат события
OK = 0
REJECT = 1
STALE = 2
INVALID = 3

# Границы поколений и лимита ходов
UINT_MAX = 0xFFFFFFFF
INT_MAX = 0x7FFFFFFF

# Максимальная длина текста события в байтах UTF-8 и ёмкость журнала аудита
TEXT_BYTES = 16000
AUDIT_CAPACITY = 128
