# 구현 현황·검증 지위 (설계서 대비)

- 기준 설계서: [`docs/design/stata_agent_design.html`](design/stata_agent_design.html) (2026-10-29 설계안 원문, 수정하지 않음)
- 이 문서: 설계서의 어느 부분이 어떤 파일로 구현됐는지, 무엇이 검증됐고 무엇이 미검증인지 기록
- 지위 표기: **[1차 확인]** 원문·실제 실행으로 확인 / **[2차 확인]** 제3자 자료 / **[논리적 추론]** / **[미확인]** 실기 검증 필요
- 작성 환경 제약: Linux 클라우드 컨테이너, Stata·Windows 없음 → COM·배치·PowerShell은 코드 작성만, 실기 미검증

## 1. 범위 결정 (2026-10-29)

1. 구성 범위: 설계서 §5 골격 + Stata 없이 검증 가능한 계층 실제 구현 + COM·배치 백엔드 초안
2. stata-gui-mcp 활용: **pip 의존성 래퍼**(설계서 B안의 "래퍼" 선택지). 버전 1.1.0 고정, 내부 함수 의존

## 2. 설계서 ↔ 구현 대응

| 설계서 | 구현 파일 | 상태 |
|---|---|---|
| §5 MCP 진입점 | `mcp_server/stata_agent/server.py` | 구현·자동 테스트, Claude Code CLI stdio 연결 [1차 확인] |
| §7 도구 명세 16종 | `tool_specs.py`(단일 원본) + `service.py` | 구현·자동 테스트(가짜 백엔드) / 실기 미검증 |
| §5 com_gui | `backends/com_gui.py` | 구현(상류 래퍼), 가짜 상류로 흐름 테스트 / **실기 미검증** |
| §5 batch_cli | `backends/batch_cli.py` | 구현 / **실기 미검증** |
| §5 applescript_mac | `backends/applescript_mac.py` | 자리만(후순위) |
| §8.1 명령 차단 | `guard/command_policy.py`, `guard/stata_lexer.py` | 구현·차단/허용 사례 전수 테스트 |
| §8.2 출력 필터 | `guard/output_filter.py` | 구현·테스트(합성 로그 기준) |
| §6 버전 탐지 | `discovery.py` | 구현·테스트(공개 로그 형식 기준) / **실제 about 출력 대조 필요** |
| §10 do-file 규약 | `dofile.py`, `project.py` | 구현·테스트 |
| F3 편집기 갱신 | `editor_sync.py` | `doedit` 재호출 방식 / **탭 갱신·중복 미확인** |
| P6 사용 기록 | `session_log.py` | 구현·테스트 |
| P5 재현 대조 | `log_compare.py`, `service.reproduce` | 구현·테스트(가짜 배치) |
| §13.1 자가 점검 T1~T10 | `selftest.py` | 구현·테스트(가짜 백엔드) |
| §13.2 점검 보고서 | `report.py` | 구현·테스트(일련번호·등록자 제외 확인) |
| §9 스킬 | `skills/stata-analysis/SKILL.md`, `references/`, `templates/` | 작성. 템플릿은 코드 출력과 동기화 테스트 |
| §11 클라이언트 설정 | `client_config.py`, `installer/configure_clients.py` | 구현·테스트. Claude Code 등록 실제 CLI로 확인 [1차 확인] |
| §5 doctor·COM 등록 | `installer/doctor.ps1`, `installer/register_com.ps1` | 작성 / **실기 미검증(PowerShell 미실행)** |
| §13.4 자동 테스트 | `tests/`, `.github/workflows/ci.yml` | Ubuntu·Windows × Python 3.10·3.13 |
| §0 배포(exe·서명·mcpb·통합 설치) | — | **미착수(Phase 5)** |
| §0.6 안내 사이트 | `site/index.html`, `site/build.py`, `.github/workflows/pages.yml` | 구현: 설명서 + 분석 스킬 ZIP(확인값 포함). 설치 프로그램·`.mcpb` 칸은 "준비 중". **최초 1회 Pages 활성화 필요**(§3.5) |
| §0.6 Releases | — | **미착수**(설치 프로그램과 함께) |

