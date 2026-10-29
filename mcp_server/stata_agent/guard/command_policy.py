"""명령 허용·차단 규칙(설계서 §8.1) — 실행 전 정적 검사.

판정 등급
- ALLOW   : 그대로 실행
- WARN    : 실행하되 경고 표시(예: 런타임 고유값 점검 대상)
- APPROVE : 연구자 확인 후 ``acknowledge_risks=true``로 재요청해야 실행
- BLOCK   : MCP 경유 실행 불가(필요하면 연구자가 Stata 창에서 직접 실행)

guard는 사고 방지 장치이며 완전한 보안 경계가 아님(설계서 §8.3).
"""

from __future__ import annotations

import ntpath
import posixpath
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Callable, Iterable

from .stata_lexer import (
    ParsedCommand,
    Statement,
    abbrev_match,
    iter_statements,
    parse_command,
    split_first_token,
    strip_strings,
    unquote,
)


class Action(IntEnum):
    ALLOW = 0
    WARN = 1
    APPROVE = 2
    BLOCK = 3


ACTION_LABEL = {
    Action.ALLOW: "허용",
    Action.WARN: "경고",
    Action.APPROVE: "승인 필요",
    Action.BLOCK: "차단",
}


@dataclass
class Finding:
    line: int
    command: str
    rule: str
    action: Action
    message: str
    source: str | None = None  # do/run/include로 따라간 파일

    def as_text(self) -> str:
        where = f"{self.source}:" if self.source else ""
        return f"[{ACTION_LABEL[self.action]}·{self.rule}] {where}{self.line}행 `{self.command}` — {self.message}"


@dataclass
class GuardResult:
    findings: list[Finding] = field(default_factory=list)
    identifier_vars: list[str] = field(default_factory=list)

    @property
    def action(self) -> Action:
        return max((f.action for f in self.findings), default=Action.ALLOW)

    @property
    def blocked(self) -> bool:
        return self.action >= Action.BLOCK

    @property
    def needs_approval(self) -> bool:
        return self.action == Action.APPROVE

    def summary(self) -> str:
        if not self.findings:
            return "guard: 문제 없음"
        lines = [f"guard 판정: {ACTION_LABEL[self.action]}"]
        lines += ["- " + f.as_text() for f in self.findings]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "action": ACTION_LABEL[self.action],
            "findings": [
                {
                    "line": f.line,
                    "command": f.command,
                    "rule": f.rule,
                    "action": ACTION_LABEL[f.action],
                    "message": f.message,
                    "source": f.source,
                }
                for f in self.findings
            ],
            "identifier_vars": self.identifier_vars,
        }


@dataclass
class GuardContext:
    project_root: str
    data_dir_name: str = "data"
    known_variables: frozenset[str] | None = None
    read_file: Callable[[str], str | None] | None = None  # do/run/include 재귀 검사용
    max_include_depth: int = 5


# ── 명령 표 ────────────────────────────────────────────────────
# (전체 이름, 최소 약어)
_ROW_OUTPUT = (("list", "l"), ("browse", "br"), ("edit", "ed"))
_ROW_OUTPUT_USER = {"listtab", "listtex", "extremes"}  # 관측치 행을 출력하는 SSC 명령(용도 기준 분류)
_SHELL = (("shell", "sh"), ("winexec", "winexec"), ("xshell", "xsh"))
_DESTRUCTIVE = (("erase", "erase"), ("rm", "rm"), ("rmdir", "rmdir"))
_FOREIGN_EXEC = (("python", "py"), ("javacall", "javacall"), ("java", "java"))
_EXPORT_DATA = (("outsheet", "outs"), ("outfile", "ou"))
_SAVE = (("save", "sa"), ("saveold", "saveold"))
_TAB_FAMILY = (
    ("tabulate", "ta"),
    ("tab1", "tab1"),
    ("tab2", "tab2"),
    ("table", "table"),
    ("tabdisp", "tabdisp"),
    ("levelsof", "levelsof"),
    ("codebook", "codebook"),
)
_DISPLAY = ("display", "di")
_TYPE = ("type", "ty")
_INCLUDE = (("do", "do"), ("run", "run"), ("include", "include"))
_INSTALL = {"ssc", "net", "ado"}

