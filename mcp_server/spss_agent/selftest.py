"""SPSS 자가 점검 T1~T10. 문법 안 예제 자료(1~10)만 사용, 사용자 자료 미사용.

T4 기준값(문법 자료 x=1..10, y=x²): 평균 5.5, 표준편차 3.02765(표본), 상관 r(x,y)=0.97460
→ 출력 표의 숫자 표시 자릿수가 미확인이라 출력 안 숫자 중 기준값과 허용오차 0.005 이내 값이 있으면 통과(판정 방식 [논리적 추론])
"""

from __future__ import annotations

import math
import platform
import re
from pathlib import Path

from stata_agent.guard.command_policy import Action
from stata_agent.selftest import TestResult, latest_release_tag, _version_tuple

from . import __version__
from .guard.output_filter import filter_output
from .guard.policy import check
from .syntaxfile import SyntaxFile, new_syntax

_X = list(range(1, 11))
_Y = [v * v for v in _X]


def _pearson(a: list[float], b: list[float]) -> float:
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))


EXPECTED = {
    "mean": 5.5,
    "sd": math.sqrt(sum((v - 5.5) ** 2 for v in _X) / 9),
    "r": _pearson(_X, _Y),
}
TOLERANCE = 0.005

DATA_SYNTAX = "DATA LIST FREE / x.\nBEGIN DATA\n" + " ".join(map(str, _X)) + "\nEND DATA.\nCOMPUTE y = x*x.\nEXECUTE.\n"
CALC_SYNTAX = "DESCRIPTIVES VARIABLES=x /STATISTICS=MEAN STDDEV.\nCORRELATIONS /VARIABLES=x y.\n"

_SYNTHETIC_LISTING = "Case Summaries\n\n  id  score\n1  1  72\n2  2  85\n"


def numbers_in(text: str) -> list[float]:
    out = []
    for tok in re.findall(r"(?<![\w.])-?(?:\d+\.\d*|\.\d+|\d+)(?![\w])", text):
        try:
            out.append(float(tok))
        except ValueError:
            pass
    return out


def check_values(text: str) -> list[str]:
    nums = numbers_in(text)
    return [f"{k} 기준값 {v:.5f} 미발견" for k, v in EXPECTED.items()
            if not any(abs(n - v) <= TOLERANCE for n in nums)]


