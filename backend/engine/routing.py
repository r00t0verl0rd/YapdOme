"""Текстовый слой роутинга.

Lowercasing ограничен ASCII и кириллицей (без локали), цитаты маскируются
до поиска имён, явный [[TO:...]] всегда выигрывает у эвристик.
"""

from .enums import (NORMAL, PASS, WAIT, USER_PAUSE, USER_RESUME,
                    ROUTE_ROTATION, ROUTE_TOKEN, ROUTE_ADDRESS)


def lower_text(text):
    """Lowercase ASCII и кириллицы — как делал C-код, без учёта локали.

    Имена и текст реплик проходят один и тот же преобразователь, поэтому
    сравнение остаётся согласованным; прочие письменности не меняются.
    """
    out = []
    for ch in text:
        code = ord(ch)
        if code < 128:
            out.append(chr(code + 32) if 65 <= code <= 90 else ch)
        elif 0x0410 <= code <= 0x042F:          # А–Я
            out.append(chr(code + 0x20))
        elif code == 0x0401:                    # Ё
            out.append("\u0451")
        else:
            out.append(ch)
    return "".join(out)


_TRIM_CHARS = (" ", "\t", "\n", "\r", '"', "'",
               "\u00ab", "\u00bb", "\u201c", "\u201d")


def trim_start(text):
    """Пропускает пробельные символы и распространённые кавычки в начале."""
    i = 0
    while i < len(text) and text[i] in _TRIM_CHARS:
        i += 1
    return text[i:]


_PAUSE_PREFIXES = ("стой", "стоп", "останов", "подожд", "погод", "не тороп",
                   "пауза", "помолч", "wait", "hold on", "pause", "stop")
_RESUME_PREFIXES = ("продолж", "возобнов", "поехали", "resume", "continue", "go on")


def pause_command(text):
    return any(text.startswith(prefix) for prefix in _PAUSE_PREFIXES)


def resume_command(text):
    return any(text.startswith(prefix) for prefix in _RESUME_PREFIXES)


def user_kind(text):
    """Реплика ведущего классифицируется только как пауза/продолжение/обычная."""
    lowered = trim_start(lower_text(text))
    if pause_command(lowered):
        return USER_PAUSE
    if resume_command(lowered):
        return USER_RESUME
    return NORMAL


_MARKER_SKIP = " \t\r\n.!,:;"


def only_marker(text, label):
    """Ровно один маркер и ничего содержательного после него.

    «[[PASS]].» — pass, «Pass the ball» — обычная реплика.
    """
    n = len(label)
    if text.startswith("[[") and text[2:2 + n] == label and text[2 + n:2 + n + 2] == "]]":
        text = text[n + 4:]
    elif text.startswith("[") and text[1:1 + n] == label and text[n + 1:n + 2] == "]":
        text = text[n + 2:]
    elif text.startswith(label):
        text = text[n:]
    else:
        return False
    return not text.lstrip(_MARKER_SKIP)


_DIRECTIVE_PREFIXES = ("to:", "re:", "claim:", "pass", "wait_user", "cont")
_DIRECTIVE_SKIP = " \t\r\n.,!;:"


def directive_only(text):
    """Ход из одних управляющих директив не содержит речи — это pass.

    Пустые директивы никогда не озвучиваются, но и не блокируют эфир.
    """
    i = 0
    length = len(text)
    while i < length:
        if text.startswith("[[", i):
            end = text.find("]]", i + 2)
            if end != -1:
                inner = text[i + 2:end]
                if len(inner.encode("utf-8")) <= 140 and any(
                        inner.startswith(prefix) for prefix in _DIRECTIVE_PREFIXES):
                    i = end + 2
                    continue
        if text[i] in _DIRECTIVE_SKIP:
            i += 1
            continue
        return False
    return True


def output_kind(text):
    lowered = trim_start(lower_text(text))
    if only_marker(lowered, "wait_user"):
        return WAIT
    if only_marker(lowered, "pass"):
        return PASS
    if directive_only(lowered):
        return PASS
    if not lowered:
        return PASS
    return NORMAL


def is_word_codepoint(code):
    """«_» намеренно не считается символом слова: в ответах модели это чаще
    markdown-выделение (__Имя__), чем склеенный идентификатор."""
    if code < 0x80:
        return (48 <= code <= 57) or (65 <= code <= 90) or (97 <= code <= 122)
    if 0x0400 <= code <= 0x052F:                # кириллица + supplement
        return True
    if 0x2DE0 <= code <= 0x2DFF:                # Cyrillic Extended-A
        return True
    if 0xA640 <= code <= 0xA69F:                # Cyrillic Extended-B
        return True
    # Прочие не-ASCII письменности консервативно считаем словами, кроме
    # пунктуационных блоков, используемых для украшения адреса.
    if code >= 0x80 and not (0x2000 <= code <= 0x206F) and code != 0xAB and code != 0xBB:
        return True
    return False


def prev_codepoint(text, index):
    return ord(text[index - 1]) if index > 0 else 0


def is_word_start(text, index):
    """Имя засчитывается, только если перед ним нет «приклеенного» символа слова."""
    return not is_word_codepoint(prev_codepoint(text, index))


