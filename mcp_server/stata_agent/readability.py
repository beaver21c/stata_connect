"""분석·보고용 계산 구분(IMPLEMENTATION_STATUS §20) — 연구자가 do-file에서 "요청한 분석"만 확인하고
표 작성용 행렬·반복 계산은 건너뛸 수 있게 함.

배경(2026-11-02 사용자 실사용): AI가 쓴 do-file이 ``quietly regress`` + 행렬(J()·_b·_se·ttail) 위주라 사람이
분석을 확인하기 어려움 → "요청한 분석(예: reg a b c d)은 보이게 표기하고, 그 아래 기술용 행렬 계산은 구분"(사용자 요구).

규칙
- 분석 섹션(kind=analysis): 추정 명령을 ``quietly`` 없이 실행해 Stata 원래 결과표가 로그에 남게 함.
  필요한 통계는 가능하면 Stata 기본 출력으로(예: 표준화 계수 ``regress …, beta``, 단계별 R² 변화·F 검정 ``nestreg:``)
- 보고용 섹션(kind=report): 표·그림을 만들기 위한 행렬·스칼라·반복 계산. 새 추정 없이 ``estimates restore``로 꺼내 씀.
  섹션 표지에 ``[보고용]``을 붙이고 첫 줄에 "확인 생략 가능" 안내
- 판정은 명령 문자열 기준 정적 검사이며 강제하지 않고 "가독성 참고"로만 알림 [논리적 추론]
"""

from __future__ import annotations

import re

from .guard.stata_lexer import abbrev_match, iter_statements, parse_command

REPORT_TAG = "[보고용]"
ANALYSIS_NOTE = "* ▶ 분석 — 연구자 확인 대상: 아래 명령의 Stata 출력이 결과의 근거"
REPORT_NOTE = "* ▷ 보고용 계산 — 확인 생략 가능: 위 분석 결과를 표·그림으로 옮기는 계산(새 추정 없음)"
_NOTE_PREFIXES = ("* ▶ 분석 —", "* ▷ 보고용 계산 —")
KINDS = ("analysis", "report")

# 추정·검정 명령(결과표가 분석의 근거가 되는 명령)
_ESTIMATION = {
    "regress", "reg", "logit", "logistic", "probit", "ologit", "oprobit", "mlogit", "mprobit", "poisson", "nbreg",
    "zip", "zinb", "glm", "tobit", "intreg", "truncreg", "qreg", "rreg", "areg", "ivregress", "heckman",
    "xtreg", "xtlogit", "xtprobit", "xtpoisson", "xtnbreg", "xtmixed", "mixed", "melogit", "meprobit", "mepoisson",
    "sem", "gsem", "stcox", "streg", "anova", "manova", "oneway", "ttest", "ranksum", "signrank", "kwallis",
    "correlate", "corr", "pwcorr", "spearman", "ktau", "factor", "pca", "alpha", "reghdfe", "ppmlhdfe",
    "mediate", "nl", "mlexp", "biprobit", "cloglog", "clogit", "hetprobit", "betareg", "fracreg",
}
_MATRIX_BUILD = re.compile(r"^\s*mat(?:r(?:i(?:x)?)?)?\s+(?!list\b|dir\b|drop\b)[A-Za-z_]\w*\s*(?:\[[^\]]*\])?\s*=",
                           re.IGNORECASE)


def is_report(title: str) -> bool:
    return str(title or "").strip().startswith(REPORT_TAG)


def section_kind(title: str) -> str:
    return "report" if is_report(title) else "analysis"


def section_title(title: str, kind: str | None) -> str:
    """kind에 맞게 [보고용] 표지 붙이기·떼기. kind=None이면 그대로."""
    t = str(title or "").strip()
    if kind is None:
        return t
    bare = t[len(REPORT_TAG):].strip() if t.startswith(REPORT_TAG) else t
    return f"{REPORT_TAG} {bare}" if kind == "report" else bare


def decorate_code(code: str, kind: str, notes: tuple[str, str] = (ANALYSIS_NOTE, REPORT_NOTE)) -> str:
    """섹션 첫 줄에 분석·보고용 안내(이미 있으면 바꿈). notes=(분석 안내, 보고용 안내) — SPSS는 마침표로 끝나는 주석."""
    lines = [ln for ln in str(code or "").replace("\r\n", "\n").split("\n")
             if not ln.strip().startswith(_NOTE_PREFIXES)]
    while lines and not lines[0].strip():
        lines.pop(0)
    note = notes[1] if kind == "report" else notes[0]
    return "\n".join([note, *lines])


def _is_estimation(name: str) -> bool:
    return name in _ESTIMATION or abbrev_match(name, "regress", "reg")


def readability_notes(code: str, kind: str) -> list[str]:
    """정적 점검 → 사람이 읽을 참고 문장(강제 아님)."""
    notes: list[str] = []
    quiet_est: list[str] = []
    est_in_report: list[str] = []
    matrix_lines = 0
    quiet_depth = 0
    depth = 0
    for st in iter_statements(code):
        if st.context != "stata":
            continue
        text = st.text.strip()
        cmd = parse_command(text)
        quiet_prefix = any(abbrev_match(p.split()[0].lower(), "quietly", "qui") for p in cmd.prefixes if p)
        if cmd.name == "{" or text.endswith("{"):
            depth += 1
            if quiet_prefix and cmd.name == "{":
                quiet_depth = depth
        if text.startswith("}"):
            if quiet_depth and depth == quiet_depth:
                quiet_depth = 0
            depth = max(0, depth - 1)
        if _MATRIX_BUILD.match(text):
            matrix_lines += 1
        if _is_estimation(cmd.name):
            if kind == "report":
                est_in_report.append(text[:60])
            elif quiet_prefix or quiet_depth:
                quiet_est.append(text[:60])
    if kind == "analysis":
        if quiet_est:
            notes.append("분석 섹션의 추정 명령에 quietly → Stata 결과표가 로그에 남지 않아 연구자가 확인하기 어려움: "
                         + "; ".join(f"`{q}`" for q in quiet_est[:3]) + " → quietly 없이 실행")
        if matrix_lines >= 3:
            notes.append(f"분석 섹션에 행렬 계산 {matrix_lines}줄 → 표 작성용 계산은 보고용 섹션(kind=report)으로 분리하고, "
                         "가능하면 Stata 기본 출력 사용(표준화 계수 `regress …, beta`, 단계별 R² 변화 `nestreg:`)")
    elif est_in_report:
        notes.append("보고용 섹션에 새 추정 명령: " + "; ".join(f"`{e}`" for e in est_in_report[:3])
                     + " → 분석 섹션으로 옮기고, 보고용 섹션에서는 `estimates restore`로 저장된 결과를 사용")
    return notes


__all__ = ["ANALYSIS_NOTE", "KINDS", "REPORT_NOTE", "REPORT_TAG", "decorate_code", "is_report",
           "readability_notes", "section_kind", "section_title"]
