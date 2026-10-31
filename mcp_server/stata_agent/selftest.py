"""사용자 자가 점검 T1~T10(설계서 §13.1). Stata 내장 auto.dta만 사용.

T4 기준값: N=74, 평균 6165.257, 표준편차 2949.496, r(weight,length)=.9460, 허용오차 ±0.001
(설계서 §13.1 — Stata 18 SE·StataNow 19.5 산출값 일치, 1차 확인)
"""

from __future__ import annotations

import json
import platform
import re
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__
from .dofile import DoFile, new_dofile
from .guard.command_policy import Action, check
from .guard.output_filter import extract_markers, filter_output

EXPECTED_T4 = {"N": 74.0, "mean": 6165.257, "sd": 2949.496, "r": 0.9460}
TOLERANCE = 0.001
RELEASES_API = "https://api.github.com/repos/beaver21c/stata_connect/releases/latest"

T4_CODE = """\
sysuse auto, clear
summarize price
quietly summarize price
display "SAT4|N|" r(N)
display "SAT4|mean|" %24.0g r(mean)
display "SAT4|sd|" %24.0g r(sd)
quietly correlate weight length
display "SAT4|r|" %24.0g r(rho)
"""

_SYNTHETIC_LIST_OUTPUT = """\
. list make price in 1/2

     +---------------------+
     | make          price |
     |---------------------|
  1. | AMC Concord   4,099 |
  2. | AMC Pacer     4,749 |
     +---------------------+
"""


@dataclass
class TestResult:
    id: str
    name: str
    status: str  # pass | fail | skip | manual
    detail: str = ""
    remedy: str = ""


def _markers(text: str, prefix: str) -> dict[str, float]:
    out = {}
    for fields in extract_markers(text, prefix):
        if len(fields) >= 2:
            try:
                out[fields[0]] = float(fields[1])
            except ValueError:
                pass
    return out


def _compare_t4(values: dict[str, float]) -> list[str]:
    errors = []
    for key, expected in EXPECTED_T4.items():
        got = values.get(key)
        if got is None:
            errors.append(f"{key} 값 없음")
        elif abs(got - expected) > TOLERANCE:
            errors.append(f"{key}={got} (기준 {expected})")
    return errors


