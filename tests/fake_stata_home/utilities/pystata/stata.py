# -*- coding: utf-8 -*-
"""가짜 pystata.stata(테스트 전용). run()이 받은 명령을 흉내 내 로그 파일에 씀.

흉내 범위: log using/close(name), cd, do 파일(줄마다 '. 명령' 기록), display 문자열·scalar,
scalar 대입(호출 간 유지), graph export(PNG 머리만 쓴 합성 파일), force_error(오류 r(111) + SystemError).
표준출력과 1번 파일 기술자에 잡음을 써서 작업자의 출력 분리를 검증함.
"""
import io
import os
import re
import sys

from . import config

_LOG = {"path": None}
_SCALARS = {}
_CWD = {"dir": None}
PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x05\x78" + b"\x00\x00\x03\xe8"
       + b"\x08\x02\x00\x00\x00" + b"\x00" * 4)


def _log(text):
    if _LOG["path"]:
        with io.open(_LOG["path"], "a", encoding="utf-8") as f:
            f.write(text + u"\n")


def _path(p):
    if not os.path.isabs(p) and _CWD["dir"]:
        return os.path.join(_CWD["dir"], p)
    return p


def _one(line):
    s = line.strip()
    if not s or s.startswith("*"):
        return
    _log(u". " + s)
    m = re.match(r'^display\s+"SA_VERSION\|"\s+c\(stata_version\)', s)
    if m:
        _log(u"SA_VERSION|18")
        return
    m = re.match(r"^scalar\s+(\w+)\s*=\s*(\S+)$", s)
    if m:
        _SCALARS[m.group(1)] = m.group(2)
        return
    m = re.match(r"^display\s+scalar\((\w+)\)$", s)
    if m:
        if m.group(1) not in _SCALARS:
            _log(u"scalar not found")
            _log(u"r(111);")
            raise SystemError("r(111);")
        _log(u"%s" % _SCALARS[m.group(1)])
        return
    m = re.match(r'^display\s+"([^"]*)"$', s)
    if m:
        _log(m.group(1))
        return
    m = re.match(r'^graph export\s+"([^"]+)"', s)
    if m:
        target = _path(m.group(1))
        d = os.path.dirname(target)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(target, "wb") as f:
            f.write(PNG)
        _log(u"file %s saved as PNG format" % m.group(1))
        return
    if "force_error" in s:
        _log(u"variable force_error not found")
        _log(u"r(111);")
        raise SystemError("variable force_error not found\nr(111);")


def run(cmd, quietly=False, echo=False, inline=None):
    if not config.STATE["initialized"]:
        raise SystemError("Stata not initialized")
    sys.stdout.write("python-level noise\n")      # 작업자가 버려야 하는 출력
    os.write(1, b"C-level noise\n")
    s = cmd.strip()
    m = re.match(r'^log using\s+"([^"]+)",\s*text replace name\(_sapy\)$', s)
    if m:
        _LOG["path"] = m.group(1)
        with io.open(_LOG["path"], "w", encoding="utf-8") as f:
            f.write(u"")
        return
    if re.match(r"^capture log close _sapy$", s):
        _LOG["path"] = None
        return
    m = re.match(r'^cd\s+"([^"]+)"$', s)
    if m:
        _CWD["dir"] = m.group(1)
        return
    m = re.match(r'^do\s+"([^"]+)"$', s)
    if m:
        _log(u". do \"%s\"" % m.group(1))
        with io.open(m.group(1), encoding="utf-8") as f:
            for line in f.read().splitlines():
                _one(line)
        _log(u"end of do-file")
        return
    for line in s.splitlines():
        _one(line)
