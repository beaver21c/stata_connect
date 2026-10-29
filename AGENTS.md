# 개발 지침 (이 저장소를 수정하는 Claude Code·Codex용)

> 분석 프로젝트용 지침은 `skills/stata-analysis/templates/AGENTS.md`(별도 파일)임. 이 파일은 저장소 개발 지침.

## 먼저 읽을 것
1. `docs/design/stata_agent_design.html` — 설계서 원문(수정 금지)
2. `docs/IMPLEMENTATION_STATUS.md` — 구현 대응·검증 지위·설계 변경점·실기 검증 체크리스트

## 규칙
- 테스트: `python -m pytest -q` 통과 후 커밋. Stata 없이 도는 테스트는 `tests/fakes.py`의 가짜 백엔드 사용
- 도구 추가·변경: `mcp_server/stata_agent/tool_specs.py`가 단일 원본 → `service.py`·`server.py dispatch`·`SKILL.md` 도구표 함께 수정(`tests/test_skill_and_templates.py`가 누락 검사)
- 프로젝트 템플릿 변경: `project.py`·`dofile.py` 수정 후 `stata-agent render-templates` 실행(동기화 테스트 있음)
- 상류(stata-gui-mcp) 도구는 노출 금지. 상류 버전 변경 절차는 IMPLEMENTATION_STATUS §6
- AI에게 반환하는 모든 Stata 출력은 `guard/output_filter.filter_output` 통과 필수. 사용 기록(`history.jsonl`)에 코드·값·로그 원문 기록 금지
- 일련번호·등록자는 로컬 `stata-agent doctor` 화면에만 표시. 도구 반환·점검 보고서에 넣지 않음
- 문서·주석은 한국어 보고서체. 확인되지 않은 사실은 [미확인] 등 지위 표기
- PowerShell 스크립트는 UTF-8 BOM으로 저장(Windows PowerShell 5.1 한글 처리)

## Windows 실기 검증 시
IMPLEMENTATION_STATUS §7 체크리스트 순서로 진행하고, 확인 결과(통과·실패·실제 출력)를 같은 문서에 기록. 실제 `about` 출력·로그는 익명화 후 테스트 사례로 추가.
