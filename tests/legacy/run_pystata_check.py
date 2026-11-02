# -*- coding: utf-8 -*-
"""pystata 작업자 스크립트 구버전 Python 실행 점검(Stata 17 pystata 지원 범위 Python 2.7·3.4 이상 대비, §16).

CI(spss-legacy-python 작업의 둘째 단계)가 python:2.7·python:3.4 이미지 안에서 실행. pytest 없이 단독 실행되며
Python 2.7·3.4 문법만 사용. 가짜 pystata(tests/fake_stata_home, StataCorp 제품 아님)로 통신 규약 전체를 확인.

사용: python tests/legacy/run_pystata_check.py   (종료 코드 0 = 통과)
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
FAKE_HOME = os.path.join(ROOT, "tests", "fake_stata_home")
SCRIPT_SRC = os.path.join(ROOT, "mcp_server", "stata_agent", "backends", "pystata_proc.py")


def worker_script():
    with io.open(SCRIPT_SRC, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"WORKER_SCRIPT = r'''(.*?)'''", text, re.S)
    if not m:
        raise SystemExit("WORKER_SCRIPT not found")
    return m.group(1)


def main():
    work = tempfile.mkdtemp(prefix="sa_pystata_legacy_")
    try:
        home = os.path.join(work, "Stata18")
        shutil.copytree(FAKE_HOME, home)
        script = os.path.join(work, "worker.py")
        with io.open(script, "w", encoding="utf-8") as f:
            f.write(worker_script())
        proc = subprocess.Popen([sys.executable, script, home, "se"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=work)

        def wait_for(marker):
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise SystemExit("worker exited before %r; stderr=%r" % (marker, proc.stderr.read()[-2000:]))
                line = line.decode("ascii", "replace").strip()
                if line == marker or line.startswith("__SA_FAIL__"):
                    return line
                raise SystemExit("unexpected stdout line (noise leaked): %r" % line)

        def request(rid, op, **payload):
            resp = os.path.join(work, "resp_%d.json" % rid)
            req = dict(payload, id=rid, op=op, resp=resp)
            proc.stdin.write((json.dumps(req) + "\n").encode("ascii"))
            proc.stdin.flush()
            wait_for("__SA_DONE__ %d" % rid)
            with io.open(resp, encoding="utf-8") as f:
                return json.load(f)

        def run(rid, code):
            do = os.path.join(work, "c%d.do" % rid)
            with io.open(do, "w", encoding="utf-8") as f:
                f.write(code)
            log = os.path.join(work, "c%d.log" % rid)
            r = request(rid, "run", do=do.replace("\\", "/"), log=log.replace("\\", "/"), cwd=work.replace("\\", "/"))
            with io.open(log, encoding="utf-8") as f:
                return r, f.read()

        first = wait_for("__SA_READY__")
        assert first == "__SA_READY__", first
        assert request(1, "ping")["ok"]
        r, log = run(2, u"* 한글 주석\nscalar keep = 7\n")
        assert r["ok"], r
        r, log = run(3, u"display scalar(keep)\n")
        assert r["ok"] and "\n7\n" in log, (r, log)
        r, log = run(4, u"force_error\n")
        assert not r["ok"] and "r(111);" in log and "SystemError" in r["error"], (r, log)
        r, log = run(5, u'graph export "fig.png", replace\n')
        assert r["ok"] and os.path.isfile(os.path.join(work, "fig.png")), (r, log)
        assert request(6, "ping")["ok"]
        proc.stdin.write(b'{"op": "exit"}\n')
        proc.stdin.flush()
        proc.wait()
        print("legacy pystata worker check passed on Python %s" % sys.version.split()[0])
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
