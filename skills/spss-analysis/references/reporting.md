# 보고 양식

> 지위: Stata 스킬 점검표를 SPSS 명령으로 옮긴 정리. 명령·하위명령은 SPSS 일반 문법 기준이며, 세부 옵션·판정 기준값은 사용 전 IBM SPSS 문서와 연구 분야 관행으로 재확인 필요 [미확인].

## 연구방법 절
- 자료·표본 정의, 결측 처리, 기법과 가정 점검, 대안 분석
- 소프트웨어: IBM SPSS Statistics 버전(`spss_status`)
- AI 사용 공개(`spss_usage_summary` 초안을 연구자가 수정)

## 표 산출
- `spss_export(filename, section_id, output="table2.docx")` → 해당 섹션을 다시 실행하며 표만 저장
- 모든 수치는 출력 인용, 표 번호와 .sps 섹션 대응표 유지
