# -*- coding: utf-8 -*-
"""SPSS 엔진 스크립트 구버전 Python 실행 점검(SPSS 22·23 = Python 2.7, 24~26 = 2.7·3.4 대비).

CI(spss-legacy-python)가 python:2.7·python:3.4 이미지 안에서 실행. pytest 없이 단독 실행되며
Python 2.7·3.4 문법만 사용. 가짜 spss 모듈(tests/fake_spss_home)로 엔진 통신 규약 전체를 확인.

사용: python tests/legacy/run_engine_check.py   (종료 코드 0 = 통과)
"""
from __future__ import print_function

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FAKE_SPSS = os.path.join(ROOT, "tests", "fake_spss_home", "Python3", "Lib", "site-packages", "spss.py")
SCRIPT_SRC = os.path.join(ROOT, "mcp_server", "spss_agent", "engine_script.py")


def engine_script():
    with io.open(SCRIPT_SRC, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"ENGINE_SCRIPT = r'''(.*?)'''", text, re.S)
    if not m:
        raise SystemExit("ENGINE_SCRIPT not found")
    return m.group(1)


def main():
    work = tempfile.mkdtemp(prefix="sa_legacy_")
    try:
        home = os.path.join(work, "SPSS")
        for sub in ("Python", "Python3"):
            d = os.path.join(home, sub, "Lib", "site-packages")
            os.makedirs(d)
            shutil.copy(FAKE_SPSS, d)
        script = os.path.join(work, "engine.py")
        with io.open(script, "w", encoding="utf-8") as f:
            f.write(engine_script())
        proc = subprocess.Popen([sys.executable, script, home], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=work)

        def wait_for(marker):
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise SystemExit("engine exited before %r; stderr=%r" % (marker, proc.stderr.read()[-2000:]))
                line = line.decode("ascii", "replace").strip()
                if line == marker or line.startswith("__SA_FAIL__"):
                    return line

        def request(rid, op, **payload):
            resp = os.path.join(work, "resp_%d.json" % rid)
            req = dict(payload, id=rid, op=op, resp=resp)
            proc.stdin.write((json.dumps(req) + "\n").encode("ascii"))  # 서버와 같은 ASCII 이스케이프 JSON
            proc.stdin.flush()
            wait_for("__SA_DONE__ %d" % rid)
            with io.open(resp, encoding="utf-8") as f:
                return json.load(f)

        first = wait_for("__SA_READY__")
        assert first == "__SA_READY__", first
        assert request(1, "ping")["ok"]
        out = os.path.join(work, "o.txt")
        r = request(2, "submit", outfile=out,
                    syntax=u"* 한글 주석.\nDATA LIST FREE / x.\nBEGIN DATA\n1 2 3 4\nEND DATA.\nDESCRIPTIVES VARIABLES=x.")
        assert r["ok"] and r["err_level"] == 0, r
        with io.open(out, encoding="utf-8-sig") as f:
            assert "2.50" in f.read()
        d = request(3, "dictionary", missing=True)
        assert d["cases"] == 4 and d["variables"][0]["name"] == "x" and d["variables"][0]["missing"] == 0, d
        u = request(4, "unique", tokens=["X", "ALL"])
        assert u["counts"]["x"] == {"unique": 4, "nonmissing": 4}, u
        bad = request(5, "submit", syntax="FORCE_ERROR.", outfile=os.path.join(work, "e.txt"))
        assert not bad["ok"] and bad["err_level"] == 3, bad
        assert request(6, "ping")["ok"]
        proc.stdin.write(b'{"op": "exit"}\n')
        proc.stdin.flush()
        proc.wait()
        print("legacy engine check passed on Python %s" % sys.version.split()[0])
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
