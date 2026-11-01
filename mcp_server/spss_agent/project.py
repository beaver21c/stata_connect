"""SPSS 분석 프로젝트 폴더 규약·지침 파일. plugins/spss-agent/skills/spss-analysis/templates와 동기화(테스트로 검사)."""

from __future__ import annotations

import json
from pathlib import Path

from .syntaxfile import ENCODING, MASTER_NAME, new_syntax, render_master
from .tool_specs import PROFILE

DIRS = ("data", "output/logs", "output/tables", ".spss-agent")

PROJECT_INSTRUCTIONS = """\
# SPSS 분석 프로젝트 지침 (AGENTS.md / CLAUDE.md 공통)

이 폴더는 spss-agent 규약을 따르는 SPSS 분석 프로젝트임. AI는 아래 원칙을 지킴.

## 원칙
- 계산 주체: 모든 통계량은 SPSS가 산출. AI는 문법 작성·출력 판독·해석만 담당하며 수치를 직접 계산·추정해 보고하지 않음.
- 원자료 비전송: `data/` 폴더 파일을 읽기 도구·셸·스크립트로 열지 않음. 자료 구조는 `spss_schema`로만 파악.
- 사람 승인: 실행·쓰기 도구는 연구자 승인 후 실행. guard가 '승인 필요'로 판정하면 사유를 설명하고 동의를 받은 뒤에만 `acknowledge_risks=true` 사용.
- 재현성: 모든 분석은 .sps 섹션으로 남기고, 마무리 때 `spss_reproduce`로 새 엔진 재실행 결과를 대조.
- 투명성: 분석 종료 시 `spss_usage_summary`로 AI 사용 공개문 초안을 제시.

## 폴더
- `00_master.sps`: 전체 재현 진입점(INSERT 목록, 자동 갱신)
- `NN_이름.sps`: 분석 단계별 문법 파일(섹션 표지 `*== [S01] 제목 ==.`)
- `data/`: 원자료(읽기 전용, AI 미열람)
- `output/logs/NN_result.txt`: 문법 파일 전체 실행 출력
- `output/tables/`: 표 산출물
- `.spss-agent/`: 세션 기록·백업(수정 금지)

## 문법 작성 규칙
- 각 섹션은 필요한 자료 불러오기(`GET FILE='data/...sav'.`)를 앞 섹션이나 자체에 포함해 단독 재실행이 가능하게 함.
- 명령은 마침표로 끝냄. 사례 값을 출력하는 LIST·PRINT·SUMMARIZE(목록)는 쓰지 않음.

## 해석 규칙
- 해석 문장의 모든 수치는 출력에서 인용하고 출처 섹션(예: 04_regress.sps S02)을 표기.
- 출력 수치와 해석 수치가 다르면 해석을 보류하고 다시 확인.
"""


def claude_settings(hook: list[str] | None = None) -> dict:
    """프로젝트 ``.claude/settings.json``. hook이 있으면 셸 명령 실행 전 검사(공용 hookguard) 등록."""
    settings: dict = {
        "permissions": {
            "deny": ["Read(/data/**)", "Edit(/data/**)"],
            "allow": [PROFILE.tool_id(n) for n in PROFILE.read_only_tools],
            "ask": [PROFILE.tool_id(n) for n in PROFILE.approval_tools],
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


# SPSS에는 Stata의 sysuse 같은 내장 예제 불러오기가 없어 문법 안 자료로 예제 구성
EXAMPLE_SECTIONS = [
    ("예제 자료 만들기", "DATA LIST FREE / id group score.\nBEGIN DATA\n1 1 72 2 1 85 3 1 90 4 1 66 5 1 78\n"
                     "6 2 88 7 2 92 8 2 79 9 2 95 10 2 84\nEND DATA.\n"
                     "VALUE LABELS group 1 '통제' 2 '처치'.\nEXECUTE."),
    ("기술통계", "DESCRIPTIVES VARIABLES=score /STATISTICS=MEAN STDDEV MIN MAX."),
    ("집단 비교", "T-TEST GROUPS=group(1 2) /VARIABLES=score."),
]


def init_project(root: Path, example: bool = False, hook: list[str] | None = None) -> list[str]:
    root = Path(root)
    created: list[str] = []
    for d in DIRS:
        if not (root / d).exists():
            (root / d).mkdir(parents=True, exist_ok=True)
            created.append(d + "/")

    def write_if_absent(rel: str, content: str, encoding: str = "utf-8") -> None:
        p = root / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding=encoding)
            created.append(rel)

    if example:
        write_if_absent("01_describe.sps", new_syntax("01_describe.sps", EXAMPLE_SECTIONS), ENCODING)
        write_if_absent(MASTER_NAME, render_master(["01_describe.sps"]), ENCODING)
    else:
        write_if_absent(MASTER_NAME, render_master([]), ENCODING)
    write_if_absent("AGENTS.md", PROJECT_INSTRUCTIONS)
    write_if_absent("CLAUDE.md", PROJECT_INSTRUCTIONS)
    write_if_absent(".claude/settings.json", json.dumps(claude_settings(hook), ensure_ascii=False, indent=2) + "\n")
    return created


def rendered_templates() -> dict[str, str]:
    return {
        "00_master.sps": render_master(["01_describe.sps"]),
        "01_describe.sps": new_syntax("01_describe.sps", EXAMPLE_SECTIONS),
        "AGENTS.md": PROJECT_INSTRUCTIONS,
        "claude_settings.json": json.dumps(claude_settings(), ensure_ascii=False, indent=2) + "\n",
    }
