# t검정

> 지위: Stata 스킬 점검표를 SPSS 명령으로 옮긴 정리. 명령·하위명령은 SPSS 일반 문법 기준이며, 세부 옵션·판정 기준값은 사용 전 IBM SPSS 문서와 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 집단별 사례 수, 정규성(소표본), 등분산(Levene) → 위배 시 "등분산 가정 안 함" 행(Welch) 보고

## 대표 문법
```spss
T-TEST GROUPS=group(1 2) /VARIABLES=score.
EXAMINE VARIABLES=score BY group /PLOT NPPLOT /STATISTICS DESCRIPTIVES.
NPAR TESTS /M-W=score BY group(1 2).
```

## 보고
- 집단별 N·평균·표준편차, t, 자유도, p, 평균 차이 신뢰구간, 등분산 가정 여부
- 효과크기: SPSS 27 이상은 `T-TEST ... /ES DISPLAY(TRUE)`(Cohen's d 등) [2차 확인: IBM T-TEST ES 하위명령 문서·제3자 안내]. 22~26에는 없음 → 연구자와 산출 방법 합의(AI 직접 계산 금지)