_MATA_DATA_FUNCS = re.compile(r"\b_?st_s?(data|view)\s*\(", re.IGNORECASE)
_MATA_STATA_CALL = re.compile(r"\bstata\s*\(\s*(\"[^\"]*\")?", re.IGNORECASE)

# display 안에서 무시할 지시어·키워드
_DISPLAY_KEYWORDS = {
    "as", "in", "text", "txt", "result", "res", "error", "err", "input", "inp",
    "smcl", "green", "yellow", "white", "red", "_n", "_newline", "_c", "_continue",
    "_col", "_column", "_skip", "_dup", "_char", "_request", "_asis", "_N",
    "_rc", "_pi", "_cons",
}
_SAFE_SUBSCRIPT = {"_b", "_se", "_coef"}
_SUBSCRIPT_RE = re.compile(r"(?<![\w`$])([A-Za-z_]\w*)\s*\[([^\]]*)\]")
_EVAL_MACRO_RE = re.compile(r"`=([^']*)'")
_ASSIGN = (("local", "loc"), ("global", "gl"), ("scalar", "sca"))
# display 식에서 변수 참조 검사 전에 지울 안전한 구성요소
_SAFE_EXPR_PARTS = re.compile(
    r"\b(?:_b|_se|_coef)\s*\[[^\]]*\]"          # 계수·표준오차
    r"|\b[rces]\(\s*[\w:]+\s*\)"                # r()·e()·c()·s() 저장결과
    r"|\bscalar\(\s*\w+\s*\)"                   # scalar(name)
    r"|\bel\([^)]*\)"                              # 행렬 원소 함수
    r"|\b\w+\s*\[[^\],]*,[^\]]*\]"             # 행렬 첨자 M[i,j]
)


def _matches(token: str, table: Iterable[tuple[str, str]]) -> bool:
    return any(abbrev_match(token, full, mn) for full, mn in table)


def _obs_subscripts(expr: str) -> list[str]:
    """관측치 첨자(var[1], var[_n-1] 등) 후보 목록. 쉼표 있는 행렬 첨자·_b/_se는 제외."""
    hits = []
    for m in _SUBSCRIPT_RE.finditer(expr):
        name, inside = m.group(1), m.group(2)
        if name in _SAFE_SUBSCRIPT or "," in inside:
            continue
        hits.append(m.group(0))
    return hits


def _strip_macros(text: str) -> str:
    text = re.sub(r"`[^'`]*'", " ", text)
    return re.sub(r"\$\{?\w+\}?", " ", text)


def _bare_variable_refs(expr: str, known: frozenset[str]) -> list[str]:
    """display 식 안의 변수 이름(약어 포함) 참조. 함수 호출·지시어·서식은 제외."""
    clean = _SAFE_EXPR_PARTS.sub(" ", _strip_macros(strip_strings(expr)))
    hits = []
    for m in re.finditer(r"(?<![\w.%])([A-Za-z_]\w*)\b(?!\s*\()", clean):
        tok = m.group(1)
        if tok in _DISPLAY_KEYWORDS or tok.lower() in _DISPLAY_KEYWORDS:
            continue
        if tok in known or any(v.startswith(tok) for v in known):
            hits.append(tok)
    return hits


