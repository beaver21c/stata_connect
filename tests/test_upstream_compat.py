"""stata-gui-mcp(상류) 래퍼 호환성. 상류 버전을 올릴 때 반드시 통과해야 함."""

import types
from pathlib import Path

import pytest

from stata_agent.backends import com_gui
from stata_agent.backends.com_gui import (
    REQUIRED_SYMBOLS,
    ComGuiBackend,
    load_upstream,
    parse_upstream_result,
    translate_upstream,
)


def test_installed_upstream_has_required_symbols():
    up = load_upstream()
    for name in REQUIRED_SYMBOLS:
        assert hasattr(up, name), name


def test_upstream_schema_tool_is_not_exposed():
    """상류의 표본 행 출력 도구(stata_get_data_schema)가 우리 도구 목록에 없어야 함."""
    from stata_agent.tool_specs import TOOL_BY_NAME

    assert "stata_get_data_schema" not in TOOL_BY_NAME
    src = Path(load_upstream().__file__).read_text(encoding="utf-8")
    assert "list in 1/" in src  # 상류에 표본 행 출력이 있다는 사실 자체를 고정(변경 시 재검토)


def test_parse_upstream_success(tmp_path):
    log = tmp_path / "run_x.log"
    log.write_text(". summarize price\n       price |  74  6165.257\n", encoding="utf-8")
    text = ("✅ Stata 执行完成\nsession_id: s\nsource: selection\n"
            f"log_path: {log}\nreturn_code: 0\noutput_truncated: false\n\n=== Stata output ===\n(tail)")
    out = parse_upstream_result(text)
    assert out.ok and out.return_code == 0 and "6165.257" in out.log_text and out.log_path == log


def test_parse_upstream_error_translated():
    out = parse_upstream_result("❌ 当前没有可用的 Stata do 文件会话。\n...")
    assert not out.ok and "stata_open_session" in out.message
    assert "상류 원문" in translate_upstream("❌ Stata 执行超时；x")


class _Session:
    def __init__(self):
        self.commands = []

    def execute(self, cmd):
        self.commands.append(cmd)


def _fake_upstream(tmp_path):
    calls = {"updates": []}
    session = _Session()
    log = tmp_path / "run.log"
    log.write_text("stata-agent session ready\nSA_VERSION|18\n", encoding="utf-8")
    ok = f"✅\nlog_path: {log}\nreturn_code: 0\n\n=== Stata output ===\n"

    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *a):
            return False

    up = types.SimpleNamespace(
        PYWIN32_READY=True, PYWIN32_ERROR="", SESSIONS={},
        _run_dofile_session=lambda path, sid, role: calls.setdefault("dofile", []).append((path, sid, role)) or ok,
        _run_stata_commands=lambda code, session_key=None: calls.setdefault("code", []).append((code, session_key)) or ok,
        _session_transaction=lambda sid: _Ctx(),
        _registry_for_session=lambda sid: (tmp_path / "reg.json", {}),
        _update_task_registry=lambda sid, path, **kw: calls["updates"].append(kw),
    )
    return up, calls, session


def test_com_backend_flow_with_fake_upstream(tmp_path, monkeypatch):
    up, calls, session = _fake_upstream(tmp_path)
    monkeypatch.setattr(com_gui, "com_registration", lambda: types.SimpleNamespace(registered=True, error=None))
    b = ComGuiBackend(upstream=up)
    root = tmp_path / "proj"
    root.mkdir()
    out = b.open_session(root, "s1")
    assert out.ok
    assert calls["dofile"][0][0].endswith("session_init.do") and calls["dofile"][0][2] == "auxiliary"
    assert calls["updates"][-1] == {"working_dir": str(root)}  # 작업 폴더를 프로젝트 루트로 재설정
    assert b.run_code("summarize", "s1", root).ok
    assert calls["code"][-1] == ("summarize", "s1")
    assert b.show_in_editor(root / "01_a.do", "s1").ok
    assert session.commands[-1].startswith('doedit "') and session.commands[-1].endswith('01_a.do"')


def test_com_backend_unavailable_without_pywin32(tmp_path):
    up, *_ = _fake_upstream(tmp_path)
    up.PYWIN32_READY = False
    up.PYWIN32_ERROR = "No module named win32com"
    ok, why = ComGuiBackend(upstream=up).available()
    assert not ok and "pywin32" in why


def test_version_mismatch_detected(monkeypatch):
    monkeypatch.setattr(com_gui.importlib.metadata, "version", lambda name: "9.9.9")
    with pytest.raises(com_gui.UpstreamIncompatible):
        load_upstream()