_DECORATION = " \t*_`\"')]}"
_QUOTES_SKIP = ("\u00ab", "\u00bb", "\u201c", "\u201d", "\u201e", "\u2018", "\u2019")


def address_delimiter(tail):
    """После имени адресата должен идти разделитель (или конец строки)."""
    i = 0
    n = len(tail)
    while i < n:
        ch = tail[i]
        if ch in _DECORATION or ch in _QUOTES_SKIP:
            i += 1
            continue
        break
    if i >= n:
        return True
    ch = tail[i]
    if ch in "\n\r":
        return True
    if ch in ",!:?;.":
        return True
    if ch == "-":
        return True
    if ch in ("\u2014", "\u2013"):              # — –
        return True
    return False


def mask_quotes(names, text):
    """Цитированная речь — данные, а не команда роутинга.

    Сохраняется историческая совместимость: одиночный звательный падеж в
    начале реплики «Имя», ответь — остаётся адресацией.
    """
    chars = list(text)
    length = len(text)
    i = 0
    close = None
    start = 0
    content = 0
    while i < length:
        code = ord(text[i])
        if close is not None:
            if code == close:
                bare = all(ch in " \t\n\v\f\r" for ch in chars[:start])
                name = any(text[content:i] == nm for nm in names)
                if not (bare and name and address_delimiter(text[i + 1:])):
                    for k in range(start, i + 1):
                        chars[k] = " "
                close = None
        else:
            apostrophe_start = (code == ord("'")
                                and (i == 0 or not is_word_codepoint(prev_codepoint(text, i))))
            if code in (ord('"'), ord("`"), 0xAB, 0x201C, 0x201E, 0x2018) or apostrophe_start:
                start = i
                content = i + 1
                if code == 0xAB:
                    close = 0xBB
                elif code in (0x201C, 0x201E):
                    close = 0x201D
                elif code == 0x2018:
                    close = 0x2019
                else:
                    close = code
        i += 1
    if close is not None:
        for k in range(start, length):
            chars[k] = " "
    return "".join(chars)


def token_scan(names, lower):
    """Явная передача слова: [[TO:Имя]], [TO:Имя], [[TO:ANY]], [[TO:SELF]].

    Проверяется до всех эвристик, чтобы markdown, кавычки и переносы строк
    не лишали модель контроля над роутингом. Повреждённый [[TO:имя] не
    принимается повторным проходом single-bracket как [TO:имя].
    """
    for mark, close in (("[[to:", "]]"), ("[to:", "]")):
        at = lower.find(mark)
        while at != -1:
            if mark == "[to:" and at > 0 and lower[at - 1] == "[":
                at = lower.find(mark, at + 1)
                continue
            p = at + len(mark)
            end = lower.find(close, p)
            if end == -1:
                at = lower.find(mark, at + 1)
                continue
            name = lower[p:end]
            if not name or len(name.encode("utf-8")) > 128:
                at = lower.find(mark, end + 1)
                continue
            name = name.strip(" \t")
            if name in ("any", "*"):
                return -1, False, True
            if name in ("self", "me"):
                return -1, True, False
            for i, nm in enumerate(names):
                if nm and name == nm:
                    return i, False, False
            at = lower.find(mark, end + 1)
    return -1, False, False


def default_target(last_turn, current):
    """Адресат по умолчанию: тот, кто дольше всех ждёт слова.

    Без перебиваний это обычная ротация; после перебивания карусель
    ломается и получается ритм A -> B -> A -> C настоящих дебатов.
    """
    best = -1
    best_turn = 0
    count = len(last_turn)
    for k in range(1, count):
        i = (current + k) % count
        if i == current:
            continue
        if best < 0 or last_turn[i] < best_turn:
            best = i
            best_turn = last_turn[i]
    return best if best >= 0 else (current + 1) % count


def route_from_text(names, last_turn, text, current, allow_current):
    """Выбор следующего спикера по тексту завершённого хода.

    Возвращает (next_agent, route_reason):
    1) явный [[TO:...]] — приоритет над всем;
    2) естественная адресация по имени (с учётом границ слов и цитат);
    3) ротация «кто дольше ждал».
    """
    lower = lower_text(text)
    masked = mask_quotes(names, lower)

    target, self_flag, any_flag = token_scan(names, masked)
    if target >= 0:
        return target, ROUTE_TOKEN
    if self_flag:
        return current, ROUTE_TOKEN
    if any_flag:
        return default_target(last_turn, current), ROUTE_ROTATION

    best = None
    chosen = -1
    for i, name in enumerate(names):
        if i == current and not allow_current:
            continue
        if len(name) < 3:                       # короткие имена требуют [[TO:имя]]
            continue
        at = masked.find(name)
        while at != -1:
            tail = at + len(name)
            if is_word_start(masked, at) and address_delimiter(masked[tail:]):
                if best is None or at < best:
                    best = at
                    chosen = i
            at = masked.find(name, at + len(name))
    if chosen >= 0:
        return chosen, ROUTE_ADDRESS
    return default_target(last_turn, current), ROUTE_ROTATION
