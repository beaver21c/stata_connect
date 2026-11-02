"""재설치(§18): 같은 설치 도우미를 다시 받아 다시 실행해도 앞선 설치 상태와 무관하게 정상으로 맞춰지는지.

배경(2026-11-02 사용자 요구): 배포하면 설치 → 실패 → 재설치가 자주 일어남. conftest 격리로 실제 사용자 설정은 건드리지 않음.
"""

import json
import os
import sys

import pytest

from stata_agent import setup_wizard
from stata_agent import dc_guard


def test_install_self_replaces_running_copy(tmp_path, monkeypatch):
    src = tmp_path / "dl" / "stata-agent-0.2.0.exe"
    src.parent.mkdir()
    src.write_bytes(b"new")
    dest = tmp_path / "StataAgent" / "stata-agent.exe"
    dest.parent.mkdir()
    dest.write_bytes(b"old")
    real_replace = os.replace

    def windows_like(a, b):  # Windows: 실행 중인 파일 덮어쓰기 금지(이름 바꾸기는 허용)
        if os.path.exists(b) and open(b, "rb").read() == b"old":
            raise PermissionError("in use")
        return real_replace(a, b)

    monkeypatch.setattr(setup_wizard.os, "replace", windows_like)
    exe, msg = setup_wizard.install_self(src=src, dest=dest)
    assert exe == dest and dest.read_bytes() == b"new" and "다시 시작" in msg
    olds = list(dest.parent.glob("stata-agent.old-*.exe"))
    assert len(olds) == 1 and olds[0].read_bytes() == b"old"
    assert not list(dest.parent.glob("*.new-*"))  # 임시 파일 남기지 않음
    monkeypatch.setattr(setup_wizard.os, "replace", real_replace)
    exe, msg = setup_wizard.install_self(src=src, dest=dest)  # 다음 재설치: 옛 사본 정리
    assert not list(dest.parent.glob("stata-agent.old-*.exe")) and "다시 시작" not in msg


def test_install_self_reports_when_rename_also_fails(tmp_path, monkeypatch):
    src = tmp_path / "a.exe"
    src.write_bytes(b"new")
    dest = tmp_path / "inst" / "stata-agent.exe"
    dest.parent.mkdir()
    dest.write_bytes(b"old")
    monkeypatch.setattr(setup_wizard.os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError("x")))
    monkeypatch.setattr(type(dest), "rename", lambda self, t: (_ for _ in ()).throw(PermissionError("x")))
    exe, msg = setup_wizard.install_self(src=src, dest=dest)
    assert exe is None and "완전히 종료" in msg and dest.read_bytes() == b"old"
    assert not list(dest.parent.glob("*.new-*"))


def test_full_setup_twice_is_clean(tmp_path, monkeypatch):
    """1회차 설치 → 2회차 재설치: 오류 없음, 같은 설정은 '이미 등록됨', 백업이 쌓이지 않음."""
    monkeypatch.setattr(sys, "platform", "win32")
    pkg = os.path.join(os.environ["LOCALAPPDATA"], "Packages", "Claude_pzs8sxrjxfjjc")
    os.makedirs(pkg)
    dc = dc_guard.dc_config_path()
    dc.parent.mkdir(parents=True)
    dc.write_text(json.dumps({"blockedCommands": ["reg", "net"]}), encoding="utf-8")
    from test_packaging import _fake_report

    monkeypatch.setattr(setup_wizard, "discover", lambda **kw: _fake_report(registered=True))
    monkeypatch.setattr(setup_wizard.shutil, "which", lambda name: None)  # Linux에서 Windows 흉내 → 명령 검색 생략
    monkeypatch.setattr(setup_wizard, "codex_home", lambda: tmp_path / "nocodex")
    opts = setup_wizard.SetupOptions(yes=True, com="no", install=False, skill=False)
    first: list[str] = []
    r1 = setup_wizard.run_setup(opts, out=first.append)
    assert not r1.errors, "\n".join(first)
    cfg_dir = os.path.join(pkg, "LocalCache", "Roaming", "Claude")
    before = sorted(os.listdir(cfg_dir)) + sorted(os.listdir(dc.parent))
    second: list[str] = []
    r2 = setup_wizard.run_setup(opts, out=second.append)
    text = "\n".join(second)
    assert not r2.errors, text
    assert "Claude 앱(Microsoft Store판): 이미 등록됨" in text and "이미 설정됨" in text
    assert sorted(os.listdir(cfg_dir)) + sorted(os.listdir(dc.parent)) == before  # 재설치로 백업이 늘지 않음


@pytest.mark.parametrize("broken", ["{", ""])
def test_reinstall_over_broken_or_empty_claude_config(tmp_path, monkeypatch, broken):
    """앞선 시도·다른 프로그램이 남긴 빈 파일은 새로 쓰고, 깨진 JSON은 손대지 않고 알림."""
    monkeypatch.setattr(sys, "platform", "win32")
    roaming = os.environ["APPDATA"]
    os.makedirs(os.path.join(roaming, "Claude"))
    cfg = os.path.join(roaming, "Claude", "claude_desktop_config.json")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(broken)
    from stata_agent.client_config import ServerCommand, configure_all

    c = configure_all(ServerCommand("x.exe", ["serve"]), tmp_path, ["claude-desktop"], install_skills=False)[0]
    if broken:
        assert c.action == "error" and open(cfg, encoding="utf-8").read() == broken
    else:
        assert c.action in ("created", "updated")
        assert json.load(open(cfg, encoding="utf-8"))["mcpServers"]["stata"]["command"] == "x.exe"
