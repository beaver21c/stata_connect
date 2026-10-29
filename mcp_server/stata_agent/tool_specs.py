"""MCP 도구 명세(설계서 §7) — 서버·클라이언트 권한 설정·프로젝트 템플릿이 공유하는 단일 원본.

read_only=True → 자동 허용 대상(클라이언트 설정의 allow / Codex approval_mode="approve")
read_only=False → 승인 필요(ask / prompt)
"""

from __future__ import annotations

from dataclasses import dataclass, field

SERVER_NAME = "stata"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    read_only: bool
    properties: dict = field(default_factory=dict)
    required: tuple[str, ...] = ()

    def input_schema(self) -> dict:
        schema: dict = {"type": "object", "properties": self.properties}
        if self.required:
            schema["required"] = list(self.required)
        return schema


_ACK = {
    "type": "boolean",
    "description": "guard가 '승인 필요'로 판정한 위험을 연구자가 확인했을 때만 true. 연구자에게 사유를 설명하고 동의를 받은 뒤 사용",
}
_SECTIONS = {
    "type": "array",
    "description": "섹션 목록(순서대로 S01, S02 …로 번호 부여)",
    "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "섹션 제목(예: 표본 정의)"},
            "code": {"type": "string", "description": "Stata 코드(섹션 표지·_nmlog 로그 명령 제외)"},
        },
        "required": ["title", "code"],
    },
}
_FILENAME = {"type": "string", "description": "프로젝트 폴더 기준 do-file 이름(예: 04_regress.do)"}

TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "stata_status",
        "백엔드·세션·Stata 버전·라이선스 유효성·COM 등록 상태 조회(읽기 전용). 일련번호·등록자는 반환하지 않음.",
        True,
        {"refresh": {"type": "boolean", "description": "Stata 설치·라이선스를 다시 탐지(about 배치 실행, 수십 초 소요 가능)"}},
    ),
    ToolSpec(
        "stata_selftest",
        "자가 점검 T1~T10 실행 후 결과표와 점검 보고서(HTML) 생성. Stata 내장 auto.dta만 사용, 사용자 자료 미사용. 점검용 Stata 창이 별도로 열림.",
        True,
        {
            "client_name": {"type": "string", "description": "사용 중인 앱 이름(예: Claude Desktop, Codex)"},
            "include_batch": {"type": "boolean", "description": "T9 배치 재현 점검 포함(기본 true)"},
        },
    ),
    ToolSpec(
        "stata_open_session",
        "프로젝트 폴더를 작업 폴더로 하는 가시 Stata 창(세션) 1개를 열거나 재사용. 폴더 규약(output/logs 등)이 없으면 생성. 다른 도구보다 먼저 호출.",
        False,
        {
            "project_dir": {"type": "string", "description": "프로젝트 폴더 절대경로"},
            "session_id": {"type": "string", "description": "세션 이름(생략 시 폴더명)"},
        },
        ("project_dir",),
    ),
    ToolSpec(
        "stata_load_data",
        "자료를 불러오고 describe, short 수준 요약(관측치 수·변수 수)만 반환. 관측치 값은 반환하지 않음. 'sysuse:auto' 형식으로 Stata 예제 자료 사용 가능.",
        False,
        {"path": {"type": "string", "description": "자료 파일 경로(.dta) 또는 sysuse:이름"}},
        ("path",),
    ),
    ToolSpec(
        "stata_schema",
        "현재 자료의 변수명·유형·변수 라벨·값 라벨 이름·결측 수·관측치 수만 반환. 표본 행·값 예시 미포함.",
        True,
    ),
    ToolSpec(
        "stata_write_dofile",
        "규약 헤더(version·로그)와 섹션 표지를 갖춘 do-file 신규 작성 + 00_master.do 목록 자동 갱신. 실행하지 않음.",
        False,
        {
            "filename": _FILENAME,
            "sections": _SECTIONS,
            "author": {"type": "string", "description": "헤더 '작성' 표기(예: AI(사용 모델명))"},
            "overwrite": {"type": "boolean", "description": "같은 이름 파일이 있을 때 백업 후 덮어쓰기"},
        },
        ("filename", "sections"),
    ),
    ToolSpec(
        "stata_patch_dofile",
        "섹션 단위 추가·교체·삭제(변경 전 .stata-agent/backups에 백업). 원 결과 섹션은 지우지 말고 수정 섹션을 추가하는 것이 원칙.",
        False,
        {
            "filename": _FILENAME,
            "action": {"type": "string", "enum": ["add", "replace", "delete"]},
            "section_id": {"type": "string", "description": "대상 섹션(예: S03). add에서는 생략 시 다음 번호"},
            "title": {"type": "string"},
            "code": {"type": "string"},
            "after": {"type": "string", "description": "add 위치: 이 섹션 뒤(생략 시 맨 끝)"},
        },
        ("filename", "action"),
    ),
    ToolSpec(
        "stata_show_in_editor",
        "Stata Do-file Editor에 파일을 열거나 다시 표시(F3).",
        True,
        {"filename": _FILENAME},
        ("filename",),
    ),
    ToolSpec(
        "stata_run_section",
        "지정 섹션만 현재 세션에서 실행하고 필터를 거친 로그 반환. 실행 전 guard 검사.",
        False,
        {"filename": _FILENAME, "section_id": {"type": "string"}, "acknowledge_risks": _ACK},
        ("filename", "section_id"),
    ),
    ToolSpec(
        "stata_run_dofile",
        "do-file 전체를 현재 세션에서 실행(호출하는 하위 do-file까지 guard 검사)하고 필터를 거친 로그 반환.",
        False,
        {"filename": _FILENAME, "acknowledge_risks": _ACK},
        ("filename",),
    ),
    ToolSpec(
        "stata_read_log",
        "최근 실행 로그 또는 output/logs의 로그를 출력 필터를 거쳐 반환.",
        True,
        {
            "name": {"type": "string", "description": "output/logs 안 로그 파일명(생략 시 최근 실행 로그)"},
            "tail_lines": {"type": "integer", "description": "마지막 N줄만"},
            "format": {"type": "string", "enum": ["text", "dict"], "description": "dict=명령·결과 쌍 JSON"},
        },
    ),
    ToolSpec(
        "stata_get_results",
        "저장결과 조회(해석 수치 대조용). names 예: e(r2), e(N), r(mean), _b[weight], _se[weight], 스칼라명. names 없이 kind=r|e면 return/ereturn list.",
        True,
        {
            "names": {"type": "array", "items": {"type": "string"}},
            "kind": {"type": "string", "enum": ["r", "e"]},
        },
    ),
    ToolSpec(
        "stata_export",
        "논문형 표 산출: mode=etable이면 저장된 추정결과(estimates store 이름)를 etable로 output/tables에 내보냄(Stata 17+). mode=custom이면 collect·putdocx 코드를 guard 검사 후 실행.",
        False,
        {
            "mode": {"type": "string", "enum": ["etable", "custom"]},
            "estimates": {"type": "array", "items": {"type": "string"}},
            "filename": {"type": "string", "description": "output/tables 안 파일명(.docx/.xlsx/.html/.tex/.md)"},
            "code": {"type": "string", "description": "mode=custom일 때 Stata 코드"},
            "acknowledge_risks": _ACK,
        },
        ("mode",),
    ),
    ToolSpec(
        "stata_reproduce",
        "배치 모드로 00_master.do 별도 실행 → 대화형 실행 로그(output/logs)와 수치 비교 보고(재현 일치/불일치 n건).",
        False,
        {"master": {"type": "string", "description": "기본 00_master.do"}},
    ),
    ToolSpec(
        "stata_break",
        "장시간 실행 중단 요청(현재 래퍼 구조에서는 미구현 → 중단 방법 안내 반환).",
        True,
    ),
    ToolSpec(
        "stata_install_package",
        "외부 패키지 설치(ssc install 또는 net install). 네트워크 사용.",
        False,
        {
            "package": {"type": "string"},
            "source": {"type": "string", "enum": ["ssc", "net"]},
            "from_url": {"type": "string", "description": "net install의 from() 주소"},
        },
        ("package",),
    ),
    ToolSpec(
        "stata_usage_summary",
        "AI 사용 기록(.stata-agent/history.jsonl) 집계와 논문 Method 절 공개문 초안 반환(P6).",
        True,
        {"client_name": {"type": "string"}},
    ),
)

TOOL_BY_NAME = {t.name: t for t in TOOLS}
READ_ONLY_TOOLS = tuple(t.name for t in TOOLS if t.read_only)
APPROVAL_TOOLS = tuple(t.name for t in TOOLS if not t.read_only)


def client_tool_id(name: str, server: str = SERVER_NAME) -> str:
    """Claude Code 권한 규칙용 도구 식별자(mcp__서버__도구)."""
    return f"mcp__{server}__{name}"
