"""Stata 코드 정적 분석용 경량 lexer.

guard(명령 차단)와 output_filter가 "실행 단위 문장"과 "명령 이름"을 얻기 위해 사용함.
완전한 Stata 파서가 아니며 사고 방지 장치임(설계서 §8.3).

처리 범위
- 주석: ``* ...``(문장 시작), ``// ...``(앞에 공백 필요), ``/* ... */``(여러 줄 가능)
- 줄 연결: ``///``
- ``#delimit ;`` / ``#delimit cr`` 전환
- 문자열: ``"..."``, 복합 따옴표 `` `"..."' ``
- 블록: ``mata`` / ``mata:`` ~ ``end``, ``python`` / ``python:`` ~ ``end``
- 접두 명령: quietly·noisily·capture, ``by ...:`` 등 콜론형 접두어

미처리(알려진 한계)
- ``if exp command`` 형태의 한 줄 조건문 내부 명령
- 매크로 확장 후에야 드러나는 명령(→ guard가 '동적 명령'으로 승인 요구)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 중첩 블록 주석 허용 여부. False가 보수적 해석(주석이 먼저 끝난 것으로 보고 뒤 코드를 검사)임.
NESTED_BLOCK_COMMENTS = False

_DELIMIT_RE = re.compile(r"^#d(?:e(?:l(?:i(?:m(?:i(?:t)?)?)?)?)?)?\b\s*(;|cr)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Statement:
    """주석 제거·줄 연결이 끝난 실행 단위 문장."""

    line: int  # 원본 기준 시작 줄(1부터)
    text: str
    context: str = "stata"  # "stata" | "mata" | "python"


@dataclass(frozen=True)
class ParsedCommand:
    """접두어를 걷어낸 명령."""

    name: str  # 소문자 명령 토큰. 매크로로 시작하면 "<macro>", "!"는 "!"
    args: str  # 명령 뒤 나머지 문자열(원문 대소문자 유지)
    prefixes: tuple[str, ...] = field(default_factory=tuple)
    raw: str = ""


def abbrev_match(token: str, full: str, minimum: str) -> bool:
    """Stata 최소 약어 규칙: token이 minimum 이상 길이이면서 full의 앞부분이면 일치."""
    t = token.lower()
    return len(t) >= len(minimum) and full.startswith(t) and t.startswith(minimum)


def split_statements(code: str) -> list[tuple[int, str]]:
    """주석 제거·``///`` 연결·``#delimit`` 처리 후 (시작 줄, 문장) 목록 반환."""
    statements: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_line: int | None = None
    line = 1
    semicolon_mode = False
    i = 0
    n = len(code)

    def buf_blank() -> bool:
        return "".join(buf).strip() == ""

    def flush() -> None:
        nonlocal buf_line, semicolon_mode
        text = "".join(buf).strip()
        buf.clear()
        start = buf_line
        buf_line = None
        if not text:
            return
        m = _DELIMIT_RE.match(text)
        if m:
            semicolon_mode = (m.group(1) or "cr") == ";"
            return
        statements.append((start or line, text))

    def append(ch: str) -> None:
        nonlocal buf_line
        if buf_line is None and not ch.isspace():
            buf_line = line
        buf.append(ch)

    while i < n:
        c = code[i]

        # ── 문장 시작의 * 주석 ──
        if c == "*" and buf_blank() and not code.startswith("*/", i):
            if semicolon_mode:
                j = code.find(";", i)
                j = n if j == -1 else j
                line += code.count("\n", i, j)
                i = j + 1
                buf.clear()
                buf_line = None
                continue
            # cr 모드: 줄 끝까지, 끝이 ' ///'이면 다음 줄까지 이어서 주석
            while True:
                j = code.find("\n", i)
                j = n if j == -1 else j
                segment = code[i:j]
                i = j
                if re.search(r"(^|\s)///", segment) and i < n:
                    line += 1
                    i += 1
                    continue
                break
            buf.clear()
            buf_line = None
            continue

        # ── #delimit ; 모드에서 #delimit 줄은 줄 단위로 처리 ──
        if semicolon_mode and c == "#" and buf_blank():
            j = code.find("\n", i)
            j = n if j == -1 else j
            directive = code[i:j].strip()
            if _DELIMIT_RE.match(directive):
                m = _DELIMIT_RE.match(directive)
                semicolon_mode = (m.group(1) or "cr") == ";"
                buf.clear()
                buf_line = None
                i = j
                continue

        # ── 블록 주석 ──
        if code.startswith("/*", i):
            depth = 1
            i += 2
            while i < n and depth > 0:
                if code.startswith("*/", i):
                    depth -= 1
                    i += 2
                    continue
                if NESTED_BLOCK_COMMENTS and code.startswith("/*", i):
                    depth += 1
                    i += 2
                    continue
                if code[i] == "\n":
                    line += 1
                i += 1
            append(" ")
            continue

        # ── // 주석과 /// 연결 ──
        if code.startswith("//", i) and (i == 0 or code[i - 1] in " \t\r\n" or buf_blank()):
            is_continuation = code.startswith("///", i)
            j = code.find("\n", i)
            j = n if j == -1 else j
            i = j
            if is_continuation and i < n:
                line += 1
                i += 1  # 줄바꿈 삼킴 → 다음 줄과 연결
                append(" ")
            continue

        # ── 문자열 ──
        if code.startswith('`"', i):
            depth = 0
            while i < n and code[i] != "\n":
                if code.startswith('`"', i):
                    depth += 1
                    append('`"')
                    i += 2
                    continue
                if code.startswith("\"'", i):
                    depth -= 1
                    append("\"'")
                    i += 2
                    if depth == 0:
                        break
                    continue
                append(code[i])
                i += 1
            continue
        if c == '"':
            append(c)
            i += 1
            while i < n and code[i] not in '"\n':
                append(code[i])
                i += 1
            if i < n and code[i] == '"':
                append('"')
                i += 1
            continue

        # ── 종결자 ──
        if c == "\n":
            if semicolon_mode:
                append(" ")
            else:
                flush()
            line += 1
            i += 1
            continue
        if c == ";" and semicolon_mode:
            flush()
            i += 1
            continue

        append(c)
        i += 1

    flush()
    return statements


