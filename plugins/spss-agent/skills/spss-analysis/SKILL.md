---
name: spss-analysis
description: SPSS Statistics를 MCP 도구(spss 서버, 화면 없는 SPSS 엔진)로 제어해 연구자의 통계분석을 수행하는 절차. 문법(.sps) 섹션 작성→연구자 승인→SPSS 실행→출력 판독·검증→해석→표 산출·재현 확인·AI 사용 공개문까지 다룸. 사용자가 SPSS 분석, SPSS 문법, t검정·분산분석·상관·회귀·로지스틱 분석, SPSS 연결 점검을 요청할 때 사용. 모든 수치는 SPSS가 계산하고 사례 값은 AI에 보내지 않는 것이 원칙.
---

# SPSS 분석 스킬 (Claude·Codex 공용)

## 1. 원칙
- **계산 주체**: 모든 통계량은 SPSS가 산출. 수치를 직접 계산·추정하지 않고 출력에서 그대로 인용.
- **원자료 비전송**: 사례 값을 보려 하지 않음. `data/` 파일을 파일 읽기·셸·스크립트로 열지 않음. 자료 구조는 `spss_schema`만 사용.
- **사람 승인**: 실행·쓰기 도구는 연구자 승인 후 진행. "승인 필요" 판정은 사유를 설명하고 동의를 받은 뒤에만 `acknowledge_risks=true`.
- **재현성**: 모든 분석은 .sps 섹션으로 남김. 일회성 명령도 섹션으로 추가 후 실행.
- **투명성**: 마무리 때 `spss_usage_summary`로 공개문 초안 제시.
- **화면 없음**: SPSS 창이 뜨지 않음. 결과는 출력 파일(`output/logs`, `.spss-agent/last_run.txt`)로 확인. 연구자가 SPSS에서 같은 .sps를 열어 직접 실행해 볼 수 있음.

## 2. 도구 이름
서버 이름은 `spss`. Claude Code에서는 `mcp__spss__spss_run_section`처럼 접두어가 붙을 수 있음.

| 도구 | 용도 | 승인 |
|---|---|---|
| spss_status | 설치·엔진·세션 상태 | 자동 |
| spss_selftest | T1~T10 연결 점검 + 보고서 | 자동 |
| spss_open_session | 프로젝트 폴더로 SPSS 엔진 기동(가장 먼저) | 필요 |
| spss_load_data | .sav 불러오기(사례·변수 수만 반환) | 필요 |
| spss_schema | 변수명·라벨·유형·측정수준·결측 | 자동 |
| spss_write_syntax / spss_patch_syntax | 문법 파일 작성 / 섹션 추가·교체·삭제 | 필요 |
| spss_run_section / spss_run_syntax_file | 섹션 / 파일 전체 실행 | 필요 |
| spss_read_output | 출력 다시 읽기(필터 적용) | 자동 |
| spss_export | 섹션 결과 표를 Word·Excel·HTML·PDF로 저장 | 필요 |
| spss_reproduce | 새 엔진에서 00_master.sps 목록 재실행·수치 대조 | 필요 |
| spss_usage_summary | AI 사용 기록·공개문 초안 | 자동 |

## 3. 작업 순서
1. **요청 해석**: 목적·종속/독립변수·표본 확인. 결론을 가르는 핵심 사항 1~2개만 먼저 질문.
2. **연결**: `spss_open_session(project_dir)` → 필요하면 `spss_load_data`.
3. **자료 구조**: `spss_schema`만 사용.
4. **문법 작성**: `spss_write_syntax`로 섹션 단위 작성(파일명 `NN_영문.sps`). 첫 섹션에 `GET FILE='data/...sav'.`를 두어 파일 단독 재실행이 가능하게 함. 명령은 마침표로 끝냄.
5. **승인·실행**: `spss_run_section` 또는 `spss_run_syntax_file`.
6. **검증**: 출력을 기법별 점검표(references/)로 확인 → 위배 시 원인·대안 제시.
7. **수정·재실행**: `spss_patch_syntax(action="add")`로 수정 섹션 추가(원 결과 섹션 유지) → 비교.
8. **해석**: 수치는 출력에서 인용하고 출처 표기(예: `04_regress.sps S02`).
9. **산출**: `spss_export`로 표 저장, 연구방법·연구결과 초안 작성.
10. **재현 확인**: `spss_run_syntax_file`로 각 파일 전체 실행 기록을 남긴 뒤 `spss_reproduce` → "재현 일치 / 불일치 n건" 보고.
11. **공개문**: `spss_usage_summary` → 연구자 검토용 초안 제시.

## 4. 차단·승인 대응
- **차단**: `LIST`, `PRINT`, OUTFILE 없는 `WRITE`, 목록형 `SUMMARIZE`(→ `/FORMAT=NOLIST` 사용), `HOST`, `ERASE`, `BEGIN PROGRAM`, TAG 없는 `OMSEND`, 프로젝트 밖·`data/`로 저장 → 요약통계로 바꿈.
- **승인 필요**: `CD`, 매크로 호출, `REPORT`, 사용자 `OMS`, 프로젝트 안 자료 내보내기(`SAVE TRANSLATE` 등), 파일 핸들 경로.
- **식별자 성격 변수**: 고유값이 대부분인 변수(아이디 등)로 `FREQUENCIES`·`CROSSTABS`·`MEANS ... BY`를 하면 실행 전 보류 → 범주화하거나 다른 방법 사용.
- **출력 필터 차단**: 사례 목록형 표·단일 빈도 범주표는 가려짐 → 연구자에게 SPSS에서 직접 확인을 요청.

## 5. 자주 생기는 상황
- **SPSS에는 Stata의 r()·e() 같은 저장결과가 없음** → 해석 수치는 출력 표에서 인용.
- **실행 시간 초과**(기본 900초): 엔진이 종료되고 세션 상태(열린 자료)가 사라짐 → 자료 불러오기부터 다시 실행.
- **SPSS 오류 수준**: 2 = 경고(출력 확인), 3 이상 = 오류(명령 미실행 가능) → 오류 메시지를 보고 문법 수정.
- **연결 점검 요청**: `spss_selftest` 결과표를 보여 주고 실패 항목 조치를 안내. 오류 보고에는 점검 보고서만 첨부.
- **SPSS 버전**: 지원 범위는 22 이상. 문법을 쓰기 전 `spss_status`의 버전을 확인하고, 이후 버전에서 추가된 기능은 그 버전 이상일 때만 사용.
  - 27 이상: `T-TEST`·`ONEWAY`의 효과크기(`/ES`). 22~26에는 없음 → 효과크기가 필요하면 `GLM ... /PRINT ETASQ`(편에타제곱) 등 SPSS가 산출하는 방법을 연구자와 정하고, AI가 직접 계산하지 않음
  - 표 내보내기: 27 이하는 Word가 `.doc`(97-2003) 형식으로 저장됨(도구가 자동 변경), 29에서 `.xlsx`가 비어 있으면 `.xls`로 다시 요청

## 6. 기법별 점검표 (references/)
기술통계 `descriptive.md` · t검정 `ttest.md` · 분산분석 `anova.md` · 상관 `correlation.md` · 회귀 `regression.md` · 비선형·다층 `nonlinear.md` · SEM `sem.md` · 보고 양식 `reporting.md`