class _PathJudge:
    def __init__(self, root: str, data_dir: str):
        self.windows = bool(re.match(r"^[A-Za-z]:[\\/]", root)) or "\\" in root
        self.mod = ntpath if self.windows else posixpath
        self.root = self._norm(root)
        self.data = self._norm(self.mod.join(root, data_dir))

    def _norm(self, p: str) -> str:
        p = self.mod.normpath(p)
        return p.lower() if self.windows else p

    def resolve(self, raw: str) -> str | None:
        """None이면 매크로 등으로 정적 해석 불가."""
        p = unquote(raw)
        if not p or "`" in p or "$" in p:
            return None
        if self.windows:
            p = p.replace("/", "\\")
        elif re.match(r"^([A-Za-z]:[\\/]|\\\\)", p):
            return self._norm(p.replace("\\", "/"))  # Unix형 프로젝트에서 Windows 절대경로 → 항상 밖
        if not self.mod.isabs(p):
            p = self.mod.join(self.root, p)
        return self._norm(p)

    def inside(self, resolved: str, base: str) -> bool:
        return resolved == base or resolved.startswith(base.rstrip(self.mod.sep) + self.mod.sep)

    def classify(self, raw: str) -> str:
        """'dynamic' | 'outside' | 'data' | 'inside'"""
        r = self.resolve(raw)
        if r is None:
            return "dynamic"
        if not self.inside(r, self.root):
            return "outside"
        if self.inside(r, self.data):
            return "data"
        return "inside"


def _using_target(args: str) -> str | None:
    m = re.search(r"\busing\s+(`\"[^']*\"'|\"[^\"]*\"|[^\s,]+)", args, re.IGNORECASE)
    return m.group(1) if m else None


def _tab_varlist(args: str) -> list[str]:
    s = strip_strings(args)
    s = re.split(r"\s(?:if|in|using)\s|,|\[", " " + s + " ", maxsplit=1)[0]
    s = s.replace("(", " ").replace(")", " ")
    tokens = [t for t in s.split() if re.fullmatch(r"[A-Za-z_*][\w*~?-]*", t)]
    return tokens or ["_all"]


