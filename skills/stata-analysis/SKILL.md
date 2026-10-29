---
name: stata-analysis
description: Stata를 MCP 도구(stata 서버)로 제어해 연구자의 통계분석을 수행하는 절차. do-file 섹션 작성→연구자 승인→Stata 실행→로그 판독·검증→해석→논문형 표·재현 확인·AI 사용 공개문까지 다룸. 사용자가 Stata 분석, do-file, 회귀·t검정·분산분석·상관·SEM·패널 분석, Stata 연결 점검을 요청할 때 사용. 모든 수치는 Stata가 계산하고 원자료 행은 AI에 보내지 않는 것이 원칙.
---

# Stata 분석 스킬 (Claude·Codex 공용)

## 1. 원칙 (항상 적용)
- **P1 계산 주체**: 모든 통계량은 Stata가 산출. 수치를 직접 계산·추정·반올림 변형해 보고하지 않음.
- **P2 원자료 비전송**: 관측치 값을 보려 하지 않음. `data/` 파일을 파일 읽기·셸·스크립트로 열지 않음. 자료 구조는 `stata_schema`만 사용.
- **P3 사람 승인**: 실행·쓰기 도구는 연구자 승인 후 진행. guard가 "승인 필요"로 판정하면 사유를 쉬운 말로 설명하고 동의를 받은 뒤에만 `acknowledge_risks=true`.
- **P4 가시성**: 분석은 AI가 연 Stata 창에서 진행. 연구자가 그 창에서 직접 명령을 입력해도 이어서 작업 가능.
- **P5 재현성**: 모든 분석은 do-file 섹션으로 남김. 일회성 명령도 섹션으로 추가 후 실행.
- **P6 투명성**: 마무리 때 `stata_usage_summary`로 공개문 초안 제시.

## 2. 도구 이름
서버 이름은 `stata`. Claude Code에서는 `mcp__stata__stata_run_section`처럼 접두어가 붙고, Claude 앱·Codex에서는 `stata_run_section` 등으로 보일 수 있음. 아래는 접두어 없이 표기.

| 도구 | 용도 | 승인 |
|---|---|---|
| stata_status | 백엔드·세션·버전·라이선스 | 자동 |
| stata_selftest | T1~T10 연결 점검 + 보고서 | 자동 |
| stata_open_session | 프로젝트 폴더로 Stata 창 열기(가장 먼저) | 필요 |
| stata_load_data | 자료 불러오기(관측치·변수 수만 반환) | 필요 |
| stata_schema | 변수명·유형·라벨·결측 | 자동 |
| stata_write_dofile / stata_patch_dofile | do-file 작성 / 섹션 추가·교체·삭제 | 필요 |
| stata_show_in_editor | Do-file Editor 표시 | 자동 |
| stata_run_section / stata_run_dofile | 섹션 / 파일 전체 실행 | 필요 |
| stata_read_log | 로그 다시 읽기(필터 적용) | 자동 |
| stata_get_results | e()·r()·_b[]·스칼라 조회 | 자동 |
| stata_export | etable·putdocx 표 산출 | 필요 |
| stata_reproduce | 00_master.do 배치 재실행·수치 대조 | 필요 |
| stata_install_package | ssc/net 설치 | 필요 |
| stata_usage_summary | AI 사용 기록·공개문 초안 | 자동 |
| stata_break | 중단 방법 안내(현재 미구현) | 자동 |

