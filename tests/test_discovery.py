import os
from datetime import date

from stata_agent.discovery import (
    AboutInfo,
    StataInstall,
    batch_command,
    choose_installation,
    parse_about,
    scan_installations,
    version_declaration,
)

# 형식 근거: 공개 저장소의 실제 Stata 로그(2차 자료). 등록자·일련번호는 익명화함.
ABOUT_ANNUAL = """\
. about

Stata/MP 17.0 for Windows (64-bit x86-64)
Revision 18 Jul 2023
Copyright 1985-2021 StataCorp LLC

Total physical memory:       32.00 GB
Available physical memory:   18.61 GB

Stata license: Unlimited-user 2-core network, expiring 21 Jan 2024
Serial number: 000000000000
  Licensed to: Example User
               Example University
"""

ABOUT_NOW_PADDED = """\
StataNow/MP 19.5 for Unix (Apple Silicon)
Revision 01 Oct 2026
Total usable memory: 48.01 GB

Stata license: Single-user 4-core , expiring  5 Oct 2027
Serial number: 000000000001
  Licensed to: Someone
"""

ABOUT_PERPETUAL = """\
Stata/SE 18.0 for Windows (64-bit x86-64)
Revision 14 Feb 2024

Stata license: Single-user 2-core  perpetual
Serial number: 000000000002
  Licensed to: A
"""

BATCH_REFUSED = "request ignored because of batch mode\n"


def test_parse_annual_license():
    info = parse_about(ABOUT_ANNUAL)
    assert (info.product, info.edition, info.version) == ("Stata", "MP", "17.0")
    assert info.expires == date(2024, 1, 21)
    assert info.licensed_to == ["Example User", "Example University"]
    assert info.license_valid(date(2026, 10, 29)) is False
    assert info.license_valid(date(2023, 12, 1)) is True
    assert info.major == 17


def test_parse_statanow_space_padded_day():
    info = parse_about(ABOUT_NOW_PADDED)
    assert (info.product, info.edition, info.version) == ("StataNow", "MP", "19.5")
    assert info.expires == date(2027, 10, 5)


def test_parse_perpetual():
    info = parse_about(ABOUT_PERPETUAL)
    assert info.perpetual and info.license_valid() is True
    assert info.expires is None


def test_public_dict_excludes_serial_and_owner():
    pub = parse_about(ABOUT_ANNUAL).public_dict(date(2023, 1, 1))
    text = str(pub)
    assert "000000000000" not in text and "Example User" not in text
    assert pub["license_valid"] is True


def test_batch_refused():
    info = parse_about(BATCH_REFUSED)
    assert info.batch_refused and info.license_valid() is False


def _inst(exe, ed, ver, valid):
    i = StataInstall(exe, ed, ver, "scan")
    i.about = AboutInfo(edition=ed, version=f"{ver}.0", perpetual=valid is True, batch_refused=valid is False, parsed=True)
    return i


def test_choose_priority():
    a = _inst("C:/Stata17/StataMP-64.exe", "MP", 17, True)
    b = _inst("C:/Stata18/StataSE-64.exe", "SE", 18, True)
    c = _inst("C:/StataNow19/StataMP-64.exe", "MP", 19, False)  # 만료
    d = _inst("C:/Stata18/StataMP-64.exe", "MP", 18, True)
    assert choose_installation([a, b, c, d]).exe == d.exe  # 유효 최신 + MP 우선
    assert choose_installation([a, b, c, d], preferred_exe=a.exe).exe == a.exe  # 사용자 지정 최우선
    assert choose_installation([c]) is None


def test_scan_with_roots(tmp_path):
    for folder, exe in (("Stata18", "StataSE-64.exe"), ("StataNow19", "StataMP-64.exe"), ("Stata17", "readme.txt")):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / exe).write_text("")
    found = {os.path.basename(i.exe) + "@" + str(i.version_hint): i.edition_hint for i in scan_installations([str(tmp_path)])}
    assert found == {"StataSE-64.exe@18": "SE", "StataMP-64.exe@19": "MP"}


def test_version_declaration():
    assert version_declaration(_inst("x", "MP", 19, True)) == "version 19"
    assert version_declaration(StataInstall("x", "SE", 18, "scan")) == "version 18"
    assert version_declaration(None, fallback=17) == "version 17"


def test_batch_command():
    assert batch_command("C:/Stata18/StataSE-64.exe", "a.do") == ["C:/Stata18/StataSE-64.exe", "/e", "do", "a.do"]
