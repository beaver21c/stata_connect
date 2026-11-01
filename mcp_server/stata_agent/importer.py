"""연구자가 쓰던 do-file을 이어 작업할 수 있게 준비(가져오기). SPSS판은 spss_agent.importer.

사용자 결정(2026-11-01): 원본은 같은 파일을 고치고 백업, 원래 내용은 주석 제목 기준으로 자동 분할.

처리
1. 인코딩 판별: UTF-8(BOM 포함) → 그대로, 아니면 cp949(한국어 Windows 기본) 시도 → UTF-8로 변환
   (Stata 14부터 do-file을 UTF-8로 다룸 [일반 지식], 지원 범위 17 이상)
2. 제목 탐지(가장 강한 형식 하나만 사용): Do-file Editor 책갈피 ``**#`` > 장식 제목(``* ---- 제목 ----``)·
   상자형(구분선-제목-구분선) > 번호 제목(``* 1. 자료``). 블록 주석·중괄호·program·mata·python·
   ``#delimit ;``·``///`` 이어 쓰기 안에서는 나누지 않음
3. 섹션 표지 ``*== [Sxx] 제목 ==*``는 주석 줄 → 연구자가 Stata에서 그대로 실행해도 영향 없음
4. 행 출력 명령(list·browse·edit)은 주석 처리하고 "연구자가 직접 실행할 줄"로 보고. 중괄호가 같은 줄에
   있거나 ``#delimit ;`` 구간이면 고치지 않고 수동 수정 대상으로 보고
5. 그 밖의 차단·승인 대상과 프로젝트 밖 읽기 경로는 고치지 않고 보고
"""

from __future__ import annotations

import locale
import re
from dataclasses import dataclass, field
from pathlib import Path

from .dofile import SECTION_RE, DoFile, Section, clean_title


# ── 인코딩 ───────────────────────────────────────────────────────

def decode_text(data: bytes) -> tuple[str, str]:
    """(문자열, 인코딩 이름). UTF-8 우선, 다음 cp949, 그다음 시스템 인코딩, 끝으로 latin-1."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    for enc in ("cp949", locale.getpreferredencoding(False) or ""):
        if not enc:
            continue
        try:
            return data.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1"), "latin-1"


def is_utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


# ── 제목 탐지(Stata) ─────────────────────────────────────────────

_DECOR_CHARS = "-=*#~_+"
_BOOKMARK_RE = re.compile(r"^\s*\*\*#+\s*(?P<title>\S.*?)\s*$")
_DIVIDER_RE = re.compile(r"^\s*(?:\*+|//+)?\s*[-=*#~_+]{5,}\s*$")
_DECORATED_RE = re.compile(r"^(?P<l>[-=*#~_+]{3,})\s*(?P<title>[^-=*#~_+\s].*?)\s*[-=*#~_+]*$")
_NUMBERED_RE = re.compile(r"^(?:\d+(?:\.\d+)*|[IVX]+|[가-하])[.)]\s+\S")
_PROGRAM_START = re.compile(r"^\s*(?:(?:capture|cap)\s+)?program\s+(?:define\s+|def\s+)?(?!drop\b|dir\b|list\b|l\b)\w", re.I)
_BLOCK_START = re.compile(r"^\s*(?:mata|python)\s*:?\s*$", re.I)
_BLOCK_END = re.compile(r"^\s*end\b", re.I)
_DELIMIT = re.compile(r"^\s*#d(?:elimit|elimi|elim|eli|el|e)?\s+(?P<mode>;|cr)\s*$", re.I)


def comment_text(line: str) -> str | None:
    """줄 전체가 주석이면 주석 내용, 아니면 None."""
    s = line.strip()
    if not s:
        return None
    if s.startswith("//"):
        return s[2:].strip()
    if s.startswith("*"):
        return s.lstrip("*").strip()
    m = re.fullmatch(r"/\*(.*?)\*/", s)
    if m:
        return m.group(1).strip()
    return None


def _code_part(line: str) -> str:
    """중괄호 셈용: 문자열·// 주석·줄 전체 * 주석 제거(대략)."""
    if comment_text(line) is not None:
        return ""
    s = re.sub(r'`"(?:[^"]|"(?!\'))*"\'|"[^"]*"', '""', line)
    s = re.sub(r"\s//.*$|^//.*$", "", s)
    s = re.sub(r"/\*.*?\*/", "", s)
    return s