## 3. 이번 작업에서 확인한 사실

### 3.1 stata-gui-mcp 1.1.0 (PyPI 휠 소스 직접 열람) [1차 확인]
- 세션 작업 스레드가 `app.DoCommand(command)`만 중계(server.py 119–129행) → 래퍼에서 COM 결과 메서드(`StReturnNumeric` 등) 직접 호출 불가
- 명령당 대기 180초 고정(`future.result(timeout=180)`, 147행) → 초과 시 세션이 새 명령을 받지 않음
- 스키마 도구가 `list in 1/{sample_rows}` 실행(1415행) → 설계서 §3의 P2 위배 지적이 사실로 확인됨
- 세션은 do-file 실행으로 생성, 레지스트리는 do-file 폴더의 `.stata-mcp/cache/task_registry.json`
- 여러 줄 코드는 임시 do-file로 실행 → 공식 문서상 `DoCommand`가 거부하는 `foreach`·`program define`(오류 10001, [2차 확인])을 우회
- 기본 차단 목록은 `!`, `shell`, `erase`, `rm`, `del`, `rmdir`, `rd`뿐(행 출력 차단 없음)

### 3.2 Codex (openai/codex 소스 main, 2026-10-29) [1차 확인]
- 설정 파일: `~/.codex/config.toml`(`CODEX_HOME` 우선) → 설계서 §0.1의 `%APPDATA%\Codex\config.json`은 소스에 없음 → 상충 해소
- `[mcp_servers.<이름>]`: `command`·`args`·`env`·`startup_timeout_sec`(실수)·`tool_timeout_sec`(실수 초)·`default_tools_approval_mode` 등, **알 수 없는 키 거부**
- 도구별 승인: `[mcp_servers.stata.tools.<도구>] approval_mode = "auto" | "prompt" | "writes" | "approve"` → 설계서 §14 "Codex 승인 정책 미확인" 해소
- 스킬: 사용자 `~/.agents/skills/<이름>/SKILL.md`, 저장소 `.agents/skills/`. `description` 필수
- 위험: 구버전 Codex는 `default_tools_approval_mode` 등 신규 키를 몰라 설정 전체를 거부할 가능성 [논리적 추론]

### 3.3 Claude Code·Claude Desktop
- `claude mcp add`: `-e`는 가변 인자 → `claude mcp add --transport stdio --scope user stata -e K=V -- 명령` 순서 필요 [1차 확인: CLI 도움말·실제 등록]
- 사용자 범위 등록은 `~/.claude.json` 최상위 `mcpServers`에 저장됨 [1차 확인: 이 환경 CLI 동작, 버전별 차이 가능] → 직접 편집 대신 CLI 사용
- `stata-agent-mcp`를 실제 CLI에 등록 → `claude mcp get stata` 결과 `Connected` [1차 확인]
- 권한 규칙 `mcp__stata__도구명`, `permissions.ask` 존재, `Read(/data/**)`는 프로젝트 루트 기준 [2차 확인: 공식 문서, 하위 조사]
- Claude 앱 스킬 업로드: `name`(소문자·숫자·하이픈, 64자, 폴더명 일치)·`description`(1,024자) 필수, 허용 필드 제한, ZIP 최상위에 스킬 폴더 [2차 확인: 공식 문서, 하위 조사]
- Claude Desktop 설정 파일 Windows 경로(`%APPDATA%\Claude\claude_desktop_config.json`): 공식 문서에서 확인 안 됨 [미확인] → 폴더가 있을 때만 병합
- MCPB: `binary` 서버 유형 존재, `manifest_version`은 사양 내 0.3/0.4 혼재 [2차 확인] → Phase 5에서 재확인

