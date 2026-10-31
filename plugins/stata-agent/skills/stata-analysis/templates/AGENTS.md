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
