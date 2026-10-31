# 다중회귀

> 지위: 설계서 §9 점검표 기반 정리. 명령 목록은 Stata 표준 명령 기준이며, 세부 절차·판정 기준값은 구현·사용 전 Stata 매뉴얼 원문과 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 모형 설정: 종속·독립변수, 통제변수, 표본 정의
- 다중공선성: VIF
- 이분산: 검정 후 필요 시 강건 표준오차
- 영향점: 레버리지·Cook's D
- 모형 설정 오류: 누락변수·함수형 점검

## 대표 명령
```stata
regress price mpg weight
estimates store m1
estat vif
estat hettest
estat ovtest
regress price mpg weight, vce(robust)
estimates store m1_robust
predict double cooksd, cooksd
summarize cooksd                            // 개별 값 대신 요약
```

## 보고
- 계수·표준오차(종류 명시)·t·p·신뢰구간, N, R²(조정 R²)
- 표: `stata_export(mode="etable", estimates=["m1","m1_robust"], filename="table_reg.docx")`
