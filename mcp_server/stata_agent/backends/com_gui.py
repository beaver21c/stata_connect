"""COM GUI 백엔드 — stata-gui-mcp(pip 의존성) 래퍼.

상류 패키지(shichengg/stata-mcp, MIT)의 COM 세션 관리·실행·로그 반환을 그대로 쓰고,
도구 목록은 노출하지 않음(원자료 표본 행을 출력하는 ``stata_get_data_schema`` 등 차단 목적).

상류는 공개 API가 없어 내부 함수에 의존함 → 버전을 고정하고(REQUIRED_UPSTREAM_VERSION)
기동 시 필요한 내부 심볼이 모두 있는지 점검함. 상류를 올릴 때는 tests/test_upstream_compat.py와
docs/IMPLEMENTATION_STATUS.md의 "상류 의존 목록"을 함께 갱신할 것.

상류 동작(1.1.0 소스 확인)
- 세션 작업 스레드가 ``app.DoCommand(command)``만 중계 → COM 결과 메서드(StReturnNumeric 등) 직접 호출 불가
- 세션은 do-file 실행으로 생성되고, 레지스트리는 do-file 폴더의 ``.stata-mcp/cache``에 기록
- 여러 줄 코드는 임시 do-file로 실행(루프·program define 가능)
"""

from __future__ import annotations

import importlib
import importlib.metadata
import re
from pathlib import Path
from types import ModuleType

from ..discovery import com_registration
from ..guard.output_filter import last_return_code
from .base import Backend, RunOutcome, stata_path

UPSTREAM_DIST = "stata-gui-mcp"
UPSTREAM_MODULE = "stata_mcp.server"
REQUIRED_UPSTREAM_VERSION = "1.1.0"
REQUIRED_SYMBOLS = (
    "PYWIN32_READY",
    "PYWIN32_ERROR",
    "SESSIONS",
    "StataSession",
    "_run_dofile_session",
    "_run_stata_commands",
    "_session_transaction",
    "_registry_for_session",
    "_update_task_registry",
    "_session_tool",
)

# 상류 오류 문구(중국어) → 한국어 안내
_UPSTREAM_MESSAGES = (
    ("pywin32 未安装", "pywin32 미설치 또는 불러오기 실패"),
    ("当前没有可用的 Stata do 文件会话", "사용 가능한 Stata 세션 없음 → stata_open_session 먼저 실행"),
    ("没有当前 session 的项目目录", "세션 프로젝트 폴더 미설정 → stata_open_session 먼저 실행"),
    ("Stata 执行超时", "Stata 실행 시간 초과(180초) → 세션이 새 명령을 받지 않음, stata_open_session 재실행 필요"),
    ("检测到 Stata GUI/COM 断开", "Stata 창/COM 연결 끊김 → 빈 세션으로 재연결됨(자료·추정결과 소실, 중단 명령 미재실행)"),
    ("do 文件发送失败", "do-file 전송 실패"),
    ("命令执行失败", "명령 실행 실패"),
    ("Stata COM session startup timed out", "Stata COM 세션 기동 시간 초과(라이선스·COM 등록 확인)"),
)


class UpstreamIncompatible(RuntimeError):
    pass


def load_upstream(check_version: bool = True) -> ModuleType:
    try:
        version = importlib.metadata.version(UPSTREAM_DIST)
    except importlib.metadata.PackageNotFoundError as e:
        raise UpstreamIncompatible(f"{UPSTREAM_DIST} 미설치: pip install {UPSTREAM_DIST}=={REQUIRED_UPSTREAM_VERSION}") from e
    if check_version and version != REQUIRED_UPSTREAM_VERSION:
        raise UpstreamIncompatible(
            f"{UPSTREAM_DIST} {version} 설치됨, 래퍼 검증 버전은 {REQUIRED_UPSTREAM_VERSION} "
            "→ 내부 함수 변경 가능성. 버전 고정 설치 또는 래퍼 갱신 필요"
        )
    module = importlib.import_module(UPSTREAM_MODULE)
    missing = [s for s in REQUIRED_SYMBOLS if not hasattr(module, s)]
    if missing:
        raise UpstreamIncompatible(f"상류 내부 심볼 누락: {', '.join(missing)}")
    return module


def translate_upstream(text: str) -> str:
    notes = [ko for zh, ko in _UPSTREAM_MESSAGES if zh in text]
    if not notes:
        return text
    return " / ".join(notes) + f"\n(상류 원문: {text.strip()[:300]})"


