# stata_connect — Stata·SPSS 에이전트 패키지

채팅(Claude·Codex)으로 요청 → AI가 do-file·SPSS 문법 작성·수정 → **Stata·SPSS가 계산** → AI가 결과를 판독·검증·해석하는 분석 환경.
원자료 행은 AI로 보내지 않도록 명령 차단·출력 필터를 둠.

- **사용자 설명서·다운로드: https://beaver21c.github.io/stata_connect/** (SPSS: `/spss.html`, 원본 `site/`, main 반영 시 자동 배포)
- 설계서: [`docs/design/stata_agent_design.html`](docs/design/stata_agent_design.html)
- 구현 현황·검증 지위·실기 검증 체크리스트: [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md)

## 현재 상태 (v0.1.0, 개발 단계)

| 구분 | 상태 |
|---|---|
| MCP 서버(도구 17종), 원자료 보호(guard·출력 필터), do-file 섹션 편집, 버전 탐지, 재현 대조, 자가 점검·보고서, 클라이언트 설정 병합, 분석 스킬 | 구현 + 자동 테스트(Stata 없이 가짜 백엔드) |
| COM GUI 백엔드(stata-gui-mcp 1.1.0 래퍼), 배치 백엔드, PowerShell 설치 보조 | 코드 작성, **Windows·Stata 실기 미검증** |
| 사용자 설명서 사이트(GitHub Pages, Stata·SPSS 두 페이지): 설치 방법 비교(클릭 설치·Claude Code·Codex) + 다운로드 | 구현 |
| **시험판 배포**: Windows 단일 실행파일(설치 도우미 겸 MCP 서버)·Claude 데스크톱 확장 `.mcpb`·플러그인 마켓플레이스(`/stata-agent:setup`) | 구현 + CI Windows 빌드·점검, **실기 미검증** (IMPLEMENTATION_STATUS §11) |
| Stata 17 호환 | 코드·스킬 점검 + 17 미만 경고, 실기 미검증 (§12) |
| **SPSS 어댑터**(화면 없는 SPSS 엔진, 도구 13종, 문법 guard, 자가 점검, 스킬) | 구현 + 자동 테스트(가짜 `spss` 모듈로 엔진 통신까지), **실제 SPSS 미검증** (IMPLEMENTATION_STATUS §10) |
| 코드 서명·SPSS 실행파일 | 미착수 |

## 구조

```
stata_connect/
├── mcp_server/stata_agent/      MCP 서버 패키지(설계서 §5 mcp_server/)
│   ├── server.py                MCP 진입점(stdio)
│   ├── tool_specs.py            도구 명세·권한 등급(단일 원본)
│   ├── service.py               도구 동작: guard → 실행 → 출력 필터 → 기록
│   ├── backends/                com_gui(상류 래퍼)·batch_cli·applescript_mac
│   ├── guard/                   command_policy·output_filter·stata_lexer
│   ├── discovery.py             Stata 설치·에디션·라이선스 탐지
│   ├── dofile.py · project.py   do-file·폴더 규약
│   ├── editor_sync.py           Do-file Editor 갱신
│   ├── session_log.py           AI 사용 기록·공개문 초안
│   ├── log_compare.py           재현 수치 대조
│   ├── selftest.py · report.py  자가 점검 T1~T10·점검 보고서
│   ├── client_config.py         Claude Code·Desktop·Codex 설정 병합(분석 폴더 .mcp.json 포함)
│   ├── setup_wizard.py          설치 도우미(실행파일 더블클릭 시)
│   ├── hookguard.py             Claude Code 셸 명령 실행 전 검사
│   ├── resources.py             실행 형태별 경로·명령
│   └── cli.py                   stata-agent 명령
├── mcp_server/spss_agent/       SPSS 어댑터(엔진·guard·서비스·MCP 서버 spss)
├── .claude-plugin/              플러그인 마켓플레이스(marketplace.json)
├── plugins/stata-agent/         플러그인: skills/stata-analysis(스킬) + commands/setup.md(Claude Code 설치 명령)
├── plugins/spss-agent/          플러그인: skills/spss-analysis
├── packaging/                   단일 실행파일·.mcpb 빌드(build.py)·점검(smoke_test.py)
├── installer/                   doctor.ps1·register_com.ps1·configure_clients.py
├── site/                        사용자 설명서 사이트(index.html·spss.html·style.css·build.py)
├── docs/                        설계서·구현 현황
└── tests/                       자동 테스트
```

## 개발자 빠른 시작

```bash
python -m pip install -e ".[dev]"
python -m pytest -q                    # Stata 없이 실행 가능
stata-agent doctor                     # Stata 설치·라이선스·COM 점검
stata-agent init-project ./예제 --example
stata-agent configure --clients claude-code,codex --dry-run
stata-agent-mcp                        # MCP 서버(stdio)
stata-agent setup --dry-run            # 설치 도우미 점검 실행

# 배포 파일(Windows): 단일 exe + .mcpb
python -m pip install pyinstaller==6.22.3
python packaging/build.py && python packaging/smoke_test.py dist/stata-agent-0.1.0.exe

# SPSS
spss-agent doctor                      # SPSS 설치·내장 Python 탐지
spss-agent init-project ./spss예제 --example
spss-agent configure --clients claude-code,codex --dry-run
spss-agent-mcp                         # MCP 서버(stdio, 이름 spss)
```

Windows에서 COM 대화형 세션을 쓰려면 Stata Automation 등록(관리자 1회) 필요:

```powershell
powershell -ExecutionPolicy Bypass -File installer\register_com.ps1 -StataExe C:\Stata18\StataSE-64.exe
```

## 설정(환경변수)

`STATA_AGENT_STATA_EXE`(실행파일 고정), `STATA_AGENT_BACKEND`(auto/com/batch), `STATA_AGENT_MASK_SMALL_CELLS`(빈도표 소표본 마스킹 기준), `STATA_AGENT_UNIQUE_RATIO`(식별자 판정 비율) 등 — 전체 목록은 `mcp_server/stata_agent/config.py`.

## 의존

- [stata-gui-mcp](https://pypi.org/project/stata-gui-mcp/) 1.1.0 (MIT, shichengg) — COM GUI 세션 계층. 도구 목록은 노출하지 않고 내부 기능만 사용
- [mcp](https://pypi.org/project/mcp/) Python SDK
