"""연구자가 쓰던 SPSS 문법 파일(.sps) 가져오기 — Stata판(stata_agent.importer)과 같은 원칙.

SPSS 문법 특성
- 주석은 명령 단위: 줄 첫머리 ``*`` 또는 ``COMMENT``로 시작해 줄 끝 마침표까지 → 제목 후보는 명령이
  시작하는 줄이면서 한 줄로 끝나는 주석
- 블록(DO IF·LOOP·DO REPEAT·INPUT PROGRAM·MATRIX·FILE TYPE·DEFINE) 안에서는 나누지 않음.
  BEGIN DATA·BEGIN PROGRAM 구간은 명령 분리기(split_commands)가 건너뜀
- 행 출력 명령(S01: LIST·PRINT·WRITE·SUMMARIZE 목록형)은 첫 줄 앞에 ``*``를 붙여 명령 전체를 주석으로 바꿈
  (SPSS 주석 명령은 줄 끝 마침표까지 이어짐). 마침표로 끝나지 않는 명령이면 뒤 명령까지 주석이 되므로
  손대지 않고 수동 수정 대상으로 보고
- 22·23 등 코드페이지 모드에서 저장한 cp949 파일은 UTF-8(BOM 포함, 이 저장소의 .sps 규약)로 변환
"""

from __future__ import annotations

import re
from pathlib import Path

from stata_agent.dofile import clean_title
from stata_agent.importer import _ABS, _TOKEN

from .guard.policy import split_commands
from .syntaxfile import SECTION_RE, Section, SyntaxFile

COMMENT_TAG = "* [spss-agent 가져오기: 원자료 보호로 주석 처리, 연구자가 SPSS에서 직접 실행] "
_DECOR = "-=*#~_+"
_OPEN = re.compile(r"^(DO\s+IF|LOOP|DO\s+REPEAT|INPUT\s+PROGRAM|MATRIX|FILE\s+TYPE|DEFINE)\b", re.I)
_CLOSE = re.compile(r"^(END\s+IF|END\s+LOOP|END\s+REPEAT|END\s+INPUT\s+PROGRAM|END\s+MATRIX|END\s+FILE\s+TYPE"
                    r"|!ENDDEFINE)\b", re.I)
_DIVIDER = re.compile(r"^\*+\s*[-=*#~_+]{4,}\s*\.?\s*$")
_DECORATED = re.compile(r"^(?P<l>[-=*#~_+]{3,})\s*(?P<title>[^-=*#~_+\s].*?)\s*[-=*#~_+]*$")
_NUMBERED = re.compile(r"^(?:\d+(?:\.\d+)*|[IVX]+|[가-하])[.)]\s+\S")


def _comment_body(line: str) -> str | None:
    """한 줄로 끝나는 주석 명령이면 내용(끝 마침표 제외), 아니면 None."""
    s = line.strip()
    if not s.endswith("."):
        return None
    if s.startswith("*"):
        return s.lstrip("*").rstrip(".").strip()
    m = re.match(r"^COMMENT\s+(.*)\.$", s, re.I)
    return m.group(1).strip() if m else None


def _commands_with_depth(lines: list[str]) -> list[tuple[int, str, int]]:
    """(시작 줄 1부터, 명령 문자열, 그 명령 앞의 블록 깊이)."""
    out = []
    depth = 0
    for start, text in split_commands("\n".join(lines)):
        if _CLOSE.match(text.lstrip()):
            depth = max(0, depth - 1)
        out.append((start, text, depth))
        if _OPEN.match(text.lstrip()):
            depth += 1
    return out


