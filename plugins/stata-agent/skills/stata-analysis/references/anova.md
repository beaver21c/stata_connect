# F검정(일원분산분석)

> 지위: 설계서 §9 점검표 기반 정리. 명령 목록은 Stata 표준 명령 기준이며, 세부 절차·판정 기준값은 구현·사용 전 Stata 매뉴얼 원문과 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 등분산(Bartlett·Levene 계열) → 위배 시 강건 F 또는 비모수 대안
- 소표본 집단(셀 크기) → 병합 여부를 연구자와 협의
- 사후검정 방법 명시

## 대표 명령
```stata
oneway price rep78, tabulate          // Bartlett 검정 포함 출력
robvar price, by(rep78)               // Levene(W0)·Brown-Forsythe(W50, W10)
kwallis price, by(rep78)              // Kruskal-Wallis
oneway price rep78, bonferroni        // 사후 비교 예시
```

## 사례(설계서 §2.1)
- 등분산 위배 감지 → Levene·집단 병합·강건 F·Kruskal-Wallis를 수정 섹션으로 추가해 비교(원 결과 섹션 유지)