class CommandGuard:
    """do-file·코드 조각 정적 검사기."""

    def __init__(self, ctx: GuardContext):
        self.ctx = ctx
        self.paths = _PathJudge(ctx.project_root, ctx.data_dir_name)

    # ── 공개 API ──
    def check_code(self, code: str, source: str | None = None, _depth: int = 0) -> GuardResult:
        result = GuardResult()
        python_block_reported = False
        for st in iter_statements(code):
            if st.context == "python":
                if not python_block_reported:
                    result.findings.append(Finding(
                        st.line, st.text[:60], "G05", Action.BLOCK,
                        "Python 실행(자료 접근·임의 코드 실행 가능) 차단", source))
                    python_block_reported = True
                continue
            if st.context == "mata":
                self._check_mata(st, result, source, _depth)
                continue
            python_block_reported = False
            self._check_stata(st, result, source, _depth)
        # 중복 제거(순서 유지)
        seen = set()
        result.identifier_vars = [v for v in result.identifier_vars if not (v in seen or seen.add(v))]
        return result

    # ── Mata ──
    def _check_mata(self, st: Statement, result: GuardResult, source, depth) -> None:
        if _MATA_DATA_FUNCS.search(st.text):
            result.findings.append(Finding(
                st.line, st.text[:60], "G04", Action.BLOCK,
                "Mata 자료 접근 함수(st_data·st_view 등) 차단 — 출력 경로를 정적으로 판별할 수 없음", source))
        for m in _MATA_STATA_CALL.finditer(st.text):
            literal = m.group(1)
            if literal is None:
                result.findings.append(Finding(
                    st.line, st.text[:60], "G04", Action.APPROVE,
                    "Mata stata() 호출 인자가 문자열 상수가 아님 → 정적 검사 불가", source))
            else:
                inner = self.check_code(unquote(literal), source, depth)
                for f in inner.findings:
                    f.line = st.line
                result.findings.extend(inner.findings)
                result.identifier_vars.extend(inner.identifier_vars)

    # ── Stata ──
    def _check_stata(self, st: Statement, result: GuardResult, source, depth) -> None:
        cmd = parse_command(st.text)
        name, args = cmd.name, cmd.args
        add = lambda rule, action, msg: result.findings.append(  # noqa: E731
            Finding(st.line, st.text[:80], rule, action, msg, source))

        if not name or name in "{}":
            return

        # 모든 문장 공통: `=식' 매크로 평가에 관측치 첨자
        for expr in _EVAL_MACRO_RE.findall(st.text):
            if _obs_subscripts(expr):
                if abbrev_match(name, *_DISPLAY):
                    add("G02", Action.BLOCK, "매크로 평가식으로 관측치 값을 출력")
                else:
                    add("G03", Action.APPROVE, "매크로 평가식으로 관측치 값을 추출")

        if name == "<macro>":
            add("G12", Action.APPROVE, "매크로로 시작하는 동적 명령 → 정적 검사 불가")
            return
        if name == "!" or _matches(name, _SHELL):
            add("G05", Action.BLOCK, "운영체제 명령 실행 차단")
            return
        if _matches(name, _FOREIGN_EXEC):
            add("G05", Action.BLOCK, "외부 언어 실행(Python·Java) 차단")
            return
        if _matches(name, _DESTRUCTIVE):
            add("G06", Action.BLOCK, "파일 삭제 명령 차단")
            return
        if _matches(name, _ROW_OUTPUT) or name in _ROW_OUTPUT_USER:
            add("G01", Action.BLOCK, "관측치 행 단위 출력·열람 차단(원자료 비전송 원칙 P2)")
            return
        if name == "duplicates":
            sub = args.split()[0].lower() if args.split() else ""
            if abbrev_match(sub, "list", "l") or abbrev_match(sub, "examples", "e"):
                add("G01", Action.BLOCK, "duplicates list/examples는 관측치 행을 출력함")
            return
        if abbrev_match(name, *_TYPE):
            add("G01", Action.BLOCK, "type은 파일 내용을 그대로 출력함(자료 파일 노출 위험) → 로그는 stata_read_log 사용")
            return
        if abbrev_match(name, *_DISPLAY):
            subs = _obs_subscripts(_strip_macros(strip_strings(args)))
            if subs:
                add("G02", Action.BLOCK, f"display로 관측치 값 출력({', '.join(subs[:3])})")
                return
            if self.ctx.known_variables:
                refs = _bare_variable_refs(args, self.ctx.known_variables)
                if refs:
                    add("G02", Action.BLOCK,
                        f"display에 변수 이름 사용({', '.join(refs[:3])}) → 첫 관측치 값이 출력됨")
            return
        if _matches(name, _ASSIGN):
            rhs = args.split("=", 1)[1] if "=" in args else ""
            if rhs and _obs_subscripts(_strip_macros(strip_strings(rhs))):
                add("G03", Action.APPROVE, "관측치 값을 매크로·스칼라로 추출")
            return
        if name == "log":
            if re.match(r"^close\s+_all\b", args, re.IGNORECASE):
                add("G07", Action.BLOCK,
                    "log close _all은 MCP 실행 로그까지 닫음 → `capture log close _nmlog`처럼 이름 지정")
            return
        if name == "exit":
            if re.search(r",.*\bstata\b", args, re.IGNORECASE):
                add("G08", Action.BLOCK, "Stata 종료 명령 차단(세션 소실)")
            return
        if name == "cd":
            add("G11", Action.APPROVE, "작업 폴더 변경 → 상대경로 판정이 무력화될 수 있음")
            return
        if name in _INSTALL:
            sub = args.split()[0].lower() if args.split() else ""
            if sub in {"install", "inst", "get", "update", "uninstall"}:
                add("G13", Action.APPROVE, "패키지 설치·변경은 stata_install_package 도구 사용 권장")
            return
        if name == "export":
            target = _using_target(args)
            if target is None:
                parts = args.split(None, 1)
                target = split_first_token(parts[1])[0] if len(parts) > 1 else ""
            self._judge_write(target, add, data_export=True)
            return
        if _matches(name, _EXPORT_DATA):
            self._judge_write(_using_target(args) or "", add, data_export=True)
            return
        if _matches(name, _SAVE):
            target, _ = split_first_token(args)
            if not target:
                add("G10", Action.APPROVE, "파일명 없는 save → 불러온 원본 자료를 덮어쓸 수 있음")
                return
            self._judge_write(target, add, data_export=False)
            return
        if name == "copy":
            first, rest = split_first_token(args)
            second, _ = split_first_token(rest)
            self._judge_write(second, add, data_export=False)
            return
        if name == "file":
            if re.match(r"^open\b", args, re.IGNORECASE) and re.search(r",.*\b(write|w|append|a)\b", args, re.IGNORECASE):
                self._judge_write(_using_target(args) or "", add, data_export=False)
            return
        if name == "putexcel":
            if re.match(r"^set\b", args, re.IGNORECASE):
                target, _ = split_first_token(args[3:])
                self._judge_write(target, add, data_export=False)
            return
        if _matches(name, _INCLUDE):
            self._follow_include(args, st, result, source, depth, add)
            return
        if _matches(name, _TAB_FAMILY):
            vars_ = _tab_varlist(args)
            result.identifier_vars.extend(vars_)
            add("G14", Action.WARN, f"빈도·고유값 출력 명령 → 식별자 성격 변수 여부를 실행 전 점검({', '.join(vars_[:5])})")
            return

    def _judge_write(self, target: str, add, data_export: bool) -> None:
        if not target:
            add("G09" if data_export else "G10", Action.APPROVE, "저장 경로를 정적으로 확인할 수 없음")
            return
        where = self.paths.classify(target)
        rule = "G09" if data_export else "G10"
        if where == "dynamic":
            add(rule, Action.APPROVE, f"저장 경로에 매크로 사용({unquote(target)}) → 정적 확인 불가")
        elif where == "outside":
            add(rule, Action.BLOCK, f"프로젝트 폴더 밖으로 저장·반출 차단({unquote(target)})")
        elif where == "data":
            add(rule, Action.BLOCK, f"원자료 폴더(data/) 쓰기 차단 — 원자료는 읽기 전용({unquote(target)})")
        elif data_export:
            add(rule, Action.APPROVE, f"관측치 단위 자료 내보내기({unquote(target)}) → 연구자 확인 필요")

    def _follow_include(self, args, st, result, source, depth, add) -> None:
        target, _ = split_first_token(args)
        if not target:
            add("G15", Action.APPROVE, "do/run/include 대상 없음")
            return
        resolved = self.paths.resolve(target)
        if resolved is None:
            add("G15", Action.APPROVE, "do/run/include 경로에 매크로 사용 → 정적 검사 불가")
            return
        if depth >= self.ctx.max_include_depth:
            add("G15", Action.APPROVE, "do-file 중첩 깊이 초과 → 하위 파일 미검사")
            return
        reader = self.ctx.read_file
        content = None
        if reader is not None:
            content = reader(resolved)
            if content is None and not resolved.lower().endswith((".do", ".ado", ".doh")):
                content = reader(resolved + ".do")
        if content is None:
            add("G15", Action.APPROVE, f"호출 대상 파일을 읽을 수 없어 미검사({unquote(target)})")
            return
        inner = self.check_code(content, source=unquote(target), _depth=depth + 1)
        result.findings.extend(inner.findings)
        result.identifier_vars.extend(inner.identifier_vars)


def default_file_reader(path: str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def check(code: str, project_root: str, known_variables: Iterable[str] | None = None,
          read_file: Callable[[str], str | None] | None = default_file_reader) -> GuardResult:
    """간편 호출."""
    ctx = GuardContext(
        project_root=project_root,
        known_variables=frozenset(known_variables) if known_variables else None,
        read_file=read_file,
    )
    return CommandGuard(ctx).check_code(code)


__all__ = [
    "Action",
    "ACTION_LABEL",
    "CommandGuard",
    "Finding",
    "GuardContext",
    "GuardResult",
    "ParsedCommand",
    "check",
    "default_file_reader",
]
