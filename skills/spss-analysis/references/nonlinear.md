# 비선형·다층 모형

> 지위: Stata 스킬 점검표를 SPSS 명령으로 옮긴 정리. 명령·하위명령은 SPSS 일반 문법 기준이며, 세부 옵션·판정 기준값은 사용 전 IBM SPSS 문서와 연구 분야 관행으로 재확인 필요 [미확인].

## 대표 문법
```spss
LOGISTIC REGRESSION VARIABLES=outcome /METHOD=ENTER age sex /PRINT=CI(95) GOODFIT.
PLUM outcome_ord WITH age /LINK=LOGIT /PRINT=FIT PARAMETER SUMMARY TPARALLEL.
GENLIN count WITH age /MODEL age DISTRIBUTION=POISSON LINK=LOG /PRINT FIT SUMMARY SOLUTION.
MIXED score WITH time /FIXED=time /RANDOM=INTERCEPT | SUBJECT(id) /PRINT=SOLUTION TESTCOV.
```

## 주의
- MIXED의 SUBJECT(id)는 식별자 변수를 쓰지만 개별 값을 출력하지 않음. 다만 id로 FREQUENCIES·MEANS BY는 보류 대상
- 승산비(Exp(B))와 신뢰구간, 적합도 지표 함께 보고
