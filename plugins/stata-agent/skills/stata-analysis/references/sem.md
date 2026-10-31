# 경로분석·SEM

> 지위: 설계서 §9 점검표 기반 정리. 명령 목록은 Stata 표준 명령 기준이며, 세부 절차·판정 기준값은 구현·사용 전 Stata 매뉴얼 원문과 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 식별(자유도, 추정 수렴)
- 적합도: χ², CFI, TLI, RMSEA, SRMR — 판정 기준은 인용 문헌을 명시해 적용
- 간접효과: 부트스트랩 신뢰구간

## 대표 명령
```stata
sem (y <- m x) (m <- x)
estimates store sem1
estat gof, stats(all)
estat teffects
sem (y <- m x) (m <- x), vce(bootstrap, reps(1000) seed(12345))
```

## 주의
- 부트스트랩은 실행 시간이 길어 COM 180초 제한을 넘을 수 있음 → 반복 수를 줄여 시험 후 `stata_reproduce`(배치)로 최종 실행
