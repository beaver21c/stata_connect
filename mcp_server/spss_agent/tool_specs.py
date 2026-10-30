"""SPSS MCP 도구 명세(서버 이름 ``spss``) — 서버·클라이언트 권한 설정·프로젝트 템플릿의 단일 원본.

Stata판과 차이: SPSS에는 r()/e() 같은 저장결과가 없어 결과는 출력(OMS 텍스트)에서 인용,
화면 없는 실행이라 편집기 표시·실행 중단 도구 없음.
"""

from __future__ import annotations

from stata_agent.client_config import ClientProfile
from stata_agent.tool_specs import ToolSpec

SERVER_NAME = "spss"
SKILL_NAME = "spss-analysis"

_ACK = {
    "type": "boolean",
    "description": "guard가 '승인 필요'로 판정한 위험을 연구자가 확인했을 때만 true. 사유를 설명하고 동의를 받은 뒤 사용",
}
_FILENAME = {"type": "string", "description": "프로젝트 폴더 기준 문법 파일 이름(예: 04_regress.sps)"}
_SECTIONS = {
    "type": "array",
    "description": "섹션 목록(순서대로 S01, S02 …). 각 명령은 마침표로 끝낼 것",
    "items": {
        "type": "object",
        "properties": {"title": {"type": "string"}, "code": {"type": "string", "description": "SPSS 문법(섹션 표지 제외)"}},
        "required": ["title", "code"],
    },
}

TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec("spss_status", "SPSS 설치·엔진·세션 상태 조회(읽기 전용).", True,
             {"refresh": {"type": "boolean", "description": "설치 탐지 다시 실행"}}),
    ToolSpec("spss_selftest",
             "자가 점검 T1~T10 실행 후 결과표와 점검 보고서(HTML) 생성. 문법 안에서 만든 예제 자료만 사용, 사용자 자료 미사용.",
             True, {"client_name": {"type": "string"}, "include_batch": {"type": "boolean"}}),
    ToolSpec("spss_open_session",
             "프로젝트 폴더를 작업 폴더로 화면 없는 SPSS 엔진(세션)을 기동하거나 재사용. 폴더 규약이 없으면 생성. 가장 먼저 호출.",
             False, {"project_dir": {"type": "string", "description": "프로젝트 폴더 절대경로"}}, ("project_dir",)),
    ToolSpec("spss_load_data", "SPSS 자료(.sav)를 불러오고 사례 수·변수 수만 반환. 관측치 값은 반환하지 않음.",
             False, {"path": {"type": "string", "description": ".sav 파일 경로(프로젝트 기준 상대경로 가능)"}}, ("path",)),
    ToolSpec("spss_schema", "현재 자료의 변수명·라벨·유형·측정수준·결측 수·사례 수만 반환. 사례 값 미포함.", True),
    ToolSpec("spss_write_syntax", "규약 머리말과 섹션 표지를 갖춘 .sps 파일 신규 작성 + 00_master.sps 갱신. 실행하지 않음.",
             False, {"filename": _FILENAME, "sections": _SECTIONS,
                     "author": {"type": "string"}, "overwrite": {"type": "boolean"}}, ("filename", "sections")),
    ToolSpec("spss_patch_syntax", "섹션 단위 추가·교체·삭제(변경 전 .spss-agent/backups에 백업). 원 결과 섹션은 지우지 말고 수정 섹션 추가가 원칙.",
             False, {"filename": _FILENAME, "action": {"type": "string", "enum": ["add", "replace", "delete"]},
                     "section_id": {"type": "string"}, "title": {"type": "string"}, "code": {"type": "string"},
                     "after": {"type": "string"}}, ("filename", "action")),
    ToolSpec("spss_run_section", "지정 섹션만 현재 세션에서 실행하고 필터를 거친 출력 반환. 실행 전 guard 검사.",
             False, {"filename": _FILENAME, "section_id": {"type": "string"}, "acknowledge_risks": _ACK},
             ("filename", "section_id")),
    ToolSpec("spss_run_syntax_file", "문법 파일 전체를 현재 세션에서 실행(INSERT 하위 파일까지 guard 검사), 출력은 output/logs/NN_result.txt.",
             False, {"filename": _FILENAME, "acknowledge_risks": _ACK}, ("filename",)),
    ToolSpec("spss_read_output", "최근 실행 출력 또는 output/logs의 출력 파일을 필터를 거쳐 반환.", True,
             {"name": {"type": "string", "description": "output/logs 안 .txt 파일명(생략 시 최근 실행)"},
              "tail_lines": {"type": "integer"}}),
    ToolSpec("spss_export", "지정 섹션을 다시 실행하며 표를 output/tables에 Word·Excel·HTML·PDF로 저장(OMS).", False,
             {"filename": _FILENAME, "section_id": {"type": "string"},
              "output": {"type": "string", "description": "output/tables 안 파일명(.docx/.xlsx/.html/.pdf)"},
              "acknowledge_risks": _ACK}, ("filename", "section_id", "output")),
    ToolSpec("spss_reproduce", "새 SPSS 엔진에서 00_master.sps 목록 순서대로 다시 실행 → 대화형 출력(output/logs)과 수치 비교 보고.", False),
    ToolSpec("spss_usage_summary", "AI 사용 기록(.spss-agent/history.jsonl) 집계와 논문 연구방법 절 공개문 초안 반환.", True,
             {"client_name": {"type": "string"}}),
)

TOOL_BY_NAME = {t.name: t for t in TOOLS}
READ_ONLY_TOOLS = tuple(t.name for t in TOOLS if t.read_only)
APPROVAL_TOOLS = tuple(t.name for t in TOOLS if not t.read_only)
PROFILE = ClientProfile(SERVER_NAME, SKILL_NAME, READ_ONLY_TOOLS, APPROVAL_TOOLS)
