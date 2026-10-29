# 비선형 모형

> 지위: 설계서 §9 점검표 기반 정리. 명령 목록은 Stata 표준 명령 기준이며, 세부 절차·판정 기준값은 구현·사용 전 Stata 매뉴얼 원문과 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 연결함수·분포 선택 근거
- 계수 대신 한계효과로 해석
- 적합도·분류 성능(해당 시)

## 대표 명령
```stata
logit foreign price mpg
estimates store lg
margins, dydx(*)
estat gof
probit foreign price mpg
poisson y x1 x2, vce(robust)
nbreg y x1 x2
```

## 보고
- 승산비/계수, 평균 한계효과(AME)와 신뢰구간, 적합도 지표
