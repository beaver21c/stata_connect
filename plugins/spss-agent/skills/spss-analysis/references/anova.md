# 일원분산분석

> 지위: Stata 스킬 점검표를 SPSS 명령으로 옮긴 정리. 명령·하위명령은 SPSS 일반 문법 기준이며, 세부 옵션·판정 기준값은 사용 전 IBM SPSS 문서와 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 등분산 → 위배 시 Welch·Brown-Forsythe, 사후검정은 등분산 가정 안 하는 방법
- 소표본 집단 → 병합 여부 협의

## 대표 문법
```spss
ONEWAY score BY grp /STATISTICS DESCRIPTIVES HOMOGENEITY WELCH BROWNFORSYTHE
  /POSTHOC=TUKEY GH ALPHA(0.05).
NPAR TESTS /K-W=score BY grp(1 3).
```

## 효과크기
- SPSS 27 이상: `ONEWAY ... /ES=OVERALL` [2차 확인: 제3자 안내, IBM 원문 미열람]
- 22~26: `GLM score BY grp /PRINT=ETASQ DESCRIPTIVE HOMOGENEITY.`로 편에타제곱 산출
