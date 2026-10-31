# 상관

> 지위: Stata 스킬 점검표를 SPSS 명령으로 옮긴 정리. 명령·하위명령은 SPSS 일반 문법 기준이며, 세부 옵션·판정 기준값은 사용 전 IBM SPSS 문서와 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 쌍별(PAIRWISE) vs 목록별(LISTWISE) 결측 처리와 N 차이
- 다중공선성 후보(높은 상관 쌍) → 회귀 단계로 전달

## 대표 문법
```spss
CORRELATIONS /VARIABLES=score age income /PRINT=TWOTAIL NOSIG /MISSING=PAIRWISE.
```
