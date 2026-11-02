# 다중회귀

> 지위: Stata 스킬 점검표를 SPSS 명령으로 옮긴 정리. 명령·하위명령은 SPSS 일반 문법 기준이며, 세부 옵션·판정 기준값은 사용 전 IBM SPSS 문서와 연구 분야 관행으로 재확인 필요 [미확인].

## 필수 점검
- 다중공선성(공차·VIF), 잔차 정규성·등분산(잔차 도표), 영향점, 자기상관(Durbin-Watson, 해당 시)

## 대표 문법
```spss
REGRESSION
  /STATISTICS COEFF OUTS CI(95) R ANOVA COLLIN TOL
  /DEPENDENT score
  /METHOD=ENTER age income
  /SCATTERPLOT=(*ZRESID ,*ZPRED)
  /RESIDUALS DURBIN HISTOGRAM(ZRESID).
```

## 단계별(위계적) 회귀
- 한 REGRESSION 안에 `/METHOD=ENTER`를 단계마다 한 줄씩, `/STATISTICS … CHANGE`를 넣으면 모형별 R² 변화·F 변화가 출력됨(행렬로 직접 계산하지 않음) [논리적 추론: SPSS 일반 문법 기준, 버전별 출력 형식 미확인]
- 표준화 계수는 계수표의 Beta 열로 확인
- 출력은 분석 섹션에서 그대로 보이게 하고, 다시 가공하는 계산(MATRIX 등)은 `[보고용]` 섹션으로 분리(SKILL.md §3 4단계)

## 주의
- `/CASEWISE`는 이상 사례의 개별 값을 표로 출력함 → 쓰지 않거나 연구자 확인 후 사용
- 강건 표준오차는 REGRESSION에 없음 → GLM·GENLIN 계열의 강건 옵션 사용 가능 여부를 버전별 문서로 확인 [미확인]