## 3. 작업 순서
1. **요청 해석**: 분석 목적·종속/독립변수·표본을 확인. 결론을 가르는 핵심 사항 1~2개만 먼저 질문.
2. **연결**: `stata_open_session(project_dir)` → 필요하면 `stata_load_data`.
3. **자료 구조**: `stata_schema`만 사용(행 열람 금지).
4. **do-file 작성**: `stata_write_dofile`로 섹션 단위 작성(파일명 `NN_영문.do`, 예: `04_regress.do`). 추정결과는 `estimates store m1`처럼 이름을 붙여 저장.
5. **승인·실행**: 실행할 섹션과 이유를 알리고 `stata_run_section`.
6. **검증**: 로그를 기법별 점검표(references/)로 확인 → 위배 시 원인·대안 제시.
7. **수정·재실행**: `stata_patch_dofile(action="add")`로 수정 섹션 추가(원 결과 섹션 삭제 금지) → 비교.
8. **해석**: 모든 수치를 로그 또는 `stata_get_results`에서 인용하고 출처를 표기(예: `04_regress.do S02`).
9. **산출**: `stata_export`로 표(Word 등), 연구방법·연구결과 초안 작성.
10. **재현 확인**: `stata_reproduce` → "재현 일치 / 불일치 n건" 1줄 보고.
11. **공개문**: `stata_usage_summary` → 초안을 연구자가 검토하도록 제시.

## 4. 해석 규칙
- 해석 문장의 수치는 로그 표의 값을 그대로 옮김. 필요한 값이 로그에 없으면 `stata_get_results`로 조회하거나 Stata 명령을 섹션에 추가해 산출.
- 채팅 해석 수치와 로그 수치가 다르면 해석을 보류하고 다시 조회.
- p값·신뢰구간·표본 수(N)를 함께 제시. 표본 수가 단계별로 다르면 그 이유(결측 등)를 밝힘.
- 통계적 유의성과 실질적 크기를 구분해 서술.

## 5. 차단·승인 대응
- **차단**(list·browse·display var[1]·shell·외부 반출 등): 같은 목적을 요약통계로 바꿈(예: `list` 대신 `summarize`, `tabstat`, `count if`). 꼭 필요하면 연구자가 Stata 창에서 직접 실행하도록 안내.
- **승인 필요**(cd·동적 명령·data 외 저장 등): 사유를 설명하고 동의를 받은 뒤 `acknowledge_risks=true`.
- **식별자 성격 변수 빈도표**(고유값 비율 높음): 범주화하거나 빈도표 대신 요약통계 사용.
- **출력 필터 차단**: 결과 일부가 가려짐 → 원 로그는 연구자 PC에만 있음. 연구자에게 Stata 창에서 확인을 요청.

## 6. do-file 규약
- 헤더(작성·승인·계산 주체, `version`, 이름 지정 로그 `_nmlog`)와 꼬리(`log close _nmlog`)는 도구가 관리 → 섹션 코드에 넣지 않음.
- 섹션 표지 `*== [S01] 제목 ==*`가 편집·실행 단위.
- `00_master.do`는 do-file 작성 시 자동 갱신.
- 경로는 프로젝트 폴더 기준 상대경로(`output/tables/...`). `cd` 사용 지양.
- 원자료(`data/`)에 저장하지 않음. 가공 자료는 `output/` 아래에 저장.

## 7. 기법별 점검표 (references/)
기술통계 `descriptive.md` · t검정 `ttest.md` · 분산분석 `anova.md` · 상관 `correlation.md` · 다중회귀 `regression.md` · 경로분석·SEM `sem.md` · 패널 `panel.md` · 비선형 `nonlinear.md` · 보고 양식 `reporting.md`

## 8. 자주 생기는 상황
- **배치 모드**(`stata_status`의 backend가 batch_cli): 호출 간 메모리 미유지 → 각 섹션에 자료 불러오기 포함, 편집기 연동·저장결과 조회 불가.
- **실행 시간 초과**: COM 세션은 명령당 180초 제한(상류 고정값) → 장시간 작업은 `stata_reproduce`(배치)로 실행하거나 섹션을 나눔.
- **Stata 창이 닫힘·연결 끊김**: 새 빈 세션으로 재연결됨 → 자료 불러오기부터 다시 실행.
- **연결 점검 요청**: `stata_selftest` 결과표를 보여 주고, 실패 항목의 조치를 안내. 오류 보고에는 점검 보고서 파일만 첨부하도록 안내.
