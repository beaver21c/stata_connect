# 보고 양식

> 지위: 설계서 §9 점검표 기반 정리. 명령 목록은 Stata 표준 명령 기준이며, 세부 절차·판정 기준값은 구현·사용 전 Stata 매뉴얼 원문과 연구 분야 관행으로 재확인 필요 [미확인].

## 연구방법 절 체크리스트
- 자료·표본 정의, 분석 단위, 결측 처리
- 사용 기법과 가정 점검 방법, 대안 분석
- 소프트웨어: Stata 버전·에디션(`stata_status`)
- AI 사용 공개(`stata_usage_summary` 초안을 연구자가 수정)

## 연구결과 절 체크리스트
- 기술통계 표 → 주요 분석 표 → 강건성(대안) 결과 순
- 모든 수치는 로그 인용, 표 번호와 do-file 섹션 대응표 유지

## 표 산출
- 회귀류: `stata_export(mode="etable", estimates=[...], filename="table2.docx")`
- 그 밖: `stata_export(mode="custom", code="collect ... / putdocx ...")` — 저장 경로는 `output/tables/`
- `etable`·`collect`는 Stata 17 이상, `putdocx`는 Stata 15 이상(2차 자료 확인)
