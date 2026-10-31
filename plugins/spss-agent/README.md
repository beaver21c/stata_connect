# spss-agent 플러그인

SPSS가 계산하고 AI는 문법(.sps) 작성·결과 판독·해석을 맡는 분석 환경의 Claude용 플러그인.

## 들어 있는 것
- `spss-analysis` 스킬: 분석 절차·기법별 안내, 원자료 보호 원칙, 결과 해석 규칙, SPSS 버전별(22 이상) 사용 조건
- `/spss-agent:setup` 명령(Claude Code 전용): Windows에서 실행파일 내려받기·확인값 검증, SPSS 점검, 분석 폴더 준비, Claude Code 연결을 Claude가 대신 진행

## 사용
1. Claude Code: `/plugin marketplace add beaver21c/stata_connect` → `/plugin install spss-agent@stata-connect`
2. 분석 폴더에서 `/spss-agent:setup` 실행 → 안내에 따라 승인
3. 새 세션에서 "SPSS 연결 점검해줘"

Claude 채팅 앱(데스크톱): Customize › Plugins › Add marketplace에 `beaver21c/stata_connect` 입력 → 스킬만 사용됨. SPSS 연결은 설명서 SPSS 페이지의 `.mcpb` 확장으로 설치.

지원: SPSS Statistics 22 이상(Windows), 설치 시 Python Essentials(동봉 Python) 포함 필요

## 데이터
이 플러그인은 외부 서버로 자료를 보내지 않음. 분석 중 AI에 전달되는 것은 SPSS 출력(원자료 행을 걸러 낸 결과)뿐임.

설명서: https://beaver21c.github.io/stata_connect/spss.html
