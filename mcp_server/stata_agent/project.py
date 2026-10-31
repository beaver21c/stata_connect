"""프로젝트 폴더 규약(설계서 §10) 생성 + 프로젝트 지침 파일 렌더링.

plugins/stata-agent/skills/stata-analysis/templates/ 의 파일은 이 모듈 출력과 같아야 함
(tests/test_templates_sync.py가 검사, 갱신은 ``stata-agent render-templates``).
"""

from __future__ import annotations

import json
from pathlib import Path

from .dofile import MASTER_NAME, new_dofile, render_master
from .tool_specs import APPROVAL_TOOLS, READ_ONLY_TOOLS, client_tool_id

DIRS = ("data", "output/logs", "output/tables", ".stata-agent")

PROJECT_INSTRUCTIONS = """\
# Stata 분석 프로젝트 지침 (AGENTS.md / CLAUDE.md 공통)

이 폴더는 stata-agent 규약을 따르는 Stata 분석 프로젝트임. AI는 아래 원칙을 지킴.

## 원칙
- P1 계산 주체: 모든 통계량은 Stata가 산출. AI는 코드 작성·로그 판독·해석만 담당하며 수치를 직접 계산·추정해 보고하지 않음.
- P2 원자료 비전송: `data/` 폴더 파일을 읽기 도구·셸·스크립트로 열지 않음. 자료 구조는 `stata_schema`로만 파악.
- P3 사람 승인: 실행·쓰기 도구는 연구자 승인 후 실행. guard가 '승인 필요'로 판정하면 사유를 설명하고 동의를 받은 뒤에만 `acknowledge_risks=true` 사용.
- P4 가시성: 분석은 AI가 연 Stata 창에서 진행(연구자가 먼저 연 창에는 연결 불가).
- P5 재현성: 모든 분석은 do-file 섹션으로 남기고, 마무리 때 `stata_reproduce`로 `00_master.do` 배치 재실행 결과를 대조.
- P6 투명성: 분석 종료 시 `stata_usage_summary`로 AI 사용 공개문 초안을 제시.

## 폴더
- `00_master.do`: 전체 재현 진입점(자동 갱신)
- `NN_이름.do`: 분석 단계별 do-file(섹션 표지 `*== [S01] 제목 ==*`)
- `data/`: 원자료(읽기 전용, AI 미열람)
- `output/logs/NN_result.log`: do-file 전체 실행 로그
- `output/tables/`: 표 산출물
- `.stata-agent/`: 세션 기록·백업(수정 금지)

## 해석 규칙
- 해석 문장의 모든 수치는 로그 또는 `stata_get_results` 결과에서 인용하고 출처 섹션(예: 04_regress.do S02)을 표기.
- 로그 수치와 해석 수치가 다르면 해석을 보류하고 다시 조회.
- 원 결과 섹션은 삭제하지 않고 수정 섹션을 추가해 비교.
"""


def claude_settings(hook: list[str] | None = None) -> dict:
    """프로젝트 ``.claude/settings.json`` — data/ 열람 차단 + 읽기 도구 자동 허용 + 실행 도구 확인.

    hook(실행파일 + 인자)이 있으면 셸 명령 실행 전 검사(hookguard)를 실행 형식(command+args)으로 등록.
    Claude Code 공식 문서: Windows의 실행 형식은 command가 실제 .exe여야 함.
    """
    settings: dict = {
        "permissions": {
            "deny": ["Read(/data/**)", "Edit(/data/**)"],
            "allow": [client_tool_id(n) for n in READ_ONLY_TOOLS],
            "ask": [client_tool_id(n) for n in APPROVAL_TOOLS],
        }
    }
    if hook:
        settings["hooks"] = {
            "PreToolUse": [
                {"matcher": "Bash|PowerShell",
                 "hooks": [{"type": "command", "command": hook[0], "args": list(hook[1:])}]}
            ]
        }
    return settings


EXAMPLE_SECTIONS = [
    ("자료 불러오기", "sysuse auto, clear"),
    ("기술통계", "summarize price mpg weight length\ntabstat price mpg, by(foreign) statistics(n mean sd)"),
    ("상관", "pwcorr price mpg weight length, sig obs"),
]


def init_project(root: Path, version_line: str, example: bool = False,
                 hook: list[str] | None = None) -> list[str]:
    """규약 폴더·파일 생성. 기존 파일은 덮어쓰지 않음. 생성한 상대경로 목록 반환."""
    root = Path(root)
    created: list[str] = []
    for d in DIRS:
        p = root / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(d + "/")

    def write_if_absent(rel: str, content: str) -> None:
        p = root / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            created.append(rel)

    if example:
        write_if_absent("01_describe.do", new_dofile("01_describe.do", EXAMPLE_SECTIONS, version_line))
        write_if_absent(MASTER_NAME, render_master(["01_describe.do"], version_line))
    else:
        write_if_absent(MASTER_NAME, render_master([], version_line))
    write_if_absent("AGENTS.md", PROJECT_INSTRUCTIONS)
    write_if_absent("CLAUDE.md", PROJECT_INSTRUCTIONS)
    write_if_absent(".claude/settings.json", json.dumps(claude_settings(hook), ensure_ascii=False, indent=2) + "\n")
    return created


def rendered_templates(version_line: str = "version 19") -> dict[str, str]:
    """plugins/stata-agent/skills/stata-analysis/templates/ 동기화용."""
    return {
        "00_master.do": render_master(["01_describe.do"], version_line),
        "01_describe.do": new_dofile("01_describe.do", EXAMPLE_SECTIONS, version_line),
        "AGENTS.md": PROJECT_INSTRUCTIONS,
        "claude_settings.json": json.dumps(claude_settings(), ensure_ascii=False, indent=2) + "\n",
    }