def latest_release_tag(timeout: float = 5.0) -> str | None:
    req = urllib.request.Request(RELEASES_API, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (고정 https 주소)
        return json.loads(resp.read().decode("utf-8")).get("tag_name")


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def run_selftest(service, client_name: str | None = None, include_batch: bool = True,
                 release_lookup=latest_release_tag) -> tuple[list[TestResult], dict]:
    """service: StataAgentService(자가 점검 전용 복제본 권장)."""
    results: list[TestResult] = []
    meta: dict = {
        "client": client_name or "(미기재)",
        "server_version": __version__,
        "os": platform.platform(),
        "backend": service.backend.name,
    }
    root = Path(service.settings.report_dir) / "selftest"
    root.mkdir(parents=True, exist_ok=True)

    # T1 설치·라이선스
    inst = service._selected_install(full=True)
    if inst is None:
        results.append(TestResult("T1", "Stata 설치·라이선스", "fail", "Stata 설치를 찾지 못함",
                                  "STATA_AGENT_STATA_EXE로 실행파일 지정 또는 Stata 설치 확인"))
    else:
        pub = inst.public_dict()
        meta["stata"] = {k: pub.get(k) for k in ("edition", "version")}
        meta["stata"]["license_valid"] = inst.license_valid()
        meta["stata"]["expires"] = pub["about"]["expires"] if pub.get("about") else None
        valid = inst.license_valid()
        status = "pass" if valid else ("fail" if valid is False else "manual")
        remedy = "" if status == "pass" else "라이선스 갱신 또는 about 출력 확인"
        if inst.supported is False:
            status, remedy = "fail", "Stata 17 이상 필요(지원 범위 밖)"
        results.append(TestResult(
            "T1", "Stata 설치·라이선스", status,
            f"{inst.edition} {pub.get('version')} / 만료일 {meta['stata']['expires'] or '영구 또는 미확인'}"
            + (f" / {inst.about_error}" if inst.about_error else ""),
            remedy))

    # T2 COM 연결(세션 열기 + display)
    opened = service.open_session(str(root), "stata_agent_selftest")
    if opened.is_error:
        results.append(TestResult("T2", "Stata 연결", "fail", opened.text,
                                  "설치 프로그램의 'COM 재등록'(관리자 승인) 실행"))
        session_ok = False
    else:
        out = service._run_internal('display 12345')
        session_ok = out.ok and "12345" in out.log_text
        results.append(TestResult("T2", "Stata 연결", "pass" if session_ok else "fail",
                                  f"backend={service.backend.name}, rc={out.return_code}",
                                  "" if session_ok else "COM 재등록·Stata 실행 상태 확인"))

    # T3 세션 유지
    if session_ok and service.backend.persistent_session:
        service._run_internal("scalar t3 = 1")
        out = service._run_internal('display "SAT3|v|" scalar(t3)')
        v = _markers(out.log_text, "SAT3").get("v")
        results.append(TestResult("T3", "창 표시·세션 유지", "pass" if v == 1 else "fail",
                                  f"scalar t3 = {v}", "" if v == 1 else "Stata 창 수동 종료 여부 확인"))
    else:
        results.append(TestResult("T3", "창 표시·세션 유지", "skip",
                                  "세션 미연결 또는 배치 모드(메모리 미유지)"))

    # T4·T5 계산 정확성·로그 반환
    t4_values: dict[str, float] = {}
    if session_ok:
        out = service._run_internal(T4_CODE)
        t4_values = _markers(out.log_text, "SAT4")
        errs = _compare_t4(t4_values)
        results.append(TestResult("T4", "계산 정확성", "fail" if errs else "pass",
                                  "; ".join(errs) or "N·평균·표준편차·상관 기준값 일치",
                                  "버전 선언·자료 손상 확인" if errs else ""))
        m = re.search(r"^\s*price\s*\|\s*([\d,]+)\s+([\d.]+)\s+([\d.]+)", out.log_text, re.MULTILINE)
        log_mean = float(m.group(2)) if m else None
        ok5 = log_mean is not None and "mean" in t4_values and abs(log_mean - t4_values["mean"]) <= TOLERANCE
        results.append(TestResult("T5", "로그 반환", "pass" if ok5 else "fail",
                                  f"로그 평균 {log_mean} / r(mean) {t4_values.get('mean')}",
                                  "" if ok5 else "로그 경로 권한 확인"))
    else:
        results += [TestResult("T4", "계산 정확성", "skip", "세션 미연결"),
                    TestResult("T5", "로그 반환", "skip", "세션 미연결")]

    # T6 원자료 차단(guard + 출력 필터, Stata 미실행)
    g1 = check("list in 1/3", str(root))
    g2 = check("browse", str(root))
    f = filter_output(_SYNTHETIC_LIST_OUTPUT)
    ok6 = g1.action == Action.BLOCK and g2.action == Action.BLOCK and f.blocked_any and "AMC" not in f.text
    results.append(TestResult("T6", "원자료 차단", "pass" if ok6 else "fail",
                              "list·browse 차단, 목록 형식 출력 필터 차단" if ok6 else "보호 장치 실패",
                              "" if ok6 else "즉시 사용 중지·보고(보호 장치 실패)"))

    # T7 편집기 연동(육안 확인 필요)
    if session_ok and service.backend.persistent_session:
        name = "99_selftest.do"
        path = root / name
        path.write_text(new_dofile(name, [("점검", 'display "selftest"')], service._version_line()), encoding="utf-8")
        first = service.editor.show(path, service.session_id or "")
        doc = DoFile.parse(path.read_text(encoding="utf-8"))
        doc.add("추가 섹션", 'display "added"')
        path.write_text(doc.render(), encoding="utf-8")
        second = service.editor.show(path, service.session_id or "")
        status = "manual" if first.ok and second.ok else "fail"
        results.append(TestResult("T7", "do-file 편집기 연동", status,
                                  "Do-file Editor에 '추가 섹션'(S02) 반영·탭 중복 여부를 화면에서 확인",
                                  "편집기 탭 수동 새로고침"))
    else:
        results.append(TestResult("T7", "do-file 편집기 연동", "skip", "세션 미연결 또는 배치 모드"))

    # T8 파일 산출
    if session_ok:
        docx = root / "selftest.docx"
        docx.unlink(missing_ok=True)
        code = (
            "putdocx clear\nputdocx begin\nputdocx paragraph\n"
            'putdocx text ("stata-agent selftest")\n'
            f'putdocx save "{str(docx).replace(chr(92), "/")}", replace\n'
        )
        out = service._run_internal(code)
        ok8 = docx.is_file()
        results.append(TestResult("T8", "파일 산출", "pass" if ok8 else "fail",
                                  f"putdocx rc={out.return_code}", "" if ok8 else "작업 폴더 쓰기 권한 확인"))
    else:
        results.append(TestResult("T8", "파일 산출", "skip", "세션 미연결"))

    # T9 배치 재현
    if include_batch:
        ok_b, why = service.batch.available()
        if ok_b:
            out = service.batch.run_code(T4_CODE, "selftest", root)
            vals = _markers(out.log_text, "SAT4")
            errs = _compare_t4(vals)
            same = bool(t4_values) and all(abs(vals.get(k, 1e9) - t4_values[k]) <= TOLERANCE for k in t4_values)
            ok9 = not errs and (same or not t4_values)
            results.append(TestResult("T9", "재현 실행(배치)", "pass" if ok9 else "fail",
                                      "; ".join(errs) or "배치 결과 기준값 일치" + (", 대화형과 일치" if same else ""),
                                      "" if ok9 else "배치 실행 경로·라이선스 확인"))
        else:
            results.append(TestResult("T9", "재현 실행(배치)", "fail", why, "Stata 실행파일 경로 확인"))
    else:
        results.append(TestResult("T9", "재현 실행(배치)", "skip", "요청에 따라 생략"))

    # T10 버전
    try:
        tag = release_lookup()
        if not tag:
            results.append(TestResult("T10", "서버 버전", "skip", "공개 Release 없음"))
        else:
            cur, latest = _version_tuple(__version__), _version_tuple(tag)
            behind = (latest[:2] > cur[:2]) and not (latest[0] == cur[0] and latest[1] - cur[1] <= 1)
            results.append(TestResult("T10", "서버 버전", "fail" if behind else "pass",
                                      f"현재 {__version__} / 최신 {tag}", "안내 사이트에서 업데이트" if behind else ""))
    except Exception as e:  # 네트워크 차단 등
        results.append(TestResult("T10", "서버 버전", "skip", f"최신 버전 확인 불가({type(e).__name__})"))

    return results, meta


def results_table(results: list[TestResult]) -> str:
    label = {"pass": "통과", "fail": "실패", "skip": "생략", "manual": "육안 확인"}
    lines = ["| # | 항목 | 결과 | 내용 | 조치 |", "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.id} | {r.name} | {label.get(r.status, r.status)} | {r.detail} | {r.remedy} |")
    return "\n".join(lines)


def to_dicts(results: list[TestResult]) -> list[dict]:
    return [asdict(r) for r in results]