_MATA_BLOCK_RE = re.compile(r"^mata\s*:?\s*$", re.IGNORECASE)
_PY_TOKEN_RE = re.compile(r"^([A-Za-z]+)\s*(:)?\s*(.*)$", re.DOTALL)


def _is_python_token(token: str) -> bool:
    return abbrev_match(token, "python", "py")


def iter_statements(code: str) -> list[Statement]:
    """문장 목록 + mata/python 블록 문맥 표시."""
    result: list[Statement] = []
    context = "stata"
    for line, text in split_statements(code):
        if context in ("mata", "python"):
            if text.strip().lower() == "end":
                context = "stata"
                continue
            result.append(Statement(line, text, context))
            continue

        if _MATA_BLOCK_RE.match(text):
            context = "mata"
            continue
        m = _PY_TOKEN_RE.match(text)
        if m and _is_python_token(m.group(1)):
            rest = m.group(3).strip()
            if not rest:
                context = "python"
                result.append(Statement(line, text, "python"))  # 블록 시작 자체도 기록
                continue
            result.append(Statement(line, text, "python"))
            continue
        mm = re.match(r"^mata\b\s*:?\s*(.+)$", text, re.IGNORECASE | re.DOTALL)
        if mm:
            result.append(Statement(line, mm.group(1).strip(), "mata"))
            continue
        result.append(Statement(line, text, "stata"))
    return result


# ── 접두어 처리 ────────────────────────────────────────────────

# (전체 이름, 최소 약어)
_MODIFIER_PREFIXES = (("quietly", "qui"), ("noisily", "n"), ("capture", "cap"))

