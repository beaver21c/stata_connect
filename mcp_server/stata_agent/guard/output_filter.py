"""출력 필터(설계서 §8.2) — 로그를 AI에게 반환하기 직전 적용.

처리 순서
1. MCP 실행 틀(log using·cd·do 임시파일 등) 줄 제거
2. 명령 블록 단위 분할(``. 명령`` 에코 기준)
3. 블록별 판정
   - 행 출력 명령(list 등)의 결과 → 전체 차단
   - list 형식 행(``  1. | ... |``) 탐지 → 전체 차단
   - 빈도표에서 빈도 1인 행 비율이 높음(식별자 성격) → 전체 차단
   - (선택) 빈도표 소표본 셀 마스킹: 정수 빈도 < k → ``<k``
4. 길이 제한(앞부분+뒷부분 보존)

차단 시 AI에는 "차단됨 + 사유"만 반환하고 원 로그는 PC에만 보존함.
판정 기준(행 수·비율)은 논리적 추론에 따른 기본값이며 설정으로 조정 가능.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .stata_lexer import abbrev_match, parse_command

_FRAME_PREFIXES = (
    "capture log close __stata_mcp",
    "log using ",
    "log close",
    "capture log close",
)
_FRAME_FIELD_RE = re.compile(r"^\s*(name|log|log type|opened on|closed on|Log type)\s*:", re.IGNORECASE)
_LIST_ROW_RE = re.compile(r"^\s*\d+\.\s*\|")
_COMMAND_ECHO_RE = re.compile(r"^(?:\s*\d+\.)?\s?\.\s(.*)$|^\.\s(.*)$")
_TAB_ROW_RE = re.compile(r"^\s*(?P<label>.+?)\s*\|\s+(?P<freq>[\d,]+)\s+(?P<pct>[\d.]+)\s+(?P<cum>[\d.]+)\s*$")
_INT_TOKEN_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})*|\d+)(?![\d.,]*\d)(?!\.\d)")

_ROW_COMMANDS = (("list", "l"), ("browse", "br"), ("edit", "ed"))
_ROW_COMMANDS_USER = {"listtab", "listtex", "extremes"}
_TAB_COMMANDS = (("tabulate", "ta"), ("tab1", "tab1"), ("tab2", "tab2"), ("table", "table"), ("tabdisp", "tabdisp"))


@dataclass
class FilterConfig:
    list_row_threshold: int = 1  # list 형식 행이 이 수 이상이면 블록 차단
    singleton_min_rows: int = 10  # 빈도표 판정 최소 행 수
    singleton_ratio: float = 0.5  # 빈도 1인 행 비율 기준
    mask_small_cells: int = 0  # 0이면 끔. k>0이면 빈도표 정수 1..k-1을 '<k'로 치환
    max_chars: int = 20_000


@dataclass
class FilterEvent:
    command: str
    reason: str


@dataclass
class FilterResult:
    text: str
    events: list[FilterEvent] = field(default_factory=list)
    truncated: bool = False
    masked_cells: int = 0

    @property
    def blocked_any(self) -> bool:
        return bool(self.events)


@dataclass
class _Block:
    command: str | None
    lines: list[str]


def clean_frame_lines(text: str, extra_markers: tuple[str, ...] = ()) -> str:
    """MCP·로그 틀 줄 제거."""
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        body = stripped[2:] if stripped.startswith(". ") else stripped
        low = body.lower()
        if not stripped:
            kept.append(line)
            continue
        if any(low.startswith(p) for p in _FRAME_PREFIXES):
            continue
        if _FRAME_FIELD_RE.match(stripped):
            continue
        if re.match(r'^(cd|do)\s+"[^"]*(\.stata-mcp|\.stata-agent|selection_)[^"]*"', body, re.IGNORECASE):
            continue
        if any(m in stripped for m in extra_markers):
            continue
        if low in ("end of do-file", "r(0);"):
            continue
        kept.append(line)
    # 연속 빈 줄 축소
    out: list[str] = []
    for line in kept:
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    return "\n".join(out).strip("\n")


def _split_blocks(text: str) -> list[_Block]:
    blocks: list[_Block] = [_Block(None, [])]
    for line in text.splitlines():
        m = _COMMAND_ECHO_RE.match(line)
        if m and not _LIST_ROW_RE.match(line):
            cmd = (m.group(1) or m.group(2) or "").strip()
            blocks.append(_Block(cmd, [line]))
            continue
        if line.startswith("> ") and blocks[-1].command is not None and len(blocks[-1].lines) == 1:
            blocks[-1].command += " " + line[2:].strip()  # 줄 연결 에코
            blocks[-1].lines.append(line)
            continue
        blocks[-1].lines.append(line)
    return [b for b in blocks if b.lines]


def _is_row_command(cmd: str | None) -> bool:
    if not cmd:
        return False
    pc = parse_command(cmd)
    return any(abbrev_match(pc.name, f, m) for f, m in _ROW_COMMANDS) or pc.name in _ROW_COMMANDS_USER


def _is_tab_command(cmd: str | None) -> bool:
    if not cmd:
        return False
    pc = parse_command(cmd)
    return any(abbrev_match(pc.name, f, m) for f, m in _TAB_COMMANDS)


def _singleton_table(lines: list[str], cfg: FilterConfig) -> bool:
    rows = []
    for line in lines:
        m = _TAB_ROW_RE.match(line)
        if m and m.group("label").strip().lower() != "total":
            rows.append(int(m.group("freq").replace(",", "")))
    if len(rows) < cfg.singleton_min_rows:
        return False
    return sum(1 for r in rows if r == 1) / len(rows) >= cfg.singleton_ratio


def _mask_line(line: str, k: int) -> tuple[str, int]:
    if "|" not in line:
        return line, 0
    head, sep, tail = line.partition("|")
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        value = int(m.group(1).replace(",", ""))
        if 0 < value < k:
            count += 1
            token = f"<{k}"
            return token.rjust(len(m.group(1)))
        return m.group(1)

    return head + sep + _INT_TOKEN_RE.sub(repl, tail), count


def filter_output(text: str, cfg: FilterConfig | None = None, log_path: str | None = None) -> FilterResult:
    cfg = cfg or FilterConfig()
    cleaned = clean_frame_lines(text)
    result = FilterResult(text="")
    out_lines: list[str] = []
    where = f" (원 로그는 PC에만 보존: {log_path})" if log_path else " (원 로그는 PC에만 보존)"

    for block in _split_blocks(cleaned):
        body = block.lines[1:] if block.command is not None else block.lines
        reason = None
        if _is_row_command(block.command):
            reason = "행 단위 출력 명령 결과"
        elif sum(1 for ln in body if _LIST_ROW_RE.match(ln)) >= cfg.list_row_threshold:
            reason = "관측치 목록 형식 출력 탐지"
        elif _is_tab_command(block.command) and _singleton_table(body, cfg):
            reason = "빈도 1인 범주가 대부분인 빈도표(식별자 성격 변수 의심)"

        if reason:
            result.events.append(FilterEvent(block.command or "(명령 미상)", reason))
            if block.command is not None:
                out_lines.append(block.lines[0])
            out_lines.append(f"[차단됨: {reason}]{where}")
            continue

        if cfg.mask_small_cells > 1 and _is_tab_command(block.command):
            masked_body = []
            seen_separator = False  # 머리글(열 범주값) 줄은 마스킹 제외 → 첫 구분선 이후만
            for ln in body:
                if re.match(r"^\s*-+\+[-+]*\s*$", ln):
                    seen_separator = True
                    masked_body.append(ln)
                    continue
                if not seen_separator:
                    masked_body.append(ln)
                    continue
                new, c = _mask_line(ln, cfg.mask_small_cells)
                result.masked_cells += c
                masked_body.append(new)
            body = masked_body
        if block.command is not None:
            out_lines.append(block.lines[0])
        out_lines.extend(body)

    text_out = "\n".join(out_lines).strip("\n")
    if result.masked_cells:
        text_out += f"\n[안내] 빈도 {cfg.mask_small_cells} 미만 셀 {result.masked_cells}개 마스킹"
    if len(text_out) > cfg.max_chars:
        half = cfg.max_chars // 2
        text_out = (
            text_out[:half]
            + f"\n\n[중략: 출력 {len(text_out):,}자 중 앞 {half:,}자·뒤 {half:,}자만 반환. 전체는 로그 파일 참조]\n\n"
            + text_out[-half:]
        )
        result.truncated = True
    result.text = text_out
    return result


def extract_markers(text: str, prefix: str) -> list[list[str]]:
    """``display "PREFIX|a|b"`` 형태 표지 줄을 필드 목록으로 추출(명령 에코 줄 제외)."""
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(". ") or s.startswith(">"):
            continue
        if s.startswith(prefix + "|"):
            rows.append([p.strip() for p in s.split("|")[1:]])
    return rows


def last_return_code(text: str) -> int:
    codes = re.findall(r"^r\((\d+)\);\s*$", text, re.MULTILINE)
    return int(codes[-1]) if codes else 0
