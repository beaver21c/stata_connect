# 기술통계

> 지위: Stata 스킬 점검표를 SPSS 명령으로 옮긴 정리. 명령·하위명령은 SPSS 일반 문법 기준이며, 세부 옵션·판정 기준값은 사용 전 IBM SPSS 문서와 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 결측: 변수별 결측 수·비율(`spss_schema`의 missing)
- 이상치: 최솟값·최댓값·분위수가 측정 범위 안인지
- 코딩: 변수 라벨·값 라벨로 단위·방향 확인

## 대표 문법
```spss
DESCRIPTIVES VARIABLES=score age /STATISTICS=MEAN STDDEV MIN MAX.
FREQUENCIES VARIABLES=score /FORMAT=NOTABLE /STATISTICS=MEAN MEDIAN STDDEV /PERCENTILES=25 50 75.
FREQUENCIES VARIABLES=sex region.
```

## 주의
- 연속형·식별자 변수의 FREQUENCIES 표는 개별 값이 그대로 나옴 → `/FORMAT=NOTABLE`
- `EXAMINE ... /STATISTICS EXTREME`은 극단값 사례 값을 출력함(경고 대상)
