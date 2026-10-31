# 기술통계

> 지위: 설계서 §9 점검표 기반 정리. 명령 목록은 Stata 표준 명령 기준이며, 세부 절차·판정 기준값은 구현·사용 전 Stata 매뉴얼 원문과 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 결측: 변수별 결측 수·비율, 결측 양상
- 이상치: 최솟값·최댓값·분위수가 측정 범위 안에 있는지
- 단위: 변수 라벨·값 라벨로 단위·코딩 방향 확인

## 대표 명령
```stata
misstable summarize
summarize price mpg weight
tabstat price mpg, statistics(n mean sd p25 p50 p75 min max)
tabstat price, by(foreign) statistics(n mean sd)
```

## 주의
- `summarize, detail`은 최솟값·최댓값 근처 개별 값(Smallest/Largest)을 출력함 → 민감자료에서는 `tabstat`의 분위수로 대체 검토
- 범주형 빈도는 `tab`(식별자 성격 변수는 guard가 실행 전 점검)
