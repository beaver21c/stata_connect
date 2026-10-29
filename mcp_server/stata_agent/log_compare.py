"""재현 검증(설계서 P5·§13.3): 대화형 로그 vs 배치 재실행 로그의 수치 비교.

비교 단위: 줄별 수치 토큰 순서열. 날짜·시각·경로가 들어간 줄과 로그 틀 줄은 제외
(예: describe의 자료 파일 날짜 1줄 차이 — 설계서 §2.1 1차 확인 사례).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUM_RE = re.compile(r"(?<![\w.])-?(?:\d+\.\d*|\.\d+|\d+)(?:e[+-]?\d+)?(?![\w])", re.IGNORECASE)
_SKIP_LINE_RE = re.compile(
    r"(\b\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}\b)"  # 29 Oct 2026
    r"|(\b\d{1,2}:\d{2}(:\d{2})?\b)"  # 10:00:00
    r"|(^\s*(name|log|log type|opened on|closed on)\s*:)"
    r"|([A-Za-z]:[\\/])|(/[^\s]+/[^\s]+)"  # 경로
    r"|(Revision\s)|(Serial number)|(Licensed to)|(memory)",
    re.IGNORECASE,
)


@dataclass
class LineDiff:
    line_a: int
    line_b: int
    a: list[str]
    b: list[str]


@dataclass
class CompareResult:
    equal: bool
    compared_lines: int
    diffs: list[LineDiff] = field(default_factory=list)
    note: str = ""

    @property
    def verdict(self) -> str:
        return "재현 일치" if self.equal else f"불일치 {len(self.diffs)}건"


def numeric_lines(text: str) -> list[tuple[int, list[str]]]:
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        if _SKIP_LINE_RE.search(line):
            continue
        nums = _NUM_RE.findall(line)
        if nums:
            out.append((i, nums))
    return out


def _close(a: str, b: str, rel_tol: float) -> bool:
    if a == b:
        return True
    try:
        x, y = float(a), float(b)
    except ValueError:
        return False
    return abs(x - y) <= rel_tol * max(abs(x), abs(y), 1e-12)


def compare_logs(a: str, b: str, rel_tol: float = 0.0, max_diffs: int = 20) -> CompareResult:
    la, lb = numeric_lines(a), numeric_lines(b)
    diffs: list[LineDiff] = []
    for (ia, na), (ib, nb) in zip(la, lb):
        if len(na) != len(nb) or not all(_close(x, y, rel_tol) for x, y in zip(na, nb)):
            diffs.append(LineDiff(ia, ib, na, nb))
    note = ""
    if len(la) != len(lb):
        note = f"수치 포함 줄 수 상이({len(la)} vs {len(lb)}) → 출력 구조 차이"
        diffs.append(LineDiff(-1, -1, [str(len(la))], [str(len(lb))]))
    return CompareResult(not diffs, min(len(la), len(lb)), diffs[:max_diffs], note)