def split_points(lines: list[str]) -> list[bool]:
    """각 줄 앞에서 섹션을 나눠도 되는지(블록·이어 쓰기 안이면 False)."""
    ok: list[bool] = []
    depth = 0
    in_block_comment = False
    in_program = False
    delimit_semicolon = False
    prev_continues = False
    for line in lines:
        ok.append(depth == 0 and not in_block_comment and not in_program
                  and not delimit_semicolon and not prev_continues)
        stripped = line.strip()
        m = _DELIMIT.match(line)
        if m:
            delimit_semicolon = m.group("mode") == ";"
        if in_program:
            if _BLOCK_END.match(line):
                in_program = False
        elif not in_block_comment and (_PROGRAM_START.match(line) or _BLOCK_START.match(line)):
            in_program = True
        # 블록 주석 열고 닫기(줄 전체 * 주석 안의 /* 는 무시)
        if not stripped.startswith("*") or in_block_comment:
            opens = len(re.findall(r"/\*", line))
            closes = len(re.findall(r"\*/", line))
            if in_block_comment:
                in_block_comment = closes < opens + 1
            else:
                in_block_comment = opens > closes
        if not in_block_comment:
            code = _code_part(line)
            depth = max(0, depth + code.count("{") - code.count("}"))
        prev_continues = bool(re.search(r"///\s*$", line)) and comment_text(line) is None
    return ok


@dataclass
class Heading:
    index: int        # 표지를 넣을 줄(0부터)
    title: str
    kind: str         # bookmark | decorated | box | numbered


def find_headings(lines: list[str]) -> list[Heading]:
    allowed = split_points(lines)
    found: dict[str, list[Heading]] = {"bookmark": [], "decorated": [], "numbered": []}
    skip_until = -1
    for i, line in enumerate(lines):
        if i <= skip_until or not allowed[i]:
            continue
        m = _BOOKMARK_RE.match(line)
        if m:
            found["bookmark"].append(Heading(i, m.group("title"), "bookmark"))
            continue
        # 상자형: 구분선 / 제목 주석 / 구분선
        if _DIVIDER_RE.match(line) and i + 2 < len(lines) and _DIVIDER_RE.match(lines[i + 2]):
            mid = comment_text(lines[i + 1])
            if mid and mid.strip(_DECOR_CHARS + " "):
                found["decorated"].append(Heading(i, mid.strip(_DECOR_CHARS + " "), "box"))
                skip_until = i + 2
                continue
        text = comment_text(line)
        if not text:
            continue
        m = _DECORATED_RE.match(text)
        if m and m.group("title").strip(_DECOR_CHARS + " "):
            found["decorated"].append(Heading(i, m.group("title").strip(_DECOR_CHARS + " "), "decorated"))
            continue
        if len(text) <= 60 and _NUMBERED_RE.match(text):
            found["numbered"].append(Heading(i, text, "numbered"))
    for kind in ("bookmark", "decorated", "numbered"):
        if found[kind]:
            return found[kind]
    return []


# ── 행 출력 명령 주석 처리 ────────────────────────────────────────

_ROW_CMD = re.compile(
    r"^\s*(?:(?:quietly|qui|capture|cap|noisily|noi)\s+)*(?:(?:by|bysort|bys)\b[^:]*:\s*)?"
    r"(?P<cmd>l|li|lis|list|br|bro|brow|brows|browse|ed|edi|edit)\b",
    re.IGNORECASE,
)
COMMENT_TAG = "* [stata-agent 가져오기: 원자료 보호로 주석 처리, 연구자가 Stata 창에서 직접 실행] "


@dataclass
class ImportReport:
    encoding: str
    converted: bool
    already_sectioned: bool
    sections: list[tuple[str, str, int]] = field(default_factory=list)  # (id, 제목, 원래 시작 줄)
    heading_kind: str | None = None
    commented: list[tuple[int, str]] = field(default_factory=list)       # (원래 줄, 원래 내용)
    manual: list[tuple[int, str]] = field(default_factory=list)          # 수동 수정 필요
    findings: list[str] = field(default_factory=list)                    # 그 밖의 차단·승인·경고
    outside_paths: list[tuple[int, str]] = field(default_factory=list)


