# 상관

> 지위: 설계서 §9 점검표 기반 정리. 명령 목록은 Stata 표준 명령 기준이며, 세부 절차·판정 기준값은 구현·사용 전 Stata 매뉴얼 원문과 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 쌍별(pairwise) vs 목록별(listwise) N 차이
- 다중공선성 후보(높은 상관 쌍)를 회귀 단계에 전달

## 대표 명령
```stata
pwcorr price mpg weight length, sig obs   // 쌍별 N·유의확률
correlate price mpg weight length         // 목록별 결측 제거
```

## 보고
- 상관행렬 + 각 셀 N(쌍별일 때) + 유의확률 표기 방식 명시