def run_selftest(service, client_name: str | None = None, include_batch: bool = True,
                 release_lookup=latest_release_tag) -> tuple[list[TestResult], dict]:
    results: list[TestResult] = []
    inst = service.backend.install
    meta = {
        "client": client_name or "(미기재)", "server_version": __version__, "os": platform.platform(),
        "backend": service.backend.name, "software": "SPSS",
        "software_info": {"version": inst.version if inst else None, "edition": "Statistics",
                          "license_valid": None, "expires": None},
    }
    root = Path(service.settings.report_dir) / "spss_selftest"
    root.mkdir(parents=True, exist_ok=True)

    ok, why = service.backend.available()
    results.append(TestResult("T1", "SPSS 설치", "pass" if ok else "fail",
                              f"{inst.home} (버전 {inst.version})" if inst else why,
                              "" if ok else "SPSS 설치·Python 연동 기능 확인, SPSS_AGENT_HOME 지정"))

    opened = service.open_session(str(root)) if ok else None
    session_ok = bool(opened and not opened.is_error)
    results.append(TestResult("T2", "SPSS 엔진 기동", "pass" if session_ok else ("fail" if ok else "skip"),
                              "" if session_ok else (opened.text if opened else "설치 미확인"),
                              "" if session_ok else "SPSS 라이선스·Python 연동 확인"))

    calc_text = ""
    if session_ok:
        r1 = service.backend.run(DATA_SYNTAX, root / ".spss-agent" / "t3a.txt")
        r2 = service.backend.run("DESCRIPTIVES VARIABLES=x.\n", root / ".spss-agent" / "t3b.txt")
        kept = r1.ok and r2.ok and any(abs(n - 5.5) <= TOLERANCE for n in numbers_in(r2.log_text))
        results.append(TestResult("T3", "세션 유지", "pass" if kept else "fail",
                                  "앞 요청에서 만든 자료를 다음 요청에서 사용" if kept else (r2.message or "자료 유지 실패"),
                                  "" if kept else "엔진 재기동 여부 확인"))
        r3 = service.backend.run(CALC_SYNTAX, root / ".spss-agent" / "t4.txt")
        calc_text = r3.log_text
        errs = check_values(calc_text)
        results.append(TestResult("T4", "계산 정확성", "fail" if errs or not r3.ok else "pass",
                                  "; ".join(errs) or "평균·표준편차·상관 기준값 확인", "출력 확인" if errs else ""))
        has_out = bool(calc_text.strip()) and r3.log_path is not None and Path(r3.log_path).is_file()
        results.append(TestResult("T5", "출력 수집(OMS)", "pass" if has_out else "fail",
                                  "출력 파일 생성·수신" if has_out else "출력 파일 없음", "" if has_out else "작업 폴더 쓰기 권한 확인"))
    else:
        results += [TestResult(t, n, "skip", "엔진 미기동") for t, n in
                    (("T3", "세션 유지"), ("T4", "계산 정확성"), ("T5", "출력 수집(OMS)"))]

    g1, g2 = check("LIST.", str(root)), check("PRINT / x.\nEXECUTE.", str(root))
    f = filter_output(_SYNTHETIC_LISTING)
    ok6 = g1.action == Action.BLOCK and g2.action == Action.BLOCK and f.blocked_any and "72" not in f.text
    results.append(TestResult("T6", "원자료 차단", "pass" if ok6 else "fail",
                              "LIST·PRINT 차단, 사례 목록 표 필터 차단" if ok6 else "보호 장치 실패",
                              "" if ok6 else "즉시 사용 중지·보고"))

    p = root / "99_selftest.sps"
    p.write_text(new_syntax("99_selftest.sps", [("점검", "DESCRIPTIVES VARIABLES=x.")]), encoding="utf-8-sig")
    doc = SyntaxFile.parse(p.read_text(encoding="utf-8-sig"))
    doc.add("추가", "CORRELATIONS /VARIABLES=x y.")
    p.write_text(doc.render(), encoding="utf-8-sig")
    ok7 = [s.id for s in SyntaxFile.parse(p.read_text(encoding="utf-8-sig")).sections] == ["S01", "S02"]
    results.append(TestResult("T7", "문법 파일 섹션 편집", "pass" if ok7 else "fail", "섹션 추가·재해석"))

    if session_ok:
        sav = root / "selftest.sav"
        sav.unlink(missing_ok=True)
        r8 = service.backend.run(f"SAVE OUTFILE='{str(sav).replace(chr(92), '/')}'.\n", root / ".spss-agent" / "t8.txt")
        results.append(TestResult("T8", "파일 산출", "pass" if sav.is_file() else "fail",
                                  f"SAVE 오류 수준 {r8.return_code}", "" if sav.is_file() else "작업 폴더 쓰기 권한 확인"))
    else:
        results.append(TestResult("T8", "파일 산출", "skip", "엔진 미기동"))

    if include_batch and session_ok:
        fresh = service.backend.fresh()
        try:
            o = fresh.open_session(root, engine_dir=".spss-agent/t9")
            r9 = fresh.run(DATA_SYNTAX + CALC_SYNTAX, root / ".spss-agent" / "t9.txt") if o.ok else None
        finally:
            fresh.close()
        errs = check_values(r9.log_text) if r9 else ["새 엔진 기동 실패"]
        results.append(TestResult("T9", "재현 실행(새 엔진)", "fail" if errs else "pass",
                                  "; ".join(errs) or "새 엔진 결과 기준값 일치", "SPSS 동시 실행 라이선스 확인" if errs else ""))
    else:
        results.append(TestResult("T9", "재현 실행(새 엔진)", "skip", "생략 또는 엔진 미기동"))

    try:
        tag = release_lookup()
        if not tag:
            results.append(TestResult("T10", "서버 버전", "skip", "공개 Release 없음"))
        else:
            cur, latest = _version_tuple(__version__), _version_tuple(tag)
            behind = latest[:2] > cur[:2] and not (latest[0] == cur[0] and latest[1] - cur[1] <= 1)
            results.append(TestResult("T10", "서버 버전", "fail" if behind else "pass", f"현재 {__version__} / 최신 {tag}"))
    except Exception as e:
        results.append(TestResult("T10", "서버 버전", "skip", f"최신 버전 확인 불가({type(e).__name__})"))
    service.backend.close()
    return results, meta
