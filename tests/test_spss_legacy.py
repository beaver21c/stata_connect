"""SPSS 22~26 대비: 엔진 스크립트·가짜 spss 모듈·구버전 점검 스크립트가 Python 2.7·3.4 문법 범위인지 정적 검사.

실제 실행 검사는 CI 작업 spss-legacy-python(python:2.7·python:3.4 이미지에서 tests/legacy/run_engine_check.py).
근거: SPSS 22·23은 Python 2.7, 24~26은 2.7·3.4 동봉 [2차 확인: IBM 문서 검색 요약].
"""

import ast
import re
from pathlib import Path

import pytest

from spss_agent.engine_script import ENGINE_SCRIPT

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "engine_script": ENGINE_SCRIPT,
    "fake_spss": (ROOT / "tests/fake_spss_home/Python3/Lib/site-packages/spss.py").read_text(encoding="utf-8"),
    "legacy_driver": (ROOT / "tests/legacy/run_engine_check.py").read_text(encoding="utf-8"),
}


def _problems(src: str) -> list[str]:
    tree = ast.parse(src)
    out = []
    in_try: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for sub in node.body:
                for n in ast.walk(sub):
                    in_try.add(id(n))
    has_print_future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
                           and any(a.name == "print_function" for a in n.names) for n in ast.walk(tree))
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.JoinedStr):
            out.append(f"{line}: f-문자열(3.6+)")
        elif isinstance(node, (ast.AnnAssign, ast.Nonlocal, ast.NamedExpr, ast.YieldFrom, ast.Await,
                               ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith)):
            out.append(f"{line}: {type(node).__name__}(Python 3 전용)")
        elif isinstance(node, (ast.FunctionDef, ast.Lambda)):
            args = node.args
            if args.kwonlyargs or getattr(args, "posonlyargs", []):
                out.append(f"{line}: 키워드 전용·위치 전용 인자")
            if any(a.annotation is not None for a in args.args) or getattr(node, "returns", None) is not None:
                out.append(f"{line}: 형 주석")
        elif isinstance(node, ast.Raise) and node.cause is not None:
            out.append(f"{line}: raise ... from")
        elif isinstance(node, ast.Dict) and any(k is None for k in node.keys):
            out.append(f"{line}: 사전 펼치기 {{**a}}(3.5+)")
        elif isinstance(node, (ast.Assign, ast.For)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(n, ast.Starred) for t in targets for n in ast.walk(t)):
                out.append(f"{line}: 별표 대입(3.0+)")
        elif isinstance(node, ast.Call):
            f = node.func
            kws = {k.arg for k in node.keywords}
            if isinstance(f, ast.Name) and f.id == "open" and "encoding" in kws:
                out.append(f"{line}: open(encoding=) → io.open 사용")
            if isinstance(f, ast.Attribute) and f.attr == "fdopen" and "encoding" in kws:
                out.append(f"{line}: os.fdopen(encoding=)")
            if "exist_ok" in kws:
                out.append(f"{line}: exist_ok(3.2+)")
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "subprocess" \
                    and f.attr in ("run", "DEVNULL"):
                out.append(f"{line}: subprocess.{f.attr}(3.3+/3.5+)")
            if isinstance(f, ast.Attribute) and f.attr == "reconfigure" and id(node) not in in_try:
                out.append(f"{line}: reconfigure는 try 안에서만(3.7+)")
            if isinstance(f, ast.Name) and f.id == "print" and not has_print_future and len(node.args) != 1:
                out.append(f"{line}: print 여러 인자(2.7은 print_function 필요)")
            if sum(1 for k in node.keywords if k.arg is None) > 1:
                out.append(f"{line}: ** 여러 번(3.5+)")
    if any(ord(c) > 127 for c in src):
        head = src.lstrip("\n").splitlines()[:2] if src.startswith("\n") else src.splitlines()[:2]
        if not any(re.search(r"coding[:=]\s*utf-?8", h) for h in head):
            out.append("비ASCII 문자 있음 → 첫 두 줄에 '# -*- coding: utf-8 -*-' 필요(2.7)")
    return out


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_python27_34_syntax_subset(name):
    assert _problems(SOURCES[name]) == []


def test_checker_catches_examples():
    bad = 'x = f"{1}"\ndef g(*, a): pass\nopen("p", encoding="utf-8")\nimport sys\nsys.stdin.reconfigure(encoding="utf-8")\n'
    found = "\n".join(_problems(bad))
    assert "f-문자열" in found and "키워드 전용" in found and "open(encoding=)" in found and "reconfigure" in found
    assert "coding" in "\n".join(_problems('s = "한글"\n'))


def test_engine_reads_stdin_line_by_line():
    """2.7의 `for line in sys.stdin`은 미리 읽기 버퍼로 요청이 늦게 처리됨 → readline 반복이어야 함."""
    assert "sys.stdin.readline()" in ENGINE_SCRIPT
    assert not re.search(r"^\s*for \w+ in sys\.stdin", ENGINE_SCRIPT, re.MULTILINE)