### 3.4 Stata
- `about` 출력 형식: 첫 줄 `Stata/MP 17.0 for Windows (64-bit x86-64)`·`StataNow/SE 19.5 ...`, 라이선스 `..., expiring 21 Jan 2024`(한 자리 일은 공백 채움)·`perpetual` [2차 확인: 공개 저장소 실제 로그]
- 배치: `/e`는 완료 후 대기 없이 종료, 로그는 현재 폴더에 do-file 이름으로 생성 [2차 확인: 공식 FAQ·매뉴얼 검색 발췌]
- 배치 종료코드는 오류여도 0이라는 보고 [2차 확인: Statalist 2014] → 로그의 `r(#);`로 판정
- COM 등록 `/Register` 또는 `/Regserver`, 해제 `/Unregister`, 객체 생성 시 주 창 표시 [2차 확인: 공식 자동화 페이지 검색 발췌]
- `UtilSetStataBreak`가 동기 `DoCommand` 실행을 중단하는지 [미확인] → `stata_break` 미구현
- `display 변수명`은 첫 관측치 값 출력 [2차 확인: Stata Journal 2006, 6(2)] → guard가 변수 목록을 알면 차단
- 블록 주석 중첩은 Mata 문서에만 명시 → guard는 비중첩으로 보수적 해석
- 최소 약어: list `l`, browse `br`, edit `ed`, display `di`, shell `sh`(`!`), xshell `xsh`, save `sa`, tabulate `ta`, outfile `ou`, outsheet `outs` [1차 확인: 공식 help 파일 사본]

### 3.5 설명서 사이트 (2026-10-29)
- 공개 주소: `https://beaver21c.github.io/stata_connect/`(GitHub Pages 프로젝트 사이트 주소 규칙)
- 저장소 공개 상태, Pages 미활성(`has_pages: false`), Release 0건 [1차 확인: GitHub API]
- 배포 방식: main 반영 시 Actions가 `site/build.py` 실행 → Pages 배포. Pages 소스를 "GitHub Actions"로 지정하는 설정은 저장소 관리자가 1회 수행해야 함 [논리적 추론: 워크플로 기본 토큰은 저장소 설정 변경 권한 없음, 실제 동작 미확인]
- Claude 앱 스킬 업로드 경로 `Customize › Skills › + › + Create skill › Upload a skill`, ZIP에 스킬 폴더 포함, 코드 실행(Settings › Capabilities › "Create and edit files") 필요, Free·Pro·Max·Team·Enterprise 사용 가능 [1차 확인: Claude 도움말 원문]
- Claude 앱 다운로드 주소 `https://claude.com/download` 접속 확인 [1차 확인]
- Codex 앱 안내 주소 `https://developers.openai.com/codex/app`: 이 작업 환경에서 접속 차단으로 미확인(설계서 참고자료 기재 주소 사용) [미확인]
- 스킬 ZIP은 항목 순서·시각을 고정해 같은 내용이면 같은 SHA-256 → 사이트에 확인값 게시

## 4. 설계서 대비 변경점

| 항목 | 설계서 | 구현 | 사유 |
|---|---|---|---|
| `stata_get_results` | COM 결과 메서드 | `display` 표지 출력을 로그에서 파싱 | 래퍼 구조상 COM 메서드 호출 불가(§3.1) |
| `stata_schema` | COM 메타데이터 메서드 | Stata 루프로 메타데이터만 출력 | 같은 사유. 표본 행은 출력하지 않음 |
| `stata_break` | `UtilSetStataBreak` | 미구현, 중단 방법 안내 | 동기 실행 중 끼어들 통로 없음 + 효과 미확인 |
| `log close _all` | 차단·치환 | 차단 + 대안(`log close _nmlog`) 제시 | 실행 파일을 몰래 바꾸지 않기 위함 |
| 추가 도구 | — | `stata_usage_summary` | §9 10단계 공개문 초안에 필요한 집계 |
| `stata_export` etable | — | `mstat(N)`만 기본, 그 밖은 custom 모드 | `mstat(r2)` 등은 모형별로 없을 수 있음 |
| `version` 선언 | 19.5 또는 19 | StataNow 19.5도 `version 19` | 보수적 선택 |
| Codex 설정 경로 | 두 위치 탐지 | `config.toml` 하나 | 소스 확인(§3.2) |

## 5. 원자료 보호 규칙 (guard)