def comment_out_rows(lines: list[str], finding_lines: list[int], tag: str = COMMENT_TAG
                     ) -> tuple[list[str], list[tuple[int, str]], list[tuple[int, str]]]:
    """guard가 행 출력(G01)으로 지목한 줄(1부터) 중 list·browse·edit를 주석 처리.

    줄 전체를 주석으로 바꾸므로, 같은 줄에 중괄호가 있거나(구조가 깨짐) ``#delimit ;`` 구간이거나
    앞줄 ``///``에 이어지는 줄이면 고치지 않고 수동 수정 대상으로 돌려줌.
    """
    out = list(lines)
    done: list[tuple[int, str]] = []
    manual: list[tuple[int, str]] = []
    in_semicolon = []
    mode = False
    for line in lines:
        in_semicolon.append(mode)
        m = _DELIMIT.match(line)
        if m:
            mode = m.group("mode") == ";"
    for ln in sorted(set(finding_lines)):
        i = ln - 1
        if not 0 <= i < len(lines):
            continue
        original = lines[i]
        if not _ROW_CMD.match(original):
            # 줄 중간(예: foreach ... { list ... })이거나 다른 행 출력 형태 → 자동으로 고치지 않음
            manual.append((ln, original.strip()))
            continue
        code = _code_part(original)
        continued = i > 0 and bool(re.search(r"///\s*$", lines[i - 1]))
        if "{" in code or "}" in code or in_semicolon[i] or continued:
            manual.append((ln, original.strip()))
            continue
        j = i
        while True:
            indent = re.match(r"^\s*", out[j]).group()
            out[j] = indent + tag + out[j].strip()
            if j + 1 < len(lines) and re.search(r"///\s*$", lines[j]):
                j += 1
                continue
            break
        done.append((ln, original.strip()))
    return out, done, manual


# ── 프로젝트 밖 읽기 경로 ────────────────────────────────────────

_READ_CMD = re.compile(
    r"^\s*(?:(?:quietly|qui|capture|cap|noisily|noi)\s+)*"
    r"(?P<cmd>use|u|import\s+\w+|merge|append|joinby|cross|do|run|include|cd|insheet|infile)\b(?P<rest>.*)$",
    re.IGNORECASE,
)
_TOKEN = re.compile(r'"([^"]*)"|\'([^\']*)\'|([^\s,"\']+)')
_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")


def outside_paths(lines: list[str], project_root: Path) -> list[tuple[int, str]]:
    root = str(Path(project_root).resolve()).replace("\\", "/").rstrip("/").lower()
    found = []
    for i, line in enumerate(lines, start=1):
        if comment_text(line) is not None:
            continue
        m = _READ_CMD.match(line)
        if not m:
            continue
        for tm in _TOKEN.finditer(m.group("rest")):
            token = next(g for g in tm.groups() if g is not None)
            if not _ABS.match(token):
                continue
            if not token.replace("\\", "/").lower().startswith(root):
                found.append((i, line.strip()))
                break
    return found


# ── 전체 변환(Stata) ─────────────────────────────────────────────

def build_imported_dofile(text: str, row_finding_lines: list[int]) -> tuple[str, list[tuple[str, str, int]], str | None,
                                                                            list[tuple[int, str]], list[tuple[int, str]]]:
    """(새 내용, 섹션 목록, 제목 형식, 주석 처리한 줄, 수동 수정 줄)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    lines, commented, manual = comment_out_rows(lines, row_finding_lines)
    if any(SECTION_RE.match(ln.strip()) for ln in lines):
        return "\n".join(lines) + "\n", [], None, commented, manual
    headings = find_headings(lines)
    kind = headings[0].kind if headings else None
    if kind == "box":
        kind = "decorated"
    starts = [h.index for h in headings]
    header: list[str] = []
    sections: list[Section] = []
    meta: list[tuple[str, str, int]] = []
    first = starts[0] if starts else len(lines)
    pre = lines[:first]
    has_code = any(comment_text(ln) is None and ln.strip() for ln in pre)
    if not headings:
        sections.append(Section("S01", "기존 작업", lines))
        meta.append(("S01", "기존 작업", 1))
    else:
        if has_code:
            sections.append(Section("S01", "시작 부분", pre))
            meta.append(("S01", "시작 부분", 1))
        else:
            header = pre
        bounds = starts + [len(lines)]
        for k, h in enumerate(headings):
            sid = f"S{len(sections) + 1:02d}"
            title = clean_title(h.title)
            sections.append(Section(sid, title, lines[bounds[k]:bounds[k + 1]]))
            meta.append((sid, title, h.index + 1))
    doc = DoFile(header, sections, [])
    return doc.render().lstrip("\n"), meta, kind, commented, manual
