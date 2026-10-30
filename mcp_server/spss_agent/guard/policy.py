"""SPSS 문법 실행 전 정적 검사(원자료 보호, Stata 설계서 §8을 SPSS에 적용).

문법 해석 기준 [일반 지식, IBM 원문 미열람 → 실기 검증 대상]
- 명령은 줄 끝 마침표 또는 빈 줄로 끝남, 이어지는 줄은 들여쓰기·'/'로 시작
- ``*``·``COMMENT``로 시작하는 명령은 주석, ``/* ... */``는 줄 안 주석
- 명령어는 앞 3글자 이상으로 줄여 쓸 수 있음(보수적으로 3글자 이상 접두어 모두 일치로 처리)
- ``BEGIN DATA``~``END DATA``(자료), ``BEGIN PROGRAM``~``END PROGRAM``(Python·R 코드) 블록

판정 등급·결과 객체는 Stata guard와 공유(Action·Finding·GuardResult).
guard는 사고 방지 장치이며 보안 경계가 아님.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from stata_agent.guard.command_policy import Action, Finding, GuardResult, _PathJudge
from stata_agent.guard.command_policy import default_file_reader as _plain_reader


def default_file_reader(path: str) -> str | None:
    """.sps는 BOM 포함 UTF-8로 저장되므로 BOM 제거 후 반환."""
    text = _plain_reader(path)
    return text.lstrip("\ufeff") if text is not None else None

_BEGIN_DATA = re.compile(r"^\s*BEGIN\s+DATA\b", re.IGNORECASE)
_END_DATA = re.compile(r"^\s*END\s+DATA\b", re.IGNORECASE)
_BEGIN_PROGRAM = re.compile(r"^\s*BEGIN\s+PROGRAM\b", re.IGNORECASE)
_END_PROGRAM = re.compile(r"^\s*END\s+PROGRAM\b", re.IGNORECASE)

# 이 명령으로 시작하는 1열 줄은 앞 명령의 마침표가 없어도 새 명령으로 봄(보수적 분리)
_DANGER_WORDS = ("LIST", "PRINT", "WRITE", "HOST", "ERASE", "SUMMARIZE", "REPORT", "OMSEND",
                 "SAVE", "EXPORT", "INSERT", "INCLUDE", "BEGIN")


def _abbrev(word: str, full: str, minimum: int = 3) -> bool:
    w, f = word.upper(), full.upper()
    return len(w) >= min(minimum, len(f)) and f.startswith(w)


def _strip_inline_comments(line: str) -> str:
    out, i, quote = [], 0, None
    while i < len(line):
        c = line[i]
        if quote:
            out.append(c)
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
            out.append(c)
            i += 1
            continue
        if line.startswith("/*", i):
            end = line.find("*/", i + 2)
            if end == -1:
                break
            out.append(" ")
            i = end + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _starts_danger(line: str) -> bool:
    if not line or line[0] in " \t/+-.":
        return False
    m = re.match(r"([A-Za-z]+)", line)
    return bool(m) and any(_abbrev(m.group(1), w) for w in _DANGER_WORDS)


def split_commands(code: str) -> list[tuple[int, str]]:
    """(시작 줄, 명령 문자열) 목록. 주석 명령도 포함(호출 측에서 제외)."""
    commands: list[tuple[int, str]] = []
    buf: list[str] = []
    start = 0
    mode: str | None = None

    def flush() -> None:
        nonlocal buf, mode
        text = " ".join(buf).strip()
        buf = []
        if text.endswith("."):
            text = text[:-1].rstrip()
        if not text:
            return
        commands.append((start, text))
        if _BEGIN_DATA.match(text):
            mode = "data"
        elif _BEGIN_PROGRAM.match(text):
            mode = "program"

    for lineno, raw in enumerate(code.lstrip("\ufeff").replace("\r\n", "\n").split("\n"), start=1):
        if mode == "data":
            if _END_DATA.match(raw):
                mode = None
            continue
        if mode == "program":
            if _END_PROGRAM.match(raw):
                mode = None
            continue
        line = _strip_inline_comments(raw)
        if not line.strip():
            flush()
            continue
        if buf and _starts_danger(line):
            flush()
        if not buf:
            start = lineno
        buf.append(line.strip())
        joined = " ".join(buf)
        if line.rstrip().endswith(".") or _BEGIN_DATA.match(joined) or _BEGIN_PROGRAM.match(joined):
            flush()
    flush()
    return commands


_OUTFILE_RE = re.compile(r"\b(?:OUTFILE|DOCUMENTFILE|FILE)\s*=\s*('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|[^\s/]+)", re.IGNORECASE)


def _targets(text: str, key: str = "OUTFILE") -> list[str]:
    pat = re.compile(rf"\b{key}\s*=\s*('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|[^\s/]+)", re.IGNORECASE)
    return [m.group(1) for m in pat.finditer(text)]


def _unquote(token: str) -> str:
    t = token.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        return t[1:-1].replace(t[0] * 2, t[0])
    return t


def _is_literal(token: str) -> bool:
    t = token.strip()
    return len(t) >= 2 and t[0] == t[-1] and t[0] in "'\""


_VAR_TOKEN = re.compile(r"^[A-Za-z@#$][\w.@#$]*$")


def _main_spec(args: str) -> str:
    return re.split(r"/", args, maxsplit=1)[0]


def _var_tokens(spec: str) -> list[str]:
    spec = re.sub(r"\[[^\]]*\]", " ", spec)  # CTABLES 범주·요약 지정
    spec = re.sub(r"\b(VARIABLES|TABLES|TABLE)\s*=", " ", spec, flags=re.IGNORECASE)
    tokens = []
    for t in re.split(r"[\s>+()=,]+", spec):
        if not t or t.upper() in {"BY", "WITH", "TABLE", "TABLES", "VARIABLES"}:
            continue
        if t.upper() in {"TO", "ALL"} or _VAR_TOKEN.match(t):
            tokens.append(t)
    return tokens


@dataclass
class SpssGuardContext:
    project_root: str
    data_dir_name: str = "data"
    read_file: Callable[[str], str | None] | None = default_file_reader
    max_include_depth: int = 5


class SpssGuard:
    def __init__(self, ctx: SpssGuardContext):
        self.ctx = ctx
        self.paths = _PathJudge(ctx.project_root, ctx.data_dir_name)

    def check_code(self, code: str, source: str | None = None, _depth: int = 0) -> GuardResult:
        result = GuardResult()
        for line, text in split_commands(code):
            self._check(line, text, result, source, _depth)
        seen: set[str] = set()
        result.identifier_vars = [v for v in result.identifier_vars if not (v in seen or seen.add(v))]
        return result

    def _check(self, line: int, text: str, result: GuardResult, source, depth) -> None:
        def add(rule: str, action: Action, msg: str) -> None:
            result.findings.append(Finding(line, text[:80], rule, action, msg, source))

        if text.startswith("*"):
            return
        m = re.match(r"([A-Za-z!$#@][\w.$#@]*)\s*(.*)$", text, re.DOTALL)
        if not m:
            return
        word, rest = m.group(1), m.group(2)
        second = (re.match(r"([A-Za-z]+)", rest) or [None, ""])[1] if rest else ""
        up, up2 = word.upper(), (second or "").upper()

        if _abbrev(up, "COMMENT"):
            return
        if up.startswith("!"):
            add("S12", Action.APPROVE, "매크로 호출 → 펼쳐진 명령을 정적으로 확인할 수 없음")
            return
        if up == "BEGIN" and _abbrev(up2, "PROGRAM"):
            add("S04", Action.BLOCK, "BEGIN PROGRAM(Python·R 코드 실행) 차단 — 자료 접근·임의 코드 실행 가능")
            return
        if up == "BEGIN" and _abbrev(up2, "DATA"):
            return
        if _abbrev(up, "LIST"):
            add("S01", Action.BLOCK, "LIST는 사례(행) 값을 출력함 → 요약통계로 대체")
            return
        if _abbrev(up, "PRINT"):
            if up2 and any(_abbrev(up2, w) for w in ("FORMATS", "SPACE", "EJECT")):
                return
            add("S01", Action.BLOCK, "PRINT는 사례별 값을 출력함")
            return
        if _abbrev(up, "WRITE"):
            if up2 and _abbrev(up2, "FORMATS"):
                return
            targets = _targets(rest)
            if not targets:
                add("S01", Action.BLOCK, "OUTFILE 없는 WRITE는 사례 값을 출력 창에 씀")
                return
            for t in targets:
                self._judge_write(t, add, data_export=True)
            return
        if _abbrev(up, "SUMMARIZE"):
            if re.search(r"/\s*FORMAT\s*=\s*NOLIST\b", rest, re.IGNORECASE):
                return
            add("S01", Action.BLOCK, "SUMMARIZE는 기본으로 사례 목록을 출력함 → /FORMAT=NOLIST 사용")
            return
        if _abbrev(up, "REPORT"):
            add("S01", Action.APPROVE, "REPORT는 사례 목록 보고서를 만들 수 있음")
            return
        if _abbrev(up, "HOST"):
            add("S05", Action.BLOCK, "운영체제 명령 실행 차단")
            return
        if _abbrev(up, "ERASE"):
            add("S06", Action.BLOCK, "파일 삭제 명령 차단")
            return
        if _abbrev(up, "PERMISSIONS"):
            add("S06", Action.APPROVE, "파일 권한 변경")
            return
        if up == "OMSEND":
            if not re.search(r"\bTAG\s*=", rest, re.IGNORECASE):
                add("S07", Action.BLOCK, "TAG 없는 OMSEND는 에이전트의 출력 수집까지 끝냄 → TAG 지정")
            return
        if up == "OMS":
            add("S07", Action.APPROVE, "사용자 OMS 요청은 출력 수집과 충돌할 수 있음")
            return
        if _abbrev(up, "MATRIX") and up2 != "DATA":
            add("S04", Action.APPROVE, "MATRIX 블록은 자료 행렬을 PRINT로 출력할 수 있음")
            return
        if up == "CD":
            add("S11", Action.APPROVE, "작업 폴더 변경 → 상대경로 판정이 무력화될 수 있음")
            return
        if _abbrev(up, "DEFINE"):
            add("S12", Action.WARN, "매크로 정의 → 호출 시 정적 확인 불가")
            return
        if _abbrev(up, "SAVE") and up2 and _abbrev(up2, "TRANSLATE"):
            for t in _targets(rest) or [""]:
                self._judge_write(t, add, data_export=True)
            return
        if _abbrev(up, "EXPORT"):
            for t in _targets(rest) or [""]:
                self._judge_write(t, add, data_export=True)
            return
        if _abbrev(up, "SAVE") or _abbrev(up, "XSAVE", 4):
            for t in _targets(rest) or [""]:
                self._judge_write(t, add, data_export=False)
            return
        if _abbrev(up, "OUTPUT") and up2 and (_abbrev(up2, "EXPORT") or _abbrev(up2, "SAVE")):
            for t in _targets(rest, "DOCUMENTFILE") + _targets(rest, "OUTFILE"):
                self._judge_write(t, add, data_export=False)
            return
        if _abbrev(up, "INSERT") or _abbrev(up, "INCLUDE"):
            self._follow_include(rest, add, result, source, depth)
            return
        if _abbrev(up, "FREQUENCIES") or _abbrev(up, "CROSSTABS") or _abbrev(up, "CTABLES"):
            tokens = _var_tokens(_main_spec(rest) if not rest.lstrip().startswith("/") else rest.lstrip()[1:].split("/", 1)[0])
            result.identifier_vars.extend(tokens or ["ALL"])
            add("S14", Action.WARN, f"빈도·교차표 → 식별자 성격 변수 여부를 실행 전 점검({' '.join(tokens[:6])})")
            return
        if _abbrev(up, "MEANS") or _abbrev(up, "EXAMINE"):
            spec = _main_spec(rest) if not rest.lstrip().startswith("/") else rest.lstrip()[1:].split("/", 1)[0]
            parts = re.split(r"\bBY\b", spec, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                tokens = _var_tokens(parts[1])
                result.identifier_vars.extend(tokens)
                add("S14", Action.WARN, f"집단별 요약 → 집단 변수의 식별자 성격 점검({' '.join(tokens[:6])})")
            if _abbrev(up, "EXAMINE") and re.search(r"\bEXTREME\b", rest, re.IGNORECASE):
                add("S01", Action.WARN, "EXAMINE EXTREME은 극단값 사례의 개별 값을 출력함")
            return

    def _judge_write(self, target: str, add, data_export: bool) -> None:
        rule = "S09" if data_export else "S10"
        if not target:
            add(rule, Action.APPROVE, "저장 경로를 정적으로 확인할 수 없음")
            return
        if not _is_literal(target):
            add(rule, Action.APPROVE, f"파일 핸들·매크로 경로({target}) → 정적 확인 불가")
            return
        where = self.paths.classify(_unquote(target))
        if where == "dynamic":
            add(rule, Action.APPROVE, f"경로에 매크로 사용({_unquote(target)})")
        elif where == "outside":
            add(rule, Action.BLOCK, f"프로젝트 폴더 밖으로 저장·반출 차단({_unquote(target)})")
        elif where == "data":
            add(rule, Action.BLOCK, f"원자료 폴더(data/) 쓰기 차단({_unquote(target)})")
        elif data_export:
            add(rule, Action.APPROVE, f"사례 단위 자료 내보내기({_unquote(target)}) → 연구자 확인 필요")

    def _follow_include(self, rest: str, add, result: GuardResult, source, depth) -> None:
        targets = _targets(rest, "FILE") or ([rest.split()[0]] if rest.split() and _is_literal(rest.split()[0]) else [])
        if not targets or not _is_literal(targets[0]):
            add("S15", Action.APPROVE, "INSERT/INCLUDE 대상을 정적으로 확인할 수 없음")
            return
        resolved = self.paths.resolve(_unquote(targets[0]))
        if resolved is None:
            add("S15", Action.APPROVE, "INSERT 경로에 매크로 사용")
            return
        if depth >= self.ctx.max_include_depth:
            add("S15", Action.APPROVE, "중첩 깊이 초과 → 하위 파일 미검사")
            return
        content = self.ctx.read_file(resolved) if self.ctx.read_file else None
        if content is None:
            add("S15", Action.APPROVE, f"호출 대상 파일을 읽을 수 없어 미검사({_unquote(targets[0])})")
            return
        inner = self.check_code(content, source=_unquote(targets[0]), _depth=depth + 1)
        result.findings.extend(inner.findings)
        result.identifier_vars.extend(inner.identifier_vars)


def check(code: str, project_root: str, read_file=default_file_reader) -> GuardResult:
    return SpssGuard(SpssGuardContext(project_root, read_file=read_file)).check_code(code)


__all__ = ["SpssGuard", "SpssGuardContext", "check", "split_commands"]