def parse_upstream_result(text: str) -> RunOutcome:
    """상류 ``_format_run_result`` 문자열 → RunOutcome. 로그는 파일에서 전체를 다시 읽음."""
    if "=== Stata output ===" not in text:
        return RunOutcome(False, message=translate_upstream(text))
    head = text.split("=== Stata output ===", 1)[0]
    m = re.search(r"^log_path:\s*(.+)$", head, re.MULTILINE)
    log_path = Path(m.group(1).strip()) if m else None
    log_text = ""
    if log_path and log_path.is_file():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    else:
        log_text = text.split("=== Stata output ===", 1)[1]
    rc_m = re.search(r"^return_code:\s*(\d+)", head, re.MULTILINE)
    rc = int(rc_m.group(1)) if rc_m else last_return_code(log_text)
    return RunOutcome(rc == 0, rc, log_text, log_path, "" if rc == 0 else f"Stata 오류 r({rc})")


SESSION_INIT_DO = """\
* stata-agent 세션 초기화(자동 생성, 수정 불필요)
display "stata-agent session ready"
display "SA_VERSION|" c(stata_version)
"""


class ComGuiBackend(Backend):
    name = "com_gui"
    persistent_session = True

    def __init__(self, upstream: ModuleType | None = None):
        self._upstream = upstream
        self._load_error: str | None = None
        self._project_roots: dict[str, Path] = {}

    @property
    def up(self) -> ModuleType:
        if self._upstream is None:
            self._upstream = load_upstream()
        return self._upstream

    def available(self) -> tuple[bool, str]:
        try:
            up = self.up
        except UpstreamIncompatible as e:
            return False, str(e)
        if not up.PYWIN32_READY:
            return False, f"pywin32 사용 불가({up.PYWIN32_ERROR}) — Windows 전용"
        reg = com_registration()
        if not reg.registered:
            return False, f"Stata COM 미등록: {reg.error} → 관리자 권한으로 installer/register_com.ps1 실행"
        return True, ""

    def _reset_working_dir(self, session_id: str, project_root: Path) -> None:
        registry_path, _ = self.up._registry_for_session(session_id)
        if registry_path:
            self.up._update_task_registry(session_id, registry_path, working_dir=str(project_root))

    def open_session(self, project_root: Path, session_id: str) -> RunOutcome:
        ok, why = self.available()
        if not ok:
            return RunOutcome(False, message=why)
        agent_dir = Path(project_root) / ".stata-agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        init = agent_dir / "session_init.do"
        init.write_text(SESSION_INIT_DO, encoding="utf-8")
        outcome = parse_upstream_result(self.up._run_dofile_session(str(init), session_id, "auxiliary"))
        if outcome.ok:
            self._project_roots[session_id] = Path(project_root)
            self._reset_working_dir(session_id, Path(project_root))
        return outcome

    def run_code(self, code: str, session_id: str, project_root: Path) -> RunOutcome:
        ok, why = self.available()
        if not ok:
            return RunOutcome(False, message=why)
        return parse_upstream_result(self.up._run_stata_commands(code, session_key=session_id))

    def run_dofile(self, path: Path, session_id: str, project_root: Path) -> RunOutcome:
        ok, why = self.available()
        if not ok:
            return RunOutcome(False, message=why)
        outcome = parse_upstream_result(self.up._run_dofile_session(str(path), session_id, "entry"))
        self._reset_working_dir(session_id, Path(project_root))
        return outcome

    def show_in_editor(self, path: Path, session_id: str) -> RunOutcome:
        """``doedit``로 Do-file Editor에 표시. 재호출 시 탭 갱신·중복 여부는 미확인(F3, Phase 0 실측)."""
        ok, why = self.available()
        if not ok:
            return RunOutcome(False, message=why)
        try:
            with self.up._session_transaction(session_id) as session:
                if session is None:
                    return RunOutcome(False, message="세션 없음 → stata_open_session 먼저 실행")
                session.execute(f'doedit "{stata_path(path)}"')
        except Exception as e:  # COM 오류 전달
            return RunOutcome(False, message=f"doedit 실패: {e}")
        return RunOutcome(True, 0, message="Do-file Editor 표시 요청 완료(탭 갱신 방식은 실기 확인 필요)")

    def status(self) -> dict:
        base = super().status()
        try:
            up = self.up
            base["upstream_version"] = importlib.metadata.version(UPSTREAM_DIST)
            base["sessions"] = {
                key: ("ready" if s.is_ready() else f"not ready: {s.error}") for key, s in list(up.SESSIONS.items())
            }
        except UpstreamIncompatible as e:
            base["upstream_error"] = str(e)
        return base
