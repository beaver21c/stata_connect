# spss-agent 플러그인

SPSS가 계산하고 AI는 문법(.sps) 작성·결과 판독·해석을 맡는 분석 환경의 Claude용 플러그인.

## 들어 있는 것
- `spss-analysis` 스킬: 분석 절차·기법별 안내, 원자료 보호 원칙, 결과 해석 규칙

## 사용
- Claude Code: `/plugin marketplace add beaver21c/stata_connect` → `/plugin install spss-agent@stata-connect`
- Claude 채팅 앱(데스크톱): Customize › Plugins › Add marketplace에 `beaver21c/stata_connect` 입력
- SPSS 연결(MCP 서버) 설치는 설명서 SPSS 페이지 참조(실행파일 배포는 준비 중)

## 데이터
이 플러그인은 외부 서버로 자료를 보내지 않음. 분석 중 AI에 전달되는 것은 SPSS 출력(원자료 행을 걸러 낸 결과)뿐임.

설명서: https://beaver21c.github.io/stata_connect/spss.html
