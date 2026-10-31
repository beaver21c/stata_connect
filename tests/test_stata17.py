"""Stata 17 호환 검사(IMPLEMENTATION_STATUS §11).

근거: Stata 17에서 IC → BE 이름 변경(Stata 17 매뉴얼, 2차), etable·collect 17 도입(Stata 17 기능 소개, 2차),
상류 stata-gui-mcp 1.1.0 지원 범위 17/18/19(패키지 설명, 1차).
"""

from datetime import date

from fakes import FakeBackend
from stata_agent.discovery import (
    AboutInfo,
    ComRegistration,
    DiscoveryReport,
    StataInstall,
    choose_installation,
    parse_about,
    version_declaration,
)
from stata_agent.selftest import run_selftest
from stata_agent.service import StataAgentService

# 형식은 test_discovery의 Stata 17 실제 로그(2차)와 같고 에디션만 BE로 바꾼 합성 사례
ABOUT_17_BE = """\
. about

Stata/BE 17.0 for Windows (64-bit x86-64)
Revision 21 Feb 2023
Copyright 1985-2021 StataCorp LLC

Total physical memory:       16.00 GB

Stata license: Single-user  perpetual
Serial number: 000000000000
  Licensed to: Example User
"""


def test_parse_about_17_be():
    info = parse_about(ABOUT_17_BE)
    assert (info.product, info.edition, info.version, info.major) == ("Stata", "BE", "17.0", 17)
    assert info.perpetual and info.license_valid(date(2026, 10, 31)) is True
    assert "Example" not in str(info.public_dict())


def test_edition_hint_ic_becomes_be_from_17():
    assert StataInstall("C:/Program Files/Stata17/Stata-64.exe", "IC", 17, "scan").edition == "BE"
    assert StataInstall("C:/Program Files/Stata16/Stata-64.exe", "IC", 16, "scan").edition == "IC"


def test_supported_range():
    assert StataInstall("x", "SE", 16, "scan").supported is False
    assert StataInstall("x", "SE", 17, "scan").supported is True
    assert StataInstall("x", "SE", None, "scan").supported is None
    assert StataInstall("x", "SE", 17, "scan").public_dict()["supported"] is True


def test_choose_prefers_17_over_16_and_declares_17():
    i16 = StataInstall("C:/Stata16/StataMP-64.exe", "MP", 16, "scan",
                       AboutInfo(edition="MP", version="16.1", perpetual=True, parsed=True))
    i17 = StataInstall("C:/Stata17/StataBE-64.exe", "BE", 17, "scan",
                       AboutInfo(edition="BE", version="17.0", perpetual=True, parsed=True))
    sel = choose_installation([i16, i17])
    assert sel is i17 and version_declaration(sel) == "version 17"
    assert version_declaration(None) == "version 17"  # 버전 미상 시 지원 하한으로 선언


def test_selftest_t1_fails_below_17(settings):
    inst = StataInstall("C:/Stata16/StataSE-64.exe", "SE", 16, "scan",
                        AboutInfo(product="Stata", edition="SE", version="16.1", perpetual=True, parsed=True))
    svc = StataAgentService(settings, backend=FakeBackend(), batch=FakeBackend(persistent=False),
                            discovery_report=DiscoveryReport([inst], inst, ComRegistration(True, inst.exe)))
    results, _ = run_selftest(svc, "test", release_lookup=lambda: "v0.1.0")
    t1 = next(r for r in results if r.id == "T1")
    assert t1.status == "fail" and "17" in t1.remedy


def test_etable_export_path_has_no_space_or_comma(settings, tmp_path):
    """Stata 17의 etable export()는 따옴표 안 경로의 공백·쉼표를 잘못 해석한다는 보고(2차) → 상대경로만 사용.
    프로젝트 폴더 이름에 공백이 있어도 명령에는 상대경로만 들어감."""
    project = tmp_path / "내 프로젝트, 1"
    project.mkdir()
    backend = FakeBackend()
    svc = StataAgentService(settings, backend=backend, batch=FakeBackend(persistent=False))
    assert not svc.open_session(str(project)).is_error
    assert not svc.export("etable", ["m1"], "table1.docx").is_error
    sent = [c[1] for c in backend.calls if c[0] == "code" and "etable" in c[1]][-1]
    target = sent.split('export("', 1)[1].split('"', 1)[0]
    assert target == "output/tables/table1.docx"
    assert svc.export("etable", ["m1"], "my table.docx").is_error
    assert svc.export("etable", ["m1"], "a,b.docx").is_error
