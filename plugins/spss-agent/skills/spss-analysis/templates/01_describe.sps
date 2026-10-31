* ============================================================.
* 01_describe.sps | 작성: AI / 승인: 연구자 / 계산: SPSS.
* 생성일·수정 이력: .spss-agent/history.jsonl 참조.
* ============================================================.

*== [S01] 예제 자료 만들기 ==.
DATA LIST FREE / id group score.
BEGIN DATA
1 1 72 2 1 85 3 1 90 4 1 66 5 1 78
6 2 88 7 2 92 8 2 79 9 2 95 10 2 84
END DATA.
VALUE LABELS group 1 '통제' 2 '처치'.
EXECUTE.

*== [S02] 기술통계 ==.
DESCRIPTIVES VARIABLES=score /STATISTICS=MEAN STDDEV MIN MAX.

*== [S03] 집단 비교 ==.
T-TEST GROUPS=group(1 2) /VARIABLES=score.
