"""SPSS 출력(OMS TEXT) 필터 — AI 반환 직전 적용.

OMS TEXT 출력의 정확한 형식은 실기 미확인 [미확인] → 표 제목·빈도표 행 형태에 대한 일반적 판정만 수행.
주 방어선은 실행 전 guard(LIST·PRINT·SUMMARIZE 차단)이며, 이 필터는 보조 장치.

- 사례 목록형 표(Case Summaries·List·Report 등 제목) 블록 차단
- 빈도 1인 범주가 대부분인 빈도표 블록 차단(식별자 성격 변수 의심)
- 길이 제한(앞·뒤 보존)
"""

from __future__ import annotations

import re

from stata_agent.guard.output_filter import FilterConfig, FilterEvent, FilterResult

# 표 제목 줄 전체가 아래 중 하나일 때(각주 표지 "(a)" 허용). "Case Processing Summary"는 해당 없음
_LISTING_TITLES = re.compile(r"^\s*(Case Summaries|List|Report|케이스 요약|사례 요약)\s*(\([a-z]\))?\s*$", re.IGNORECASE)
_FREQ_HEADER = re.compile(r"(Frequency|빈도).*(Percent|퍼센트|백분율)", re.IGNORECASE)
_ROW_NUMS = re.compile(r"(?<![\w.])(\d[\d,]*)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)(?:\s+(\d+(?:\.\d+)?))?\s*\|?\s*$")


def _blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = [[]]
    for line in text.splitlines():
        if not line.strip():
            if blocks[-1]:
                blocks.append([])
            continue
        blocks[-1].append(line)
    return [b for b in blocks if b]


def _singleton_freq_table(block: list[str], cfg: FilterConfig) -> bool:
    if not any(_FREQ_HEADER.search(ln) for ln in block):
        return False
    freqs = []
    for ln in block:
        if re.search(r"\b(Total|합계|전체|Missing|결측|System)\b", ln, re.IGNORECASE):
            continue
        m = _ROW_NUMS.search(ln)
        if m:
            freqs.append(int(m.group(1).replace(",", "")))
    if len(freqs) < cfg.singleton_min_rows:
        return False
    return sum(1 for f in freqs if f == 1) / len(freqs) >= cfg.singleton_ratio


def filter_output(text: str, cfg: FilterConfig | None = None, out_path: str | None = None) -> FilterResult:
    cfg = cfg or FilterConfig()
    result = FilterResult(text="")
    where = f" (원 출력은 PC에만 보존: {out_path})" if out_path else " (원 출력은 PC에만 보존)"
    out: list[str] = []
    carry: str | None = None  # 제목만 있는 블록 다음 블록(표 본문)도 차단
    for block in _blocks(text.replace("\r\n", "\n")):
        title = block[0].strip()
        reason = None
        if carry:
            reason, carry = carry, None
        elif _LISTING_TITLES.match(title):
            if len(block) == 1:
                carry = f"사례 목록형 표({title[:40]}) 본문"
            reason = f"사례 목록형 표({title[:40]})"
        elif _singleton_freq_table(block, cfg):
            reason = "빈도 1인 범주가 대부분인 빈도표(식별자 성격 변수 의심)"
        if reason:
            result.events.append(FilterEvent(title[:60], reason))
            out.append(f"[차단됨: {reason}]{where}")
        else:
            out.extend(block)
        out.append("")
    text_out = "\n".join(out).strip("\n")
    if len(text_out) > cfg.max_chars:
        half = cfg.max_chars // 2
        text_out = (text_out[:half] + f"\n\n[중략: 출력 {len(text_out):,}자 중 앞뒤 {half:,}자씩만 반환]\n\n"
                    + text_out[-half:])
        result.truncated = True
    result.text = text_out
    return result
