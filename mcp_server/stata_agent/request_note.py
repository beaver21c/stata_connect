"""연구자 요청 원문 기록(IMPLEMENTATION_STATUS §21) — do-file·.sps 섹션 첫머리에 연구자가 채팅창에 입력한 요청을
(일자 시각)과 함께 실행되지 않는 주석으로 남김. Stata·SPSS 공용.

배경(2026-11-02 사용자 요구): "채팅창에서 요청한 사항을 do파일로 기록하여 어떤 명령을 내렸는지 기록하도록 …
분석에 포함되지 않는 설명(주석)으로, 그 앞에 (일자, 시간)도"

형식
- Stata: ``/* ── 연구자 요청 (2026-11-02 23:41) ──`` / 원문 줄들 / ``*/`` — 원문의 ``*/``·``/*``는 띄어 써서 주석이 끝나거나
  겹치지 않게 함
- SPSS: ``* ── 연구자 요청 (2026-11-02 23:41) ──.`` / ``* │ 원문 줄.`` — SPSS 주석은 줄 끝 마침표까지라 줄마다 닫음
  (여러 줄 원문이 다음 명령을 주석으로 삼키지 않게) [논리적 추론: SPSS 주석 명령 규칙]
- 시각은 서버(연구자 PC)의 현재 시각. 원문은 AI가 그대로 넘기며(요약·번역 금지는 스킬 지침), 서버는 검증할 수 없음 [한계]
- 같은 섹션을 고칠 때 이전 요청 기록은 지우지 않고 새 요청을 아래에 쌓음(검토 이력)
- 사용 기록(history.jsonl)에는 원문을 남기지 않음(기록 여부만)
"""

from __future__ import annotations

from datetime import datetime

MAX_CHARS = 4000
_HEAD = "── 연구자 요청"
STATA_START = f"/* {_HEAD}"
SPSS_HEAD = f"* {_HEAD}"
SPSS_LINE = "* │ "


def _clean(text: str) -> list[str]:
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(t) > MAX_CHARS:
        t = t[:MAX_CHARS].rstrip() + " …(이하 생략)"
    return [ln.rstrip() for ln in t.split("\n")]


def stamp(when: datetime | None = None) -> str:
    return (when or datetime.now()).strftime("%Y-%m-%d %H:%M")


def stata_block(text: str, when: datetime | None = None) -> list[str]:
    body = [ln.replace("*/", "* /").replace("/*", "/ *") for ln in _clean(text)]
    return [f"{STATA_START} ({stamp(when)}) ──", *body, "*/"]


def spss_block(text: str, when: datetime | None = None) -> list[str]:
    out = [f"{SPSS_HEAD} ({stamp(when)}) ──."]
    for ln in _clean(text):
        s = ln.strip()
        if not s:
            continue
        out.append(f"{SPSS_LINE}{s}" + ("" if s.endswith(".") else "."))
    return out


def split_requests(lines: list[str], dialect: str) -> tuple[list[str], list[str]]:
    """(요청 기록 줄, 나머지 줄). 섹션 본문·새 코드 어디에 있든 요청 기록만 떼어 냄."""
    req: list[str] = []
    rest: list[str] = []
    in_block = False
    for ln in lines:
        s = ln.strip()
        if dialect == "stata":
            if in_block:
                req.append(ln)
                if s == "*/":
                    in_block = False
                continue
            if s.startswith(STATA_START):
                req.append(ln)
                in_block = s != "*/" and not s.endswith("*/")
                continue
        else:
            if s.startswith(SPSS_HEAD) or s.startswith(SPSS_LINE.strip()):
                req.append(ln)
                continue
        rest.append(ln)
    return req, rest


def _blocks(req_lines: list[str], dialect: str) -> list[tuple[str, ...]]:
    """요청 기록 줄 → 블록 단위(중복 제거용)."""
    head = STATA_START if dialect == "stata" else SPSS_HEAD
    blocks: list[list[str]] = []
    for ln in req_lines:
        if ln.strip().startswith(head) or not blocks:
            blocks.append([ln])
        else:
            blocks[-1].append(ln)
    return [tuple(b) for b in blocks]


def compose(old_body: list[str], new_code: str, request: str | None, dialect: str,
            when: datetime | None = None) -> tuple[list[str], str]:
    """(섹션 앞에 둘 요청 기록 줄 — 이전 기록 + 새 요청, 요청 기록을 뺀 새 코드)."""
    old_req, _ = split_requests(old_body, dialect)
    code_req, code_rest = split_requests(str(new_code or "").split("\n"), dialect)
    seen: list[tuple[str, ...]] = []
    for b in _blocks(old_req, dialect) + _blocks(code_req, dialect):
        if b not in seen:
            seen.append(b)
    lines = [ln for b in seen for ln in b]
    if request and request.strip():
        lines += stata_block(request, when) if dialect == "stata" else spss_block(request, when)
    return lines, "\n".join(code_rest)


__all__ = ["MAX_CHARS", "compose", "spss_block", "split_requests", "stamp", "stata_block"]
