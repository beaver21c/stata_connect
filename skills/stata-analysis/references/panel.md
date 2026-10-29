# 패널

> 지위: 설계서 §9 점검표 기반 정리. 명령 목록은 Stata 표준 명령 기준이며, 세부 절차·판정 기준값은 구현·사용 전 Stata 매뉴얼 원문과 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 패널 구조(개체·시점 식별자, 균형 여부)
- 고정효과(FE) vs 확률효과(RE): Hausman 검정
- 군집 표준오차
- 자기상관

## 대표 명령
```stata
xtset id year
xtdescribe
xtreg y x1 x2, fe
estimates store fe
xtreg y x1 x2, re
estimates store re
hausman fe re
xtreg y x1 x2, fe vce(cluster id)
xtserial y x1 x2                        // SSC 패키지: stata_install_package("xtserial")
```

## 주의
- 개체 식별자(id)는 식별자 성격 변수 → `tab id`·`levelsof id`는 guard가 실행 전 보류