def find_headings(lines: list[str]) -> list[tuple[int, str, str]]:
    """(표지를 넣을 줄 0부터, 제목, 형식). 장식·상자형 > 번호 제목."""
    cmds = _commands_with_depth(lines)
    starts = {start - 1: depth for start, _, depth in cmds}
    decorated: list[tuple[int, str, str]] = []
    numbered: list[tuple[int, str, str]] = []
    skip = -1
    for i in sorted(starts):
        if i <= skip or starts[i] != 0:
            continue
        line = lines[i]
        if _DIVIDER.match(line.strip()) and i + 2 < len(lines) and _DIVIDER.match(lines[i + 2].strip()):
            mid = _comment_body(lines[i + 1])
            if mid and mid.strip(_DECOR + " "):
                decorated.append((i, mid.strip(_DECOR + " "), "decorated"))
                skip = i + 2
                continue
        body = _comment_body(line)
        if not body:
            continue
        m = _DECORATED.match(body)
        if m and m.group("title").strip(_DECOR + " "):
            decorated.append((i, m.group("title").strip(_DECOR + " "), "decorated"))
        elif len(body) <= 60 and _NUMBERED.match(body):
            numbered.append((i, body, "numbered"))
    return decorated or numbered


def _command_end(lines: list[str], start: int) -> int | None:
    """start(0부터) 명령의 마지막 줄(마침표로 끝나는 줄). 빈 줄로 끝나면 None."""
    for j in range(start, len(lines)):
        s = lines[j].strip()
        if not s:
            return None
        if s.endswith("."):
            return j
    return None


def comment_out_rows(lines: list[str], finding_lines: list[int]) -> tuple[list[str], list, list]:
    out = list(lines)
    done, manual = [], []
    for ln in sorted(set(finding_lines)):
        i = ln - 1
        if not 0 <= i < len(lines):
            continue
        original = lines[i].strip()
        end = _command_end(lines, i)
        if end is None or not re.match(r"^(LIS|LIST|PRI|PRIN|PRINT|WRI|WRIT|WRITE|SUM|SUMM|SUMMA|SUMMAR|SUMMARI"
                                      r"|SUMMARIZ|SUMMARIZE)\b", original, re.I):
            manual.append((ln, original))
            continue
        out[i] = COMMENT_TAG + lines[i].lstrip()
        done.append((ln, original))
    return out, done, manual


_READ_CMD = re.compile(r"^\s*(GET|INSERT|INCLUDE|CD|DATA\s+LIST|MATCH\s+FILES|ADD\s+FILES|IMPORT)\b(?P<rest>.*)$", re.I)


def outside_paths(lines: list[str], project_root: Path) -> list[tuple[int, str]]:
    root = str(Path(project_root).resolve()).replace("\\", "/").rstrip("/").lower()
    found = []
    for i, line in enumerate(lines, start=1):
        m = _READ_CMD.match(line)
        if not m:
            continue
        for tm in _TOKEN.finditer(m.group("rest").replace("=", " ")):
            token = next(g for g in tm.groups() if g is not None)
            if _ABS.match(token) and not token.replace("\\", "/").lower().startswith(root):
                found.append((i, line.strip()))
                break
    return found


def build_imported_syntax(text: str, row_finding_lines: list[int]):
    """(새 내용, 섹션 목록, 제목 형식, 주석 처리한 줄, 수동 수정 줄)."""
    lines = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    lines, commented, manual = comment_out_rows(lines, row_finding_lines)
    if any(SECTION_RE.match(ln.strip()) for ln in lines):
        return "\n".join(lines) + "\n", [], None, commented, manual
    headings = find_headings(lines)
    kind = headings[0][2] if headings else None
    header: list[str] = []
    sections: list[Section] = []
    meta: list[tuple[str, str, int]] = []
    starts = [h[0] for h in headings]
    pre = lines[: starts[0]] if starts else lines
    has_code = any(ln.strip() and _comment_body(ln) is None for ln in pre)
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
        for k, (idx, title, _) in enumerate(headings):
            sid = f"S{len(sections) + 1:02d}"
            t = clean_title(title).rstrip(".")
            sections.append(Section(sid, t, lines[bounds[k]:bounds[k + 1]]))
            meta.append((sid, t, idx + 1))
    return SyntaxFile(header, sections).render().lstrip("\n"), meta, kind, commented, manual