| 규칙 | 대상 | 판정 |
|---|---|---|
| G01 | `list`·`browse`·`edit`·`listtab`·`listtex`·`extremes`·`duplicates list/examples`·`type` | 차단 |
| G02 | `display var[i]`, 변수 이름 직접 표시(변수 목록 확보 시), `` `=var[i]' `` 출력 | 차단 |
| G03 | `local/global/scalar = var[i]`, 매크로 평가식 관측치 추출 | 승인 필요 |
| G04 | Mata `st_data`·`st_view` 계열 / 상수 아닌 `stata()` 호출 | 차단 / 승인 필요 |
| G05 | `shell`·`!`·`winexec`·`xshell`·`python`·`java`·`javacall` | 차단 |
| G06 | `erase`·`rm`·`rmdir` | 차단 |
| G07 | `log close _all` | 차단(대안 제시) |
| G08 | `exit, STATA` | 차단 |
| G09 | `export`·`outsheet`·`outfile`: 프로젝트 밖·`data/` / 안 | 차단 / 승인 필요 |
| G10 | `save`·`saveold`·`copy`·`file open, write`·`putexcel set`: 밖·`data/` / 파일명 없는 save | 차단 / 승인 필요 |
| G11 | `cd` | 승인 필요 |
| G12 | 매크로로 시작하는 동적 명령 | 승인 필요 |
| G13 | `ssc/net/ado install` | 승인 필요(전용 도구 권장) |
| G14 | `tab`·`table`·`tabdisp`·`levelsof`·`codebook` | 실행 전 고유값 비율 점검(기본 0.9 초과 시 승인 필요) |
| G15 | `do`·`run`·`include` | 하위 파일 재귀 검사, 못 읽으면 승인 필요 |

출력 필터: 행 출력 명령 결과·목록 형식 행(`  1. | … |`)·빈도 1 범주가 대부분인 빈도표 차단, 선택적 소표본 셀 마스킹(`STATA_AGENT_MASK_SMALL_CELLS`).

알려진 한계(guard는 사고 방지 장치이며 보안 경계가 아님, 설계서 §8.3)
- 한 줄 `if 조건 명령` 내부 명령, 매크로 확장 후 드러나는 명령은 정적 판별 불가
- `summarize, detail`의 최소·최대 개별 값(Smallest/Largest)은 차단하지 않음
- `file read` 후 매크로 표시, 그래프 표식 등 우회 경로
- Claude Code·Codex의 자체 파일·셸 도구가 `data/`를 여는 경우 → 프로젝트 `.claude/settings.json`의 `Read(/data/**)` 거부 규칙으로 일부 차단, 셸 스크립트 경유는 차단 안 됨 [2차 확인]

## 6. 상류(stata-gui-mcp) 의존 목록

`backends/com_gui.py`의 `REQUIRED_SYMBOLS`: `PYWIN32_READY`, `PYWIN32_ERROR`, `SESSIONS`, `StataSession`, `_run_dofile_session`, `_run_stata_commands`, `_session_transaction`, `_registry_for_session`, `_update_task_registry`, `_session_tool`

상류 버전을 올릴 때
1. `pyproject.toml`과 `REQUIRED_UPSTREAM_VERSION`을 함께 수정
2. `tests/test_upstream_compat.py` 통과 확인
3. 새 버전 소스에서 §3.1 사실(180초 제한, `DoCommand` 중계, 레지스트리 위치) 재확인

## 7. 실기 검증 체크리스트 (Windows PC, Phase 0~2)

준비
```powershell
git clone https://github.com/beaver21c/stata_connect; cd stata_connect
python -m pip install -e ".[dev]"
python -m pytest -q
powershell -ExecutionPolicy Bypass -File installer\doctor.ps1
powershell -ExecutionPolicy Bypass -File installer\register_com.ps1 -StataExe C:\Stata18\StataSE-64.exe
stata-agent doctor
stata-agent configure --clients claude-code --dry-run
stata-agent selftest --client "Claude Code"
```

확인 항목
- [ ] `doctor.ps1`·`register_com.ps1` 실행·한글 출력(UTF-8 BOM 저장) 정상
- [ ] 실제 `about` 출력이 `parse_about`으로 해석되는지(Stata 17·18·19.5, 만료 라이선스 포함) → 실제 출력을 `tests/test_discovery.py` 사례로 추가
- [ ] T1~T10 전 항목 통과(특히 `%24.0g` 숫자 서식 출력, `egen tag` 고유값 점검 코드, 스키마 루프)
- [ ] 상류 래퍼 실행 틀(`log using`·`cd`·`do`)을 거친 뒤에도 r()·e() 결과가 유지되는지(`stata_get_results`)
- [ ] F1: 창 1개에 Results·Do-file Editor 표시
- [ ] F2: 같은 창에서 섹션 실행·메모리 유지, 연구자가 Command 창에 입력한 상태를 AI가 이어받음
- [ ] F3: `doedit` 재호출 시 탭 갱신·중복 여부 → `editor_sync.py` 방식 확정
- [ ] F4: 로그 수치 = 채팅 해석 수치
- [ ] 설계서 §2.2 시나리오 1~6
- [ ] 180초 초과 명령의 동작과 안내 문구
- [ ] 배치 백엔드(`stata_reproduce`) 로그 위치·라이선스 만료 감지
- [ ] Codex 앱에서 `config.toml` 병합 결과 로드·도구별 승인 동작

## 8. 다음 단계

| 단계 | 내용 |
|---|---|
| Phase 0 | 위 체크리스트로 COM 래퍼 실기 검증, F3 방식 확정 |
| Phase 2 | Stata 17·18·19.5 각각 doctor·selftest 통과, 만료 라이선스 감지 |
| Phase 3 | 8개 기법 시나리오(auto·공개 패널자료) 기준값 대조, references 기준값 출처 보강 |
| Phase 4 | Codex 앱 동일 시나리오 |
| Phase 5 | 단일 exe 빌드·코드 서명·`.mcpb` 패킹·통합 설치 프로그램·Release 자동화 → 설명서 사이트 다운로드 칸 "준비 중" 해제 |
| 미정 | 저장소 라이선스(공개 배포 전 결정 필요) |

## 9. 참고자료

직접 열람: 아래 1·2. 그 밖은 하위 조사 결과로 확인된 주소이며 이번 작업에서 원문을 다시 열지 않음.

1. shichengg. (2026). *stata-gui-mcp* (Version 1.1.0) [Software]. PyPI. https://pypi.org/project/stata-gui-mcp/
2. OpenAI. (2026). *codex* [Software, codex-rs/config/src/mcp_types.rs]. GitHub. https://github.com/openai/codex/blob/main/codex-rs/config/src/mcp_types.rs
3. StataCorp. (n.d.). *Using Stata Automation*. https://www.stata.com/automation/
4. StataCorp. (n.d.). *Stata batch mode (Windows FAQ)*. https://www.stata.com/support/faqs/windows/batch-mode/
5. Statalist. (2014). *Stata batch mode exit status on error* [Forum thread]. https://www.statalist.org/forums/forum/general-stata-discussion/general/291809-stata-batch-mode-exit-status-on-error
6. Anthropic. (n.d.). *Connect Claude Code to tools via MCP*. https://code.claude.com/docs/en/mcp
7. Anthropic. (n.d.). *Configure permissions*. https://code.claude.com/docs/en/permissions
8. Anthropic. (n.d.). *Extend Claude with skills*. https://code.claude.com/docs/en/skills
9. Model Context Protocol. (n.d.). *MCPB manifest specification*. GitHub. https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md
10. `about` 출력 형식 예시(공개 저장소 로그): https://github.com/remlapmot/ivonesamplemr/blob/b932d68ce77df394e4422cd01c95e4ee707dfa51/cscripts/install.log
11. Anthropic. (n.d.). *Use skills in Claude*. Claude Help Center. https://support.claude.com/en/articles/12512180-use-skills-in-claude (직접 열람)
12. Stata Journal (2006), 6(2) 수록 글(저자·제목 미확인, `display` 변수명 동작 서술): https://journals.sagepub.com/doi/pdf/10.1177/1536867X0600600209