# 콜론으로 끝나는 접두 명령
_COLON_PREFIXES = (
    ("by", "by"),
    ("bysort", "bys"),
    ("xi", "xi"),
    ("sw", "sw"),
    ("stepwise", "stepwise"),
    ("bootstrap", "bootstrap"),
    ("bs", "bs"),
    ("jackknife", "jackknife"),
    ("jknife", "jknife"),
    ("simulate", "simulate"),
    ("statsby", "statsby"),
    ("rolling", "rolling"),
    ("permute", "permute"),
    ("nestreg", "nestreg"),
    ("svy", "svy"),
    ("mi", "mi"),
    ("fp", "fp"),
    ("mfp", "mfp"),
    ("version", "vers"),
    ("frame", "frame"),
    ("collect", "collect"),
    ("timer", "timer"),
)


def find_top_level_colon(text: str) -> int | None:
    """문자열·괄호 밖 첫 콜론 위치(``::`` 제외)."""
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if text.startswith('`"', i):
            end = text.find("\"'", i + 2)
            i = n if end == -1 else end + 2
            continue
        if c == '"':
            end = text.find('"', i + 1)
            i = n if end == -1 else end + 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif c == ":" and depth == 0:
            if text.startswith("::", i):
                i += 2
                continue
            return i
        i += 1
    return None


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def parse_command(text: str) -> ParsedCommand:
    """접두어를 제거하고 명령 이름·인자를 분리."""
    s = text.strip()
    prefixes: list[str] = []
    for _ in range(20):  # 비정상 입력 무한 반복 방지
        m = _WORD_RE.match(s)
        if not m:
            break
        word = m.group(0)
        lw = word.lower()
        if any(abbrev_match(lw, full, mn) for full, mn in _MODIFIER_PREFIXES):
            prefixes.append(lw)
            s = s[m.end():].lstrip()
            if s.startswith(":"):
                s = s[1:].lstrip()
            continue
        if lw == "else":
            prefixes.append(lw)
            s = s[m.end():].lstrip()
            continue
        if any(abbrev_match(lw, full, mn) for full, mn in _COLON_PREFIXES):
            idx = find_top_level_colon(s)
            if idx is not None:
                prefixes.append(s[:idx].strip())
                s = s[idx + 1:].lstrip()
                continue
        break

    if not s:
        return ParsedCommand("", "", tuple(prefixes), text)
    if s.startswith("!"):
        return ParsedCommand("!", s.lstrip("!").strip(), tuple(prefixes), text)
    if s[0] in "`$":
        return ParsedCommand("<macro>", s, tuple(prefixes), text)
    if s[0] in "{}":
        return ParsedCommand(s[0], s[1:].strip(), tuple(prefixes), text)
    m = re.match(r"#?[A-Za-z_][A-Za-z0-9_]*", s)
    if not m:
        return ParsedCommand(s.split()[0].lower(), s[len(s.split()[0]):].strip(), tuple(prefixes), text)
    name = m.group(0).lower()
    return ParsedCommand(name, s[m.end():].strip(), tuple(prefixes), text)


def strip_strings(text: str) -> str:
    """문자열 리터럴을 공백으로 치환(위치 유지)."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith('`"', i):
            end = text.find("\"'", i + 2)
            end = n if end == -1 else end + 2
            out.append(" " * (end - i))
            i = end
            continue
        if text[i] == '"':
            end = text.find('"', i + 1)
            end = n if end == -1 else end + 1
            out.append(" " * (end - i))
            i = end
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def split_first_token(args: str) -> tuple[str, str]:
    """인자 문자열에서 첫 토큰(따옴표 포함)과 나머지 분리."""
    s = args.lstrip()
    if not s:
        return "", ""
    if s.startswith('`"'):
        end = s.find("\"'")
        if end != -1:
            return s[: end + 2], s[end + 2:]
    if s.startswith('"'):
        end = s.find('"', 1)
        if end != -1:
            return s[: end + 1], s[end + 1:]
    m = re.match(r"[^\s,]+", s)
    if not m:
        return "", s
    return m.group(0), s[m.end():]


def unquote(token: str) -> str:
    t = token.strip()
    if t.startswith('`"') and t.endswith("\"'"):
        return t[2:-2]
    if len(t) >= 2 and t[0] == t[-1] == '"':
        return t[1:-1]
    return t
