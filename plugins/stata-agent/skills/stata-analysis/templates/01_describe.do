* ============================================================
* 01_describe.do | 작성: AI / 승인: 연구자 / 계산: Stata
* 생성일·수정 이력: .stata-agent/history.jsonl 참조
* ============================================================
version 19
set more off
capture log close _nmlog
log using "output/logs/01_result.log", text replace name(_nmlog)

*== [S01] 자료 불러오기 ==*
sysuse auto, clear

*== [S02] 기술통계 ==*
summarize price mpg weight length
tabstat price mpg, by(foreign) statistics(n mean sd)

*== [S03] 상관 ==*
pwcorr price mpg weight length, sig obs

log close _nmlog
