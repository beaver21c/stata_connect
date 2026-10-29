# t검정

> 지위: 설계서 §9 점검표 기반 정리. 명령 목록은 Stata 표준 명령 기준이며, 세부 절차·판정 기준값은 구현·사용 전 Stata 매뉴얼 원문과 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 집단별 표본 수
- 정규성(소표본일수록 중요): 집단별 분포 점검
- 등분산: 등분산 가정 위배 시 Welch 검정 병행 보고

## 대표 명령
```stata
ttest price, by(foreign)
ttest price, by(foreign) unequal      // Welch(이분산 가정)
sdtest price, by(foreign)             // 분산 동일성 검정
swilk price if foreign == 0
swilk price if foreign == 1
ranksum price, by(foreign)            // 비모수 대안(필요 시)
```

## 보고
- 집단별 N·평균·표준편차, t값, 자유도, p값, 평균 차이의 신뢰구간
