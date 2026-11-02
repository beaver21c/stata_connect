"""분석·보고용 계산 구분 SPSS판(IMPLEMENTATION_STATUS §20.5) — Stata판(stata_agent.readability)과 같은 원칙.

SPSS에 맞춘 판정 [논리적 추론]
- Stata ``quietly``에 해당: ``OMS … /DESTINATION VIEWER=NO``(출력이 결과에 남지 않음) 아래에서 분석 절차 실행
- 행렬 계산에 해당: ``MATRIX … END MATRIX`` 블록
- SPSS에는 ``estimates restore``가 없음 → 표 파일은 ``spss_export``로 저장하고, 보고용 섹션에는 저장된 결과를
  다시 가공하는 계산만 둠(새 분석 절차를 넣지 않음)
- 안내 줄은 SPSS 주석 명령(줄 첫머리 ``*``, 마침표로 끝)
"""

from __future__ import annotations

import re

from stata_agent.readability import (
    REPORT_TAG,
    decorate_code as _decorate,
    is_report,
    section_kind,
    section_title,
)

from .guard.policy import split_commands

ANALYSIS_NOTE = "* ▶ 분석 — 연구자 확인 대상: 아래 절차의 SPSS 출력이 결과의 근거."
REPORT_NOTE = "* ▷ 보고용 계산 — 확인 생략 가능: 위 분석 결과를 표·그림으로 옮기는 계산(새 분석 없음)."

# 분석 절차(출력 표가 결과의 근거). 한 낱말 명령은 SPSS 약어(앞 4글자 이상)도 인정
_PROCS_1 = ("REGRESSION", "NOMREG", "PLUM", "GENLIN", "GENLINMIXED", "GLM", "UNIANOVA", "MANOVA", "MIXED", "T-TEST",
            "ONEWAY", "CORRELATIONS", "FREQUENCIES", "DESCRIPTIVES", "EXAMINE", "CROSSTABS", "MEANS", "NPTESTS",
            "FACTOR", "RELIABILITY", "CLUSTER", "DISCRIMINANT", "COXREG", "KM", "SURVIVAL", "PROBIT", "CURVEFIT",
            "NLR", "CNLR", "ANOVA")
_PROCS_2 = ("LOGISTIC REGRESSION", "NONPAR CORR", "PARTIAL CORR", "NPAR TESTS", "QUICK CLUSTER")
_VIEWER_OFF = re.compile(r"VIEWER\s*=\s*NO\b", re.IGNORECASE)


def _proc_name(text: str) -> str | None:
    words = text.upper().split()
    if not words:
        return None
    two = " ".join(words[:2])
    for p in _PROCS_2:
        if two == p:
            return p
    w = words[0]
    for p in _PROCS_1:
        if w == p or (len(w) >= 4 and p.startswith(w)):
            return p
    return None


def decorate_code(code: str, kind: str) -> str:
    return _decorate(code, kind, (ANALYSIS_NOTE, REPORT_NOTE))


def readability_notes(code: str, kind: str) -> list[str]:
    notes: list[str] = []
    hidden: list[str] = []
    in_report: list[str] = []
    matrix = 0
    viewer_off = False
    for _, text in split_commands(code):
        t = text.strip()
        if not t or t.startswith("*") or t.upper().startswith("COMMENT"):
            continue
        u = t.upper()
        if u.startswith("OMSEND"):
            viewer_off = False
            continue
        if u.startswith("OMS") and _VIEWER_OFF.search(t):
            viewer_off = True
            continue
        if re.match(r"^MATRIX\b(?!\s+DATA)", u):
            matrix += 1
            continue
        if _proc_name(t):
            if kind == "report":
                in_report.append(t[:60])
            elif viewer_off:
                hidden.append(t[:60])
    if kind == "analysis":
        if hidden:
            notes.append("분석 섹션의 절차가 OMS VIEWER=NO 아래에서 실행됨 → 출력 표가 결과에 남지 않아 연구자가 확인하기 어려움: "
                         + "; ".join(f"`{h}`" for h in hidden[:3]) + " → 출력이 보이게 실행하고 표 파일은 spss_export로 저장")
        if matrix:
            notes.append(f"분석 섹션에 MATRIX 계산 {matrix}개 → 보고용 섹션(kind=report)으로 분리하고, 가능하면 SPSS 기본 출력 사용"
                         "(표준화 계수는 REGRESSION 계수표의 Beta, 단계별 R² 변화는 /METHOD=ENTER 여러 줄 + /STATISTICS … CHANGE)")
    elif in_report:
        notes.append("보고용 섹션에 새 분석 절차: " + "; ".join(f"`{e}`" for e in in_report[:3])
                     + " → 분석 섹션으로 옮기고, 보고용 섹션에는 저장된 결과를 가공하는 계산만 둠")
    return notes


__all__ = ["ANALYSIS_NOTE", "REPORT_NOTE", "REPORT_TAG", "decorate_code", "is_report", "readability_notes",
           "section_kind", "section_title"]
