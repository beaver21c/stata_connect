# 보고 양식

> 지위: Stata 스킬 점검표를 SPSS 명령으로 옮긴 정리. 명령·하위명령은 SPSS 일반 문법 기준이며, 세부 옵션·판정 기준값은 사용 전 IBM SPSS 문서와 연구 분야 관행으로 재확인 필요 [미확인].

## 연구방법 절
- 자료·표본 정의, 결측 처리, 기법과 가정 점검, 대안 분석
- 소프트웨어: IBM SPSS Statistics 버전(`spss_status`)
- AI 사용 공개(`spss_usage_summary` 초안을 연구자가 수정)

## 표 산출
- `spss_export(filename, section_id, output="table2.docx")` → 해당 섹션을 다시 실행하며 표만 저장
- 버전별 형식(OMS) [2차 확인: IBM OMS 문서 검색 요약]: Word·Excel(.xls)·PDF는 17부터, `.xlsx`는 21부터. Word는 28.0.1 전까지 `.doc`(97-2003) 형식 → 27 이하에서는 도구가 `.doc`로 저장. 29에서 `.xlsx`가 빈 파일로 나온 보고가 있음 → `.xls` 사용
- 모든 수치는 출력 인용, 표 번호와 .sps 섹션 대응표 유지
