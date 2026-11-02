# 구현 현황·검증 지위 (설계서 대비)

- 기준 설계서: [`docs/design/stata_agent_design.html`](design/stata_agent_design.html) (2026-10-29 설계안 원문, 수정하지 않음)
- 이 문서: 설계서의 어느 부분이 어떤 파일로 구현됐는지, 무엇이 검증됐고 무엇이 미검증인지 기록
- SPSS 어댑터(설계서 범위 밖 확장)는 §10, 설치·배포 두 방향(패키지·Claude Code)은 §11, Stata 17 호환 점검은 §12, SPSS 배포·22 호환은 §13, 기존 파일 가져오기·연구자 조작 감지는 §14, 그래프 보기는 §15, pystata 보조 백엔드는 §16, Claude 앱 직접 등록·Desktop Commander 대응은 §17, 재설치 안정성은 §18, 연결 진단은 §19
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
| (확장) pystata | `backends/pystata_proc.py`, `backends/worker.py` | 보조 백엔드(지정할 때만), 가짜 pystata로 자식 프로세스 통신 테스트 / **실기 미검증**(§16) |
| (확장) 그래프 보기 | `graphs.py`, `service.view_graph`, `server.to_content` | 구현·테스트(가짜 백엔드), 이미지 반환 / **실기 미검증**(§15) |
| §8.1 명령 차단 | `guard/command_policy.py`, `guard/stata_lexer.py` | 구현·차단/허용 사례 전수 테스트 |
| §8.2 출력 필터 | `guard/output_filter.py` | 구현·테스트(합성 로그 기준) |
| §6 버전 탐지 | `discovery.py` | 구현·테스트(공개 로그 형식 기준) / **실제 about 출력 대조 필요** |
| §10 do-file 규약 | `dofile.py`, `project.py` | 구현·테스트 |
| F3 편집기 갱신 | `editor_sync.py` | `doedit` 재호출 방식 / **탭 갱신·중복 미확인** |
| P6 사용 기록 | `session_log.py` | 구현·테스트 |
| P5 재현 대조 | `log_compare.py`, `service.reproduce` | 구현·테스트(가짜 배치) |
| §13.1 자가 점검 T1~T10 | `selftest.py` | 구현·테스트(가짜 백엔드) |
| §13.2 점검 보고서 | `report.py` | 구현·테스트(일련번호·등록자 제외 확인) |
| §9 스킬 | `plugins/stata-agent/skills/stata-analysis/` (`SKILL.md`, `references/`, `templates/`) | 작성. 템플릿은 코드 출력과 동기화 테스트. 플러그인 폴더로 이동(§11) |
| §11 클라이언트 설정 | `client_config.py`, `installer/configure_clients.py` | 구현·테스트. Claude Code 등록 실제 CLI로 확인 [1차 확인] |
| §5 doctor·COM 등록 | `installer/doctor.ps1`, `installer/register_com.ps1` | 작성 / **실기 미검증(PowerShell 미실행)** |
| §13.4 자동 테스트 | `tests/`, `.github/workflows/ci.yml` | Ubuntu·Windows × Python 3.10·3.13 |
| §0 배포(exe·서명·mcpb·통합 설치) | `packaging/`, `setup_wizard.py`, `.github/workflows/package-windows.yml` | **시험판**: 단일 exe·설치 도우미 구현, CI Windows 빌드·점검(§11). `.mcpb`는 2026-11-02 폐기(§11.7). 코드 서명 미착수, **실기 미검증** |
| §0.6 안내 사이트 | `site/index.html`, `site/build.py`, `.github/workflows/pages.yml` | 구현: 설치 방법 비교(A 클릭 설치·B Claude Code·Codex) + 시험판 exe·스킬 ZIP(확인값) + `latest.json` |
| §0.6 Releases | — | GitHub Releases 대신 Pages `downloads/`로 배포(세션 권한상 태그·Release 생성 불가, 같은 빌드 산출물 사용) |

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
- MCPB: `binary` 서버 유형 존재, `manifest_version`은 사양 내 0.3/0.4 혼재 [2차 확인] → Phase 5에서 재확인(2026-11-02 `.mcpb` 폐기, §11.7)

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
| 추가 도구 | — | `stata_view_graph`(이미지 반환) | 사용자 결정 "그래프는 AI가 볼 수 있어야 함"(2026-11-01). 텍스트 출력 필터를 거치지 않는 새 경로 → 그림 등급·승인으로 관리(§15) |
| 추가 백엔드 | com_gui·batch_cli·applescript | pystata(보조, 지정할 때만) | 사용자 결정 "추가하되 주력은 아님"(2026-11-01, §16) |
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
| G16 | `graph export`·`graph save`·그래프 명령의 `saving()`: 프로젝트 밖·`data/` / 매크로 경로 | 차단 / 경고(§15) |

출력 필터: 행 출력 명령 결과·목록 형식 행(`  1. | … |`)·빈도 1 범주가 대부분인 빈도표 차단, 선택적 소표본 셀 마스킹(`STATA_AGENT_MASK_SMALL_CELLS`).

알려진 한계(guard는 사고 방지 장치이며 보안 경계가 아님, 설계서 §8.3)
- 한 줄 `if 조건 명령` 내부 명령, 매크로 확장 후 드러나는 명령은 정적 판별 불가
- `summarize, detail`의 최소·최대 개별 값(Smallest/Largest)은 차단하지 않음
- `file read` 후 매크로 표시 등 우회 경로. 그래프로 전송되는 개별 값은 §15 등급 판정으로 관리(정적 추정이라 완전하지 않음)
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
| Phase 5 | 단일 exe·설치 도우미·플러그인 → **시험판 구현(§11)**, `.mcpb`는 폐기(§11.7). 남은 일: 코드 서명, §11.6 실기 검증, 검증 후 "시험판" 표기 해제 |
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
13. Narçiçek, M. R. (2026). *spss-mcp-extended* (Version 2.0.0) [Software]. PyPI. https://pypi.org/project/spss-mcp-extended/ (휠 소스 직접 열람, 코드 미사용·사실 확인용)
14. Anthropic. (n.d.). *Plugin structure and testing*. Claude Docs. https://claude.com/docs/plugins/build (직접 열람, 2026-10-31)
15. Anthropic. (n.d.). *Create a marketplace*. Claude Code Docs. https://code.claude.com/docs/en/plugin-marketplaces (직접 열람)
16. Anthropic. (n.d.). *Advanced setup*. Claude Code Docs. https://code.claude.com/docs/en/setup (직접 열람: 요금제·Windows 요건)
17. Anthropic. (n.d.). [Claude Code 데스크톱 앱 안내, 문서 제목 미확인]. Claude Code Docs. https://code.claude.com/docs/en/desktop (직접 열람, 문서 앞부분 100,000자까지만)
18. Anthropic. (n.d.). [Claude Code hooks 안내, 문서 제목 미확인]. Claude Code Docs. https://code.claude.com/docs/en/hooks (직접 열람, 앞부분)
19. Anthropic. (2026). *@anthropic-ai/mcpb* (Version 2.1.2) [Software]. npm. https://www.npmjs.com/package/@anthropic-ai/mcpb (npm 설치 후 manifest v0.3 스키마 직접 열람·`validate` 실행)
20. StataCorp. (n.d.). *Stata 17: Tables of estimation results*. https://stata.com/stata17/tables-of-estimation-results (검색 결과 요약으로 확인, 원문 미열람)
21. StataCorp. (n.d.). *[U] 5 Editions of Stata*. https://www.stata.com/manuals/u5.pdf (검색 결과 요약으로 확인: 17부터 IC → BE, 원문 미열람)
22. Statalist. (2024). *Help with saving documents using etable* [Forum thread]. https://www.statalist.org/forums/forum/general-stata-discussion/general/1760443-help-with-saving-documents-using-etable (검색 결과 요약으로 확인, 원문 미열람)
23. IBM. (n.d.). *Python Reference Guide for IBM SPSS Statistics* (Version 26) [PDF]. https://www.ibm.com/docs/en/SSLVMB_26.0.0/pdf/en/Python_Reference_Guide_for_IBM_SPSS_Statistics.pdf (검색 결과 요약으로 확인: 2.7·3.4 동봉, 원문 미열람 — 이 작업 환경에서 www.ibm.com 접속 불가)
24. IBM. (n.d.). *Running Python code with Python* (Version 27) [Documentation]. https://ibm.com/support/knowledgecenter/SSLVMB_27.0.0/statistics_python_plugin_uber_project_ddita/spss/programmability_option/python_uber_python3.html (검색 결과 요약으로 확인: 27부터 Python 2.x 미동봉, 원문 미열람)
25. IBM Community. (n.d.). *Get Essentials for SPSS* [Library document]. https://community.ibm.com/community/user/viewdocument/get-essentials-for-spss?CommunityKey=886b6874-0fb1-402c-8243-c70ef8179a99&tab=librarydocuments (검색 결과 요약으로 확인: 22부터 Python Essentials 본 설치 통합, 원문 미열람)
26. IBM. (n.d.). *spss.StartSPSS Function (Python)* (Version 26) [Documentation]. https://www.ibm.com/support/knowledgecenter/en/SSLVMB_26.0.0/statistics_python_plugin_uber_project_ddita/spss/programmability_option/python_package_startspss.html (검색 결과 요약으로 확인: 세션이 있으면 동작 없음, 원문 미열람)
27. IBM. (n.d.). *OMS* (Version 24) [Command syntax reference]. https://www.ibm.com/support/knowledgecenter/SSLVMB_24.0.0/spss/base/syn_oms.html (검색 결과 요약으로 확인: 형식 도입 버전, 원문 미열람)
28. IBM. (n.d.). *ES Subcommand (T-TEST command)* [Command syntax reference]. https://www.ibm.com/support/knowledgecenter/SSLVMB_sub/statistics_reference_project_ddita/spss/base/syn_t-test_es.html (검색 결과 요약으로 확인, 원문 미열람)

## 10. SPSS 어댑터 (2026-10-30)

### 10.1 결정
- 대상: IBM SPSS Statistics, **화면 없이 실행**(사용자 결정)
- 엔진: **자체 작성**(사용자 결정). 제3자 `spss-mcp-extended`는 사례 값을 AI에 반환하는 도구(`spss_read_data`, 최대 50행 표)가 있고 배포 1회·의존성 다수라 래퍼로 쓰지 않음 [1차 확인: 2.0.0 휠 소스]
- 구조: 같은 저장소의 별도 패키지 `mcp_server/spss_agent/`(MCP 서버 이름 `spss`). 사용 기록·보고서·클라이언트 설정 병합·로그 대조는 Stata 패키지 모듈을 일반화해 공유

### 10.2 구현 대응
| 구성 | 파일 | 상태 |
|---|---|---|
| 엔진(SPSS 내장 Python 서브프로세스, JSON 줄 통신, OMS 텍스트 수집, 사전·고유값 조회) | `engine_script.py`, `engine.py` | 구현. 가짜 `spss` 모듈로 서브프로세스 통신·오류·시간 초과·재기동까지 테스트. Python 2.7·3.4 겸용(§13) / **실제 SPSS 미검증** |
| 설치 탐지 | `discovery.py` | 구현·테스트(임시 폴더) / 실제 설치 미검증 |
| 문법 guard(S01~S15) | `guard/policy.py` | 구현·차단/허용/승인 사례 테스트 |
| 출력 필터 | `guard/output_filter.py` | 구현(합성 출력 기준) / **OMS TEXT 실제 형식 미확인** |
| .sps 규약·00_master.sps | `syntaxfile.py`, `project.py` | 구현·테스트 |
| 도구 14종·서비스·MCP 서버(§14 가져오기 포함) | `tool_specs.py`, `service.py`, `server.py` | 구현·테스트, Claude Code CLI stdio 연결 `Connected` [1차 확인] |
| 자가 점검 T1~T10 | `selftest.py` | 가짜 엔진으로 전 항목 통과 / 실기 미검증 |
| 스킬 | `plugins/spss-agent/skills/spss-analysis/` | 작성, 템플릿 동기화 테스트 |
| 명령줄 | `spss-agent`(doctor·selftest·init-project·configure·render-templates·serve·setup·hook-guard) | 구현 |

### 10.3 확인한 사실과 지위
- SPSS 내장 Python(`<설치폴더>\Python3\python.exe`)에서 `import spss` → `spss.StartSPSS()` → `spss.Submit(문법 문자열)` → `spss.GetLastErrorLevel()` → `spss.StopSPSS()` 흐름, SPSS가 표준출력에 잡음을 내므로 파일로 응답 [2차 확인: 제3자 구현 소스]
- 출력 수집 `OMS /TAG=... /SELECT ALL /DESTINATION FORMAT=TEXT OUTFILE='...'.` ~ `OMSEND TAG=...` [2차 확인: 제3자 구현 소스]
- 설치 경로 `Program Files\IBM\SPSS Statistics\<버전>\stats.exe`, 레지스트리 `SOFTWARE\IBM\SPSS Statistics\<버전>`의 `InstallationDirectory` [2차 확인: 제3자 구현 소스]. 구버전 경로 `IBM\SPSS\Statistics\<버전>`은 [논리적 추론]
- external mode는 일반 사용자 화면 없이 새 인스턴스로 동작 [2차 확인: IBM Community 게시글]
- `spss.GetVariableName·GetVariableLabel·GetVariableType·GetVariableFormat·GetVariableMeasurementLevel·GetCaseCount`, `spss.Cursor(...).fetchall()` [미확인: IBM 원문 미열람]
- OMS 형식: DOC·XLS·PDF는 17부터, XLSX는 21부터, DOC는 28.0.1 전까지 .doc 형식 [2차 확인: IBM OMS 문서 검색 요약]. `INSERT ... SYNTAX=INTERACTIVE ERROR=STOP`, 명령어 3글자 약어 허용 [미확인: 일반 지식]
- 시험 중 결함 2건 발견·수정: BOM 포함 .sps를 INSERT로 불러올 때 첫 명령 미검사, 실패 명령의 오류 수준이 정리 명령에 덮어써짐

### 10.4 Stata판과 다른 점
| 항목 | Stata | SPSS |
|---|---|---|
| 실행 화면 | 가시 GUI(COM) | 화면 없음(엔진) |
| 저장결과 조회 | `stata_get_results`(r()·e()) | 없음 → 출력 표에서 인용 |
| 편집기 표시·실행 중단 | `stata_show_in_editor`·`stata_break` | 없음 |
| 실행 시간 제한 | 명령당 180초(상류 고정) | 요청당 900초(`SPSS_AGENT_TIMEOUT`), 초과 시 엔진 종료·재기동 |
| 재현 확인 | 배치 실행(`/e`) | 새 엔진에서 00_master.sps 목록 순서대로 재실행 |
| 기록 폴더 | `.stata-agent/` | `.spss-agent/` |

### 10.5 SPSS 원자료 보호 규칙
| 규칙 | 대상 | 판정 |
|---|---|---|
| S01 | `LIST`, `PRINT`(FORMATS·SPACE·EJECT 제외), OUTFILE 없는 `WRITE`, 목록형 `SUMMARIZE`, MATRIX 안 `PRINT` / `REPORT` / `EXAMINE ... EXTREME` | 차단 / 승인 필요 / 경고 |
| S04 | `BEGIN PROGRAM`(Python·R) / `MATRIX` | 차단 / 승인 필요 |
| S05·S06 | `HOST` / `ERASE` / `PERMISSIONS` | 차단 / 차단 / 승인 필요 |
| S07 | TAG 없는 `OMSEND` / 사용자 `OMS` | 차단 / 승인 필요 |
| S09·S10 | `SAVE TRANSLATE`·`EXPORT`·`WRITE OUTFILE`(자료 반출), `SAVE`·`XSAVE`·`OUTPUT EXPORT/SAVE`: 프로젝트 밖·`data/` / 안(반출) / 파일 핸들 | 차단 / 승인 필요 / 승인 필요 |
| S11·S12 | `CD` / 매크로 호출(`!`) / `DEFINE` | 승인 필요 / 승인 필요 / 경고 |
| S14 | `FREQUENCIES`·`CROSSTABS`·`CTABLES`, `MEANS`·`EXAMINE ... BY` | 실행 전 고유값 점검(엔진이 개수만 계산) |
| S15 | `INSERT`·`INCLUDE` | 하위 파일 재귀 검사 |

### 10.6 SPSS 실기 검증 체크리스트 (Windows + SPSS)
```powershell
python -m pip install -e ".[dev]"
spss-agent doctor
spss-agent selftest --client "Claude Code"
spss-agent configure --clients claude-code --dry-run
```
- [ ] 엔진 기동: SPSS 내장 Python 경로, 라이선스, 기동 시간(설계상 180초 제한)
- [ ] T1~T10 통과, 특히 T4(출력 숫자 표시 형식)·T9(동시 2개 엔진 기동 라이선스)
- [ ] OMS TEXT 실제 출력 형식 확보 → `tests/test_spss.py` 필터 사례를 실제 출력으로 교체(사례 목록 표 제목·빈도표 행 형태, 한국어 출력 언어 포함)
- [ ] `spss.Cursor`·변수 정보 함수 동작(대용량 자료 처리 시간 포함)
- [ ] .sps(BOM 포함 UTF-8) 한국어 주석·값 라벨 처리, `INSERT ... SYNTAX=INTERACTIVE ERROR=STOP` 동작
- [ ] OMS DOC·XLSX 내보내기 파일 생성

### 10.7 설명서 사이트 SPSS 페이지 (2026-10-30)
- `site/spss.html`(SPSS 안내) 추가, `index.html`과 상단 "사용하는 프로그램: Stata / SPSS" 전환으로 연결, 공용 스타일 `site/style.css`
- 다운로드: SPSS 분석 스킬 ZIP(`spss-analysis-버전.zip`, 확인값 게시), 설치 프로그램은 "준비 중"
- 페이지에 [미확인]으로 남긴 내용: 지원 SPSS 버전 범위, 재현 기능의 동시 실행 라이선스 영향, SPSS 본체의 SEM 미지원(일반 지식)

## 11. 설치·배포: 패키지 방향과 Claude Code 방향 (2026-10-31)

### 11.1 결정
- 요청: Stata 실행 검증과 별개로, 처음 쓰는 사람이 사전 준비를 클릭 몇 번으로 끝내도록 패키지·설명 보완 + Claude 유료 이용자의 Claude Code 활용 방향 병행 검토
- 결론: 두 방향 모두 제공하고 **같은 단일 실행파일**을 공유
  - 방향 A(클릭 설치, Claude 채팅): `.mcpb` 확장 더블클릭 + 플러그인 마켓플레이스로 스킬 추가 + (선택) 설치 도우미로 COM 등록
    - 2026-11-02 변경: `.mcpb` 폐기 → 설치 도우미 하나로 Stata 확인·COM 등록·Claude 앱 설정 직접 등록(§11.7)
  - 방향 B(Claude Code에게 맡기기): 플러그인의 `/stata-agent:setup` 명령 → Claude Code가 내려받기·확인값 대조·설치 도우미 실행·분석 폴더 준비를 대신 수행
  - Codex: 설치 도우미 더블클릭(설정 병합·스킬 복사)

### 11.2 구현 대응
| 구성 | 파일 | 상태 |
|---|---|---|
| 단일 실행파일(PyInstaller, 파이썬 불필요) | `packaging/build.py`, `packaging/entry.py` | CI Windows 빌드 + `packaging/smoke_test.py` 10항목. 이 환경(Linux)에서 같은 절차 시험 빌드·점검 통과 [1차 확인] / Windows 산출물은 CI 결과로 확인 |
| 인자 없는 실행 | `cli._default_argv` | 콘솔(더블클릭) → 설치 도우미, 입력 연결(MCP 클라이언트) → 서버 |
| 설치 도우미 | `setup_wizard.py`, `stata-agent setup` | 실행파일 고정 위치 복사(`%LOCALAPPDATA%\StataAgent`) → Stata 확인 → COM 등록(UAC, 선택) → 분석 폴더 → 앱 연결. 자동 테스트 / **실기 미검증** |
| COM 등록 | `stata-agent register-com` | PowerShell `Start-Process -Verb RunAs`로 `<Stata> /Register` / **실기 미검증** |
| ~~`.mcpb` 확장~~ **폐기(2026-11-02, §11.7)** | (삭제) `packaging/build.py manifest()` | manifest v0.3, `binary` 서버, `user_config`(Stata 실행파일·소표본 가림 기준), 도구 목록은 `tool_specs`에서 생성. 공식 CLI `mcpb validate` 통과 [1차 확인] / Claude 앱 설치 화면 **실기 미검증** |
| 플러그인 마켓플레이스 | `.claude-plugin/marketplace.json`, `plugins/stata-agent`, `plugins/spss-agent` | `claude plugin validate` 통과, 가짜 HOME에서 `marketplace add`·`install`·`details` 확인(Claude Code 2.1.314) [1차 확인] / claude.ai 화면 추가 **실기 미검증** |
| Claude Code 설치 명령 | `plugins/stata-agent/commands/setup.md` | 명령줄 인자는 테스트가 파서로 검사 / Claude Code 실제 수행 **실기 미검증** |
| 분석 폴더 `.mcp.json` | `client_config.merge_project_mcp` | `${LOCALAPPDATA}` 확장 사용(경로에 사용자명 미기록) |
| 실행 전 검사(hook) | `hookguard.py`, `stata-agent hook-guard`, 프로젝트 `.claude/settings.json` | 셸 명령의 `data/`·원자료 확장자·Stata 직접 실행(실행파일·COM·pystata·stata_setup·sfi) 차단(종료 코드 2). 자동 테스트 / Windows Claude Code에서 **실기 미검증**. 이 문자열들을 쓰지 않는 스크립트 파일 실행은 막지 못함 |
| 출력 인코딩 | `cli._utf8_when_piped` | 출력이 다른 프로그램으로 넘어가면 UTF-8 고정(Windows 기본 코드페이지 회피) |
| 사용권 고지 | `THIRD_PARTY_NOTICES.txt` | 빌드 환경의 설치 정보로 자동 생성(stata-gui-mcp MIT 등) |
| 배포 | `.github/workflows/package-windows.yml`, `pages.yml`, `site/build.py --binaries` | Pages `downloads/`에 exe·`latest.json`·SHA256SUMS(`.mcpb`는 2026-11-02 제거) |

### 11.3 확인한 사실과 지위
- (폐기된 `.mcpb`에 관한 기록) MCPB [1차 확인]: manifest v0.3 필드·`user_config` 형식(`string|number|boolean|directory|file`), `${__dirname}`·`${user_config.키}` 치환, win32 재정의 예시의 `.exe` 명시(MANIFEST.md, mcpb 2.1.2 스키마). 서명 안 된 묶음은 `mcpb info`에서 "Not signed" 표시 — Claude 앱의 경고 문구는 [미확인]
- 비워 둔 `user_config` 값의 전달 형태 [미확인] → 서버가 빈 값·채워지지 않은 `${…}`를 미설정으로 처리(`config._env`)
- 플러그인 [1차 확인]: 매니페스트 위치 `.claude-plugin/plugin.json`, 스킬 `skills/<이름>/SKILL.md`, 최상위 `bin/`이 있으면 claude.ai·Cowork 설치 불가, 로컬 MCP 서버는 채팅에서 무시됨, 플러그인 MCP 도구 이름은 `mcp__plugin_<플러그인>_<서버>__<도구>`
  - → MCP 서버를 플러그인에 넣지 않음(기존 권한 규칙 `mcp__stata__*`와 이름이 달라짐)
- Claude Code [1차 확인]: Pro·Max·Team·Enterprise 등 유료 요금제 필요(무료 제외), Windows 기본 설치에 관리자 권한·Git 불필요(Git 없으면 PowerShell 도구 사용), 데스크톱 앱 Code 탭에서 로컬 폴더 세션 가능, 프로젝트 `.mcp.json`은 첫 사용 시 승인 창·`${VAR}` 확장
- Claude Code 원자료 보호 한계 [1차 확인]: Read·Edit 거부 규칙은 인식된 셸 파일 명령(cat 등)에는 적용되나 스크립트가 직접 파일을 여는 경우에는 미적용, Windows 기본 환경은 sandbox 미지원 → hook으로 보완하나 문자열 조립 등으로 우회 가능 [논리적 추론]
- 데스크톱 앱 Code 탭에서 `claude` 명령이 PATH에 있는지 [미확인] → 방향 B는 사용자 범위 등록(`claude mcp add`) 대신 분석 폴더 `.mcp.json` 사용
- PyInstaller 단일 파일 실행파일은 백신 오탐 사례가 알려져 있음 [미확인: 이 저장소 산출물로는 미관찰]

### 11.4 두 방향 비교(설명서 사이트 `#choose`와 같은 내용)
| 항목 | A 클릭 설치(채팅) | B Claude Code |
|---|---|---|
| 사용자 조치 | 설치 도우미 1개 더블클릭 + 플러그인 추가(2026-11-02 `.mcpb` 폐기 후) | 플러그인 추가 + `/stata-agent:setup` + 승인 |
| 설치 문제 해결 | 설명서 참조 | Claude가 오류 출력 판독 |
| 원자료 보호 | ~~MCP 도구 경로만 존재(채팅은 PC 명령 실행 불가) → 더 엄격 [논리적 추론]~~ → **정정(2026-11-02, §17)**: Claude 앱도 Desktop Commander 등 PC 명령 도구가 켜져 있으면 Stata 직접 실행·파일 열람 가능 [1차 확인: 사용자 PC 실기]. 그 도구를 끈 상태에서만 MCP 도구 경로만 남음 | 셸 실행 가능 → 거부 규칙 + hook, 우회 가능성 잔존 |
| 요금제 | Pro 이상 권장 | Pro 이상 필수 [1차 확인] |

### 11.5 설계서 대비 변경점
- 설계서의 "통합 설치 프로그램(StataAgentSetup.exe)" → 실행파일 하나가 설치 도우미·MCP 서버·hook 역할을 겸함(별도 설치 프로그램 없음)
- Claude 데스크톱 앱 연결: 설정 파일 직접 병합(Windows 경로 미확인) 대신 `.mcpb` 확장(공식 설치 화면) 우선
  - 2026-11-02 번복: 실기에서 `.mcpb`가 열리지 않아 폐기 → 설치 도우미의 설정 파일 직접 등록으로 전환(§11.7)
- 스킬 배포: ZIP 업로드 외에 플러그인 마켓플레이스(자동 갱신) 추가. 스킬 원본 위치 `skills/` → `plugins/<플러그인>/skills/`

### 11.6 실기 검증 체크리스트(Windows)
- [ ] 다운로드한 exe 더블클릭 → SmartScreen 문구·"추가 정보 → 실행" 경로, 한글 콘솔 출력·입력
- [ ] 설치 도우미: `%LOCALAPPDATA%\StataAgent` 복사, COM 등록 UAC 승인·거절 각각, Codex 설정 병합 결과
- [폐기] ~~`.mcpb` 더블클릭 → Claude 앱 설치 화면, 서명 경고 문구, `user_config` 비워 둘 때 서버 동작, 도구 19종 표시~~ → 실기 결과 열리지 않음, `.mcpb` 폐기(§11.7)
- [ ] Claude 앱 Customize › Plugins › Add marketplace(`beaver21c/stata_connect`) → stata-agent 스킬 표시(채팅·Code 탭)
- [ ] Code 탭에서 `/stata-agent:setup` 전 과정, 새 세션의 `.mcp.json` 승인 창, `${LOCALAPPDATA}` 확장
- [ ] Code 탭(Windows)에서 hook 실행(`data\…` 읽기 명령 차단 메시지 표시, 일반 명령 통과)
- [ ] 백신(Windows Defender) 오탐 여부

### 11.7 `.mcpb` 폐기 (2026-11-02)
- 실기 결과: 사용자 PC(Windows, Stata/SE 17)에서 `.mcpb` 파일이 열리지 않음 [1차 확인: 사용자 실기 보고]
- 연쇄 영향: 설치 도우미는 Claude 앱 연결을 `.mcpb`에 맡기고 앱 설정 파일을 쓰지 않았음 → 설치 도우미 실행 뒤에도 Claude 앱에 Stata 도구가 연결되지 않음 [1차 확인: `setup_wizard.py` 코드, 사용자 PC 점검 결과 Stata MCP 등록 흔적 없음]
- 관련 외부 보고: Windows 스토어판(MSIX) Claude 앱 1.12603.x에서 `.mcpb` 설치 창이 아무 표시 없이 닫히고 "Install Unpacked Extension"만 동작한다는 미해결 보고 [2차 확인: 사용자 보고 2건, 개발사 답변 없음]. 사용자 PC 앱 버전과의 일치 여부 [미확인]
- 결정(사용자): `.mcpb`를 아예 삭제
  - 빌드: `packaging/build.py`의 manifest 생성·묶음 생성·`--exe`·`--manifest-only` 제거, `Product`는 실행파일 빌드에 쓰는 항목만 유지
  - 점검·CI: `smoke_test.py --mcpb`, `package-windows`의 Node 설치·`mcpb unpack/validate` 단계, 산출물 `dist/*.mcpb` 제거
  - 설명서·배포: 다운로드 카드·확인값·FAQ의 확장 항목, `latest.json`의 `mcpb` 항목 제거. 방법 A 순서는 "설치 도우미 실행 → Claude 앱 완전히 종료 후 다시 실행"
  - 테스트: manifest 검사 대신 빌드 제품 구성과 배포 경로에 `.mcpb`가 남지 않는지 검사
- 대체: 설치 도우미가 Claude 앱 설정 파일에 직접 등록(별도 변경, 스토어판 설정 파일 위치 차이 대응 포함)
- 참고자료
  - oviedomarco1. (2026, June 12). *Installing .mcpb* (Issue #281) [GitHub issue]. modelcontextprotocol/mcpb. https://github.com/modelcontextprotocol/mcpb/issues/281

## 12. Stata 17 호환 점검 (2026-10-31)

| 항목 | 결과 | 근거·지위 |
|---|---|---|
| 상류 COM 계층(stata-gui-mcp 1.1.0) | 17/18/19, MP·SE·BE 지원 명시 | 패키지 설명 [1차 확인] |
| 에디션 이름 | 17부터 IC → BE. 실행파일명에 표기 없을 때 17 이상은 BE로 표시(`StataInstall.edition`) | Stata 매뉴얼 [U] 5 [2차 확인] |
| BE 실행파일명 | `StataBE-64.exe`·`Stata-64.exe` 모두 탐지 정규식 허용 | 실제 파일명 [미확인] |
| `about` 해석 | `Stata/MP 17.0` 공개 로그 + `Stata/BE 17.0` 합성 사례 테스트 | 공개 로그 [2차 확인], BE 사례는 합성 |
| do-file `version` 선언 | 탐지 주 버전으로 선언, 버전 미상 시 `version 17` | 코드 |
| 표 내보내기 `etable`·`collect` | 17에서 도입 → 사용 가능 | Stata 17 기능 소개 [2차 확인] |
| `etable … export("경로")` | 17·18 초기판에서 따옴표 안 경로의 공백·쉼표 오해석 보고 → 상대경로(`output/tables/파일명`, 공백·쉼표 금지)만 쓰도록 테스트로 고정 | Statalist [2차 확인], 실기 [미확인] |
| 서버 내부 코드(스키마·식별자 점검·결과 조회·자가 점검) | `egen tag`·`unab`·`display %24.0g`·`putdocx`(15+) 등 17 이전부터 있는 명령만 사용 | 코드 검토 [논리적 추론] |
| 스킬 문서 명령 | 18 이상 전용 명령(`dtable` 등) 없음, `xtserial`은 SSC 표기 | 문서 전수 추출 |
| T4 기준값(auto.dta) | 18·19.5에서 일치 확인, 17은 같은 자료라 같을 것으로 봄 | [논리적 추론], 실기 [미확인] |
| 17 미만 | `supported=False` → doctor·설치 도우미 경고, 자가 점검 T1 실패 처리 | 테스트 `tests/test_stata17.py` |

남은 실기 항목: Stata 17(BE·SE·MP 중 1개 이상)에서 doctor·selftest T1~T10, `etable` 내보내기, COM 등록(`/Register`)

## 13. SPSS 배포·SPSS 22 호환 (2026-10-31)

### 13.1 결정
- 요청: Stata판(§11)과 같은 배포 구성을 SPSS에도 적용 + SPSS 22까지 대응
- 결론: 실행파일·설치 도우미·Claude Code 설치 명령·실행 전 검사를 Stata판과 같은 구조로 제공(`.mcpb`도 제공했으나 2026-11-02 폐기, §11.7)(공용 코드 `stata_agent.resources.AppPaths`·`hookguard`·`setup_wizard` 보조 함수)
- 22 대응의 핵심 변수: SPSS 버전별 동봉 Python → 엔진 스크립트를 Python 2.7·3.4·3.x 겸용으로 작성

### 13.2 버전별 동봉 Python과 엔진 선택
| SPSS | 동봉 Python | 엔진이 쓰는 Python | 지위 |
|---|---|---|---|
| 22·23 | 2.7 | `<설치폴더>\Python\python.exe` | 버전 [2차 확인], 폴더 이름 [미확인] |
| 24~26 | 2.7 + 3.4 | `Python3`(3.4) 우선, 없으면 `Python`(2.7) | 버전 [2차 확인], 3.x 폴더 `Python3` [2차 확인: 제3자 구현] |
| 27~ | 3.x만(최신 문서 3.10) | `Python3` | [2차 확인] |
| 공통 | — | `SPSS_AGENT_PYTHON`(확장 설정 "SPSS 동봉 Python")으로 직접 지정 가능 | — |

### 13.3 구현 대응
| 구성 | 파일 | 상태 |
|---|---|---|
| 엔진 스크립트 2.7·3.4 겸용 | `engine_script.py` | 인코딩 선언, readline 반복, 바이트·유니코드 정리(`_text`), ASCII JSON 바이트 기록, 실행 Python 계열의 spss 모듈 폴더만 추가 |
| 금지 문법 정적 검사 | `tests/test_spss_legacy.py` | f-문자열·형 주석·키워드 전용 인자·`open(encoding=)`·`exist_ok` 등 검사(엔진·가짜 spss·점검 스크립트) |
| 구버전 Python 실제 실행 | `tests/legacy/run_engine_check.py`, CI `spss-legacy-python` | 이 환경 3.8·3.10·3.13 통과 [1차 확인]. 2.7·3.4는 CI Docker 이미지(python:2.7-slim·3.4-slim)에서 실행 — 이 환경에서는 외부 실행파일 실행이 보안 정책으로 막혀 CI 결과로 확인 |
| 탐지 | `discovery.py` | Python 폴더 후보(Python3→Python→Python27), 레지스트리 키 4종(`IBM\SPSS Statistics`·`IBM\SPSS\Statistics`·각 WOW6432Node), 값 `InstallationDirectory`·`InstallDir`, 지원 하한 22(`supported`) |
| 출력 인코딩 | `backend.read_output` | UTF-8 실패 시 시스템 인코딩(코드페이지 모드 대비) [논리적 추론] |
| 표 내보내기 | `service.export` | `.doc`·`.xls` 추가, 27 이하에서 `.docx` 요청은 `.doc`로 저장·안내, 28은 안내만 |
| 자가 점검·doctor | `selftest.py`, `cli.py` | 22 미만 T1 실패, 동봉 Python 계열 표시, `doctor --json` |
| 실행파일·확장 | `packaging/build.py`(제품 `spss`), `packaging/entry_spss.py` | `spss-agent-<버전>.exe`(함께 만들던 `.mcpb`는 2026-11-02 폐기, §11.7). 이 환경 시험 빌드에서 점검 11항목 통과(실행파일 → 엔진 → 가짜 spss 왕복 포함) [1차 확인] |
| 설치 도우미 | `spss_agent/setup_wizard.py` | 4단계(실행파일·SPSS 확인·분석 폴더·앱 연결), 화면 연동 단계 없음 |
| Claude Code 설치 명령 | `plugins/spss-agent/commands/setup.md` | `latest.json`의 `spss` 항목 사용, 인자는 테스트가 파서로 검사 |
| 실행 전 검사 | `hookguard.py`(공용) | SPSS 직접 실행(`stats.exe`·`runsyntx`·`import spss`·`IBM\SPSS` 경로) 차단 추가 |
| 스킬 | `plugins/spss-agent/skills/spss-analysis/` | 버전 조건: 효과크기 `/ES`는 27 이상(22~26은 `GLM /PRINT=ETASQ` 등), 내보내기 형식 |
| 설명서 | `site/spss.html` | Stata 페이지와 같은 구성(방법 비교·A·B·Codex 탭), SPSS 22 이상·동봉 Python 안내 |

### 13.4 문법 호환 점검(22 기준)
| 항목 | 결과 | 지위 |
|---|---|---|
| 서버 내부 문법(OMS·DATA LIST·DESCRIPTIVES·CORRELATIONS·SAVE·GET FILE·DATASET NAME·CD) | 22 이전부터 있는 명령 | [논리적 추론: 일반 지식] |
| 스킬 문법(FREQUENCIES·EXAMINE·T-TEST·ONEWAY·NPAR TESTS·CORRELATIONS·REGRESSION·LOGISTIC REGRESSION·PLUM·GENLIN·MIXED) | 22에 있음 | [논리적 추론] |
| 효과크기 `T-TEST /ES`·`ONEWAY /ES` | 27부터 → 스킬에 조건 명시 | [2차 확인] |
| OMS 내보내기 | XLSX 21+, DOC는 28.0.1 전 .doc → 코드 반영 | [2차 확인] |
| Python 3 처리기 | 24~26에서 유니코드 모드 필요 | [2차 확인: IBM 24 문서 검색 요약] — 코드페이지 모드에서 3.4 엔진 동작 [미확인] |

### 13.5 실기 검증 체크리스트(Windows + SPSS)
- [ ] SPSS 22(또는 23): 동봉 Python 폴더 이름(`Python`)·`python.exe` 위치, 엔진 기동(2.7), 한글 경로·한글 변수 라벨
- [ ] SPSS 24~26: `Python3`(3.4) 엔진 기동, 코드페이지 모드에서의 동작
- [ ] SPSS 27 이상: 기존 §10.6 항목
- [ ] 32비트판(22 등) 탐지(`Program Files (x86)`, WOW6432Node)
- [ ] `.doc` 내보내기(27 이하)·`.xlsx`(22)
- [ ] `spss-agent-<버전>.exe` 더블클릭·`/spss-agent:setup` 전 과정(`.mcpb` 설치 화면 항목은 폐기, §11.7)

## 14. 기존 파일 이어 작업·연구자 조작 감지 (2026-11-01)

### 14.1 배경·결정
- 지적: 연구자가 쓰던 do-file을 넘겨받는 흐름이 막힘. 재현 확인 결과 [1차 확인]
  - cp949(예전 Stata·다른 편집기) 파일은 실행·수정 즉시 실패(UnicodeDecodeError)
  - 섹션 표지가 없으면 원래 내용이 머리말로 취급되어 섹션 실행에서 빠짐
  - `list`·`browse` 포함 시 전체 실행 차단
- 정정 기록: 앞서 "파일 이름 규약이 아니면 작성·수정 도구가 거부"라고 답했으나, 실제로는 **새 파일 작성 도구만** 규약을 적용하고 수정·실행 도구는 이름과 무관하게 받음(작성 도구 코드만 보고 수정 경로를 확인하지 않은 것이 원인)
- 원인: 설계·테스트가 "AI가 처음부터 만드는 프로젝트"만 가정
- 사용자 결정: 원본은 같은 파일을 고치고 백업, 원래 내용은 주석 제목 기준 자동 분할
- 추가 요구: 창 연동 중 사람이 Stata 창에서 작업(clear·rename·recode·do-file 직접 수정)한 경우 경고 수준으로 알리고 이어받기

### 14.2 구현 대응
| 구성 | 파일 | 내용 |
|---|---|---|
| 인코딩 | `stata_agent/importer.py`(`decode_text`), 두 서비스 `_read_dofile`·`_read_syntax` | UTF-8(BOM) → cp949 → 시스템 인코딩 순 판별. 비UTF-8 파일을 실행·수정하려 하면 기술 오류 대신 가져오기 도구 안내 |
| Stata 가져오기 | `stata_import_dofile` | 제목 탐지는 가장 강한 형식 하나만 사용(책갈피 `**#` > 장식·상자형 주석 > 번호 제목). 블록 주석·중괄호·program·mata·python·`#delimit ;`·`///` 안에서는 나누지 않음. `list`·`browse`·`edit` 줄은 주석 처리(중괄호가 같은 줄·`#delimit ;`·이어 쓰기 둘째 줄은 수동 수정 목록). 그 밖 차단·승인·프로젝트 밖 경로는 보고만. 원본 백업, 00_master.do 맨 앞 등록, `preview` 지원 |
| SPSS 가져오기 | `spss_import_syntax`, `spss_agent/importer.py` | 명령 경계(split_commands) 기준 한 줄 주석 명령만 제목 후보. DO IF·LOOP·DO REPEAT·INPUT PROGRAM·MATRIX·FILE TYPE·DEFINE 안에서는 나누지 않음. 행 출력 명령은 첫 줄에 `*`를 붙여 명령 전체를 주석화(마침표로 끝나지 않는 명령은 수동 수정). 결과는 UTF-8 BOM(.sps 규약) |
| 00_master 인식 | `dofile.master_entries`·`syntaxfile.master_entries` | 규약 밖 이름(따옴표) 인식, 번호 순서 비교는 규약 이름끼리만 |
| SPSS 백업 폴더 | `backup_file(agent_dir)` | 기존 결함 수정: SPSS 백업이 `.stata-agent/backups`로 가던 것을 `.spss-agent/backups`로 |
| SPSS 규약 밖 이름 실행 | `result_relpath` | `NN_` 없는 이름은 `output/logs/<이름>_result.txt` |
| 자료 상태 지문 | `stata_agent/sync.py` | 관측치 수·변수 수·자료 파일·변수별 이름/유형/값 라벨·`datasignature`(변수 300개 이하는 변수별, 초과는 전체). r()는 `_return hold/restore`로 보존. AI 실행 직후 기록 → 다음 실행 직전 비교 → 결과 첫머리에 경고. 이름 변경은 위치·유형이 같고 값 확인값이 같을 때만 "이름 변경 추정"(drop 후 새로 만든 경우와 구분) |
| 창에서 친 명령 | 세션 시작 시 `cmdlog using .stata-agent/cmdlog.txt, append` | AI 실행·내부 실행 직후마다 읽은 위치를 끝으로 옮겨, 그 사이 쌓인 줄만 "연구자 입력 추정"으로 보고 |
| do-file 직접 수정 | `FileWatch`(Stata·SPSS) | AI가 마지막으로 쓰거나 읽은 내용과 디스크가 다르면 섹션 단위(변경·추가·삭제·머리말)로 알리고 디스크 기준으로 이어 감 |
| 점검 도구 | `stata_check_changes`(읽기 전용) | 위 세 가지를 한 번에 보고하고 기준 갱신. 남길 명령은 동의 후 '연구자 수동 작업' 섹션으로 기록하도록 안내 |
| 설정 | `STATA_AGENT_DRIFT_CHECK`(full·structure·off), `STATA_AGENT_DRIFT_MAX_CELLS`(기본 5천만 칸) | 큰 자료는 값 확인값 생략 |
| 기록 | `session_log` | 인코딩 이름·섹션 수·주석 처리 수·감지 건수만(코드·값 없음) |

### 14.3 지위·한계
- [1차 확인] 가짜 백엔드·가짜 spss로 cp949 가져오기 → 실행·섹션 실행·섹션 추가, 이름 변경·리코드·삭제·추가·clear·다른 자료 감지, cmdlog 줄 보고, do-file 수정 감지까지 자동 테스트
- [미확인: 실기] `datasignature`(변수 지정·strL 처리), `_return hold/restore`, `cmdlog`가 자동화(COM)로 보낸 명령을 기록하는지, Do-file Editor '선택 실행'이 cmdlog에 남는 형태, 대용량 자료에서 점검 시간
- [논리적 추론] AI 실행 중에 사람이 동시에 친 명령은 AI 실행분과 구분되지 않아 보고에서 빠질 수 있음 → 안내 문구로 "AI 실행 중에는 기다릴 것"
- 연구자가 창에서 한 일의 **출력**은 AI에 전달하지 않음(명령 문자열만)

### 14.4 실기 검증 체크리스트
- [ ] Stata 13 이하에서 저장한 한글 do-file 가져오기 → Stata 17+에서 주석·라벨 정상 표시
- [ ] 책갈피·장식·번호 제목이 섞인 실제 연구 do-file 분할 결과 확인
- [ ] 창에서 `rename`·`recode`·`replace`·`clear`·다른 자료 `use` 후 AI 실행 → 경고 내용 확인
- [ ] cmdlog 기록 내용(연구자 입력 vs AI 실행 구분), Do-file Editor 선택 실행
- [ ] 변수 수 많은 자료(예: 2,000개)·큰 자료(예: 100만 관측치)에서 점검 시간

## 15. 그래프 보기 (2026-11-01)

### 15.1 배경·결정
- 설계서에는 그래프 항목이 없음 [1차 확인: 설계서 본문 검색] → 그림은 파일로만 남고 AI가 확인할 수 없었음
- 사용자 결정: "그래프는 AI가 볼 수 있어야 함"
- 쟁점: 그림은 텍스트 출력 필터(`filter_output`)를 거칠 수 없는 새 전송 경로임. 산점도는 관측치마다 (x, y) 값을 담고, `mlabel()`은 점마다 변수 값을 글자로 찍음(식별자면 `list`와 같음)
- 처리 원칙: 그림을 만든 명령으로 등급을 정해 집계 그림은 바로, 개별 값이 담기는 그림은 연구자 동의 후 반환

### 15.2 구현 대응
| 구성 | 파일 | 내용 |
|---|---|---|
| 등급 판정 | `graphs.py` | 집계·분포(histogram·kdensity·graph bar/box/dot/pie·marginsplot·coefplot·binscatter·적합선만 있는 twoway·`collapse`·`contract` 뒤 그림) / 관측치별 점·선(scatter·line·connected·graph matrix·잔차 그림·`(asis)`·알 수 없는 twoway 종류) / 값 글자 표시(`mlabel()`·`(asis)`+`over()`) / 출처 미확인(`graph use`·`combine`·매크로·이 세션과 프로젝트 do-file에 근거 명령 없음) |
| 출처 추적 | `GraphScan`, `find_in_project` | AI 실행 코드의 그림 이름(`name()`)·현재 그림·내보낸 파일 기록. 연구자가 창에서 그린 그림은 cmdlog(§14)로 판정. 파일은 이번 세션 기록 → 프로젝트 do-file 검색(`data/` 제외) 순으로 찾고, 같은 이름이 여럿이면 가장 엄격한 등급 |
| 집단 변수 점검 | `service.view_graph` | 집계 그림이라도 `over()`·`by()` 변수가 식별자 성격(고유값 비율 기준, G14와 같음)이면 승인으로 올림 |
| 보기 도구 | `stata_view_graph` | 파일(PNG·JPG·GIF, 프로젝트 안, `data/` 제외) 또는 현재·이름 지정 그래프 창을 `.stata-agent/graphs/`에 PNG(폭 1400px)로 내보내 반환. `.gph`·SVG·PDF 등은 PNG로 다시 내보내도록 안내. 3.5MB 초과는 거부(크기 줄여 다시 저장 안내) |
| 이미지 전달 | `server.to_content` | MCP `ImageContent`(base64, `image/png` 등)를 텍스트와 함께 반환 |
| 실행 결과 안내 | `_graph_note` | 섹션·파일 실행 뒤 "그래프: output/figures/a.png(집계·분포 그래프) → stata_view_graph로 확인 가능" 한 줄 |
| 저장 경로 검사 | G16 | `graph export`·`graph save`·`saving()`이 프로젝트 밖·`data/`면 차단, 매크로 경로는 경고(그림은 자료가 아니므로 승인까지 요구하지 않음). 기존에는 그래프 저장 경로를 검사하지 않던 빈틈 [1차 확인: 코드] |
| 규약 | `project.py`, 스킬 | `output/figures/` 폴더, 원칙 P8(그림에서 읽은 수치는 해석에 쓰지 않음, 개별 값 그림은 동의 후) |
| 기록 | `session_log` | 등급(`graph_kind`)·승인 여부만(그림 내용 없음) |
| 권한 | `tool_specs` | 읽기 전용이 아닌 도구(클라이언트 승인 대상)로 분류 → 그림이 PC 밖으로 나가는 경로이므로 보수적으로 둠 |

### 15.3 확인한 사실과 지위
- Claude Code는 MCP 도구가 돌려준 PNG·JPEG·GIF·WebP 그림을 모델에 그대로 보여 줌. 그 밖 형식(SVG 등)은 파일로 저장하고 경로만 전달 [1차 확인: Claude Code 공식 문서·변경 기록, 하위 조사 열람]
- 그림 데이터도 `MAX_MCP_OUTPUT_TOKENS`(기본 25,000) 적용 대상이나 계산 방식은 문서에 없음 [1차 확인: 적용 대상 / 미확인: 계산 방식] → 기본 폭 1400px로 내보내 크기를 줄임
- Claude API 그림 한도: 형식 jpeg·png·gif·webp, 한 장 base64 10MB(Amazon Bedrock 5MB), 긴 변이 기준(표준 1,568px)을 넘으면 축소 [1차 확인: Claude API Vision 문서, 하위 조사 열람] → 3.5MB(base64 약 4.7MB) 상한은 두 한도 안쪽
- Claude 앱(Desktop)이 MCP 그림을 모델에 전달하는지: 공식 근거 없음, 사용자 보고가 엇갈림(보이는 경우·빈 그림으로 들어온다는 경우) [미확인] → 그래프 창 내보내기 결과에 저장 경로를 함께 적어, 그림이 안 보이면 연구자가 파일을 열도록 안내
- Codex: MCP 그림을 모델에 전달하는 변경이 상류에 병합됨(2025-10-27) [2차 확인: GitHub PR], 반영된 배포판 [미확인]
- Stata `graph export ..., name()`(창 이름 지정)·`width()` 옵션 동작, 배치 모드 PNG 내보내기 [미확인: 실기]
- 등급 판정은 명령 문자열 기준 정적 추정 [논리적 추론]. 관측치 1개짜리 집단의 막대, 아주 작은 표본의 분포 그림처럼 자료 내용에 따라 개별 값이 드러나는 경우는 걸러내지 못함 [한계]

### 15.4 실기 검증 체크리스트
- [ ] Claude Code: `stata_view_graph` 그림이 모델에 보이는지, 1400px PNG가 출력 한도 경고 없이 전달되는지
- [ ] Claude 앱(Desktop): 같은 그림이 모델에 보이는지(보이지 않으면 저장 경로 안내만 남는지)
- [ ] 그래프 창 내보내기: `name()` 지정·현재 그림, 여러 그래프 창, 창을 닫은 뒤 오류 문구
- [ ] 배치 모드(`/e`)에서 `graph export` PNG 생성
- [ ] 등급 판정: 실제 연구 do-file의 그래프 명령(twoway 복합·`by()`·사용자 명령) 표본 대조

## 16. pystata 보조 백엔드 (2026-11-01)

### 16.1 배경·결정
- 사용자 결정: "pystata 방식을 추가하되 일단 주력은 아님" → `STATA_AGENT_BACKEND=pystata`로 지정할 때만 사용, `auto`에서는 고르지 않음
- 장점: StataCorp 공식 인터페이스, 호출 간 자료·추정결과 유지(배치와 다름), Windows·macOS·Linux 공통, COM 등록(관리자 권한) 불필요
- 단점: Stata 화면 없음(연구자가 같은 세션을 볼 수 없음, Do-file Editor 연동 없음), 연구자 PC에 별도 Python 필요, 실행 중 중단은 작업자 종료(세션 소실)뿐

### 16.2 구현 대응
| 구성 | 파일 | 내용 |
|---|---|---|
| 작업자 | `backends/pystata_proc.py`(`WORKER_SCRIPT`) | 연구자 PC의 Python으로 자식 프로세스 실행 → `<Stata>/utilities`를 경로에 넣고 `pystata.config.init(에디션, splash=False)`(stata_setup이 하는 일을 직접 수행, 별도 설치 불필요) |
| 통신 | `backends/worker.py`(`JsonWorker`) | SPSS 엔진과 같은 방식(요청 JSON·응답 파일·완료 표지)을 공용 모듈로 분리, SPSS 엔진도 이 모듈 사용(동작 변화 없음, 기존 테스트 통과) |
| 출력 분리 | 작업자 | 완료 표지용 통로를 따로 두고 표준출력(파일 기술자 1번 포함)은 버림 → Stata 출력은 `log using`으로 남긴 로그 파일로만 읽음 → AI 반환은 다른 백엔드와 같이 출력 필터 통과 |
| 실행 | `run_code`·`run_dofile` | 코드는 `.stata-agent/pystata/`의 임시 do-file로 `do` 실행(실행 후 삭제), 실행마다 프로젝트 폴더로 `cd`, 오류는 로그의 `r(#);`와 `SystemError`로 판정 |
| Python 탐지 | `find_python` | `STATA_AGENT_PYTHON` → (실행파일 묶음이 아닐 때) 서버 Python → `py -3` → `python3`·`python`(Windows Store 대리 실행파일 제외) |
| Stata 폴더 | `stata_home_for` | 실행파일 위쪽 폴더 중 `utilities/pystata`가 있는 곳. 17 미만 폴더 이름이면 사용 불가 |
| 연구자 조작 감지 | `Backend.human_window` | 화면이 없어 사람이 조작할 수 없으므로 생략(com_gui만 대상) |
| 그래프 | `stata_view_graph` | 메모리 그래프 내보내기 사용 가능(세션 유지) |
| 점검 | `stata-agent doctor` | "pystata(보조): 사용 가능/불가 — 사유" 한 줄(Stata는 띄우지 않음) |
| 구버전 Python | `tests/test_spss_legacy.py`, `tests/legacy/run_pystata_check.py`, CI `spss-legacy-python` | 작업자·가짜 pystata를 Python 2.7·3.4 문법으로 유지하고 실제 실행 |

### 16.3 확인한 사실과 지위
- `stata_setup.config(path, edition, splash=True)`: `<path>/utilities`가 없으면 `OSError`, 있으면 sys.path에 넣고 `pystata.config.init(edition, splash=splash)` 호출, 에디션 mp·se·be [1차 확인: stata_setup 0.1.3 소스 직접 열람]
- `stata.run(cmd, quietly, echo, inline)`: 17과 18의 `echo` 기본값이 다름, 여러 줄은 임시 do-file로 한 번에 실행, 실패 시 `SystemError` [2차 확인: stata.com pystata17·18 문서 검색 요약 — 이 작업 환경에서 www.stata.com 접속 차단] → 작업자는 `echo`를 넘기지 않음
- `run()`만 쓰면 NumPy·pandas 불필요, Stata 17 문서 기준 Python 2.7 또는 3.4 이상 [2차 확인: 같은 문서 검색 요약]
- `config.set_graph_show`·`set_output_file` 존재, 스트리밍 출력 함수 이름은 `set_streaming_output`(StataNow 전용) [2차 확인] → 작업자는 `set_graph_show(False)`만 시도(실패해도 진행)
- Stata 출력이 Python `sys.stdout`으로 나가는지 C 수준에서 쓰는지 [미확인] → 두 경로 모두 버리도록 구현
- 일반 스크립트에서 `graph export`, macOS의 `utilities` 위치(`/Applications/Stata/utilities` 추정), 자식 프로세스·라이선스 좌석 제약 [미확인: 실기]

### 16.4 실기 검증 체크리스트
- [ ] Windows Stata 17·18: `STATA_AGENT_BACKEND=pystata`로 세션 열기·섹션 실행·오류 r() 판정·호출 간 자료 유지
- [ ] 작업자 표준출력에 Stata 출력이 섞이지 않는지(완료 표지 통신 유지)
- [ ] `graph export` PNG 생성, `stata_view_graph()` 메모리 그래프
- [ ] macOS: `utilities/pystata` 위치, 에디션 판정
- [ ] COM 창 세션과 pystata 세션을 동시에 열 때 라이선스 동작

### 16.5 참고자료(§15·§16)
1. Anthropic. (n.d.). *Connect Claude Code to tools via MCP* [Images in tool results 절]. Claude Code Docs. https://code.claude.com/docs/en/mcp (하위 조사 열람)
2. Anthropic. (2026). *Claude Code changelog* [2.1.144·2.1.283 항목]. GitHub. https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md (하위 조사 열람)
3. Anthropic. (n.d.). *Vision*. Claude API Docs. https://platform.claude.com/docs/en/build-with-claude/vision (하위 조사 열람)
4. Anthropic. (2026). *Issue #238: MCP tool result images* [GitHub issue]. https://github.com/anthropics/claude-ai-mcp/issues/238 (하위 조사 열람, 사용자 보고)
5. OpenAI. (2025). *Pull request #5600: Render MCP tool call result images to the model* [GitHub pull request]. https://github.com/openai/codex/pull/5600 (하위 조사 열람)
6. StataCorp. (2022). *stata_setup* (Version 0.1.3) [Software]. PyPI. https://pypi.org/project/stata_setup/ (소스 직접 열람)
7. StataCorp. (n.d.). *pystata.config* (Stata 18). https://www.stata.com/python/pystata18/config.html (검색 결과 요약으로 확인, 원문 미열람)
8. StataCorp. (n.d.). *pystata.stata* (Stata 17). https://www.stata.com/python/pystata17/stata.html (검색 결과 요약으로 확인, 원문 미열람)
9. StataCorp. (n.d.). *Installation* (pystata, Stata 17). https://www.stata.com/python/pystata17/install.html (검색 결과 요약으로 확인, 원문 미열람)

## 17. Claude 앱 직접 등록·Desktop Commander 대응 (2026-11-02)

### 17.1 실기 결과·결정
- 실기(사용자 PC: Windows, Stata/SE 17.0 `C:\Stata17`): 설치 도우미 실행 뒤 Claude 앱 채팅에 "Stata 연결 점검해줘" → Stata 도구가 아니라 Claude가 **Desktop Commander로 Stata를 직접 배치 실행**하고 로그를 읽어 보고함 [1차 확인: 사용자 실기 보고]
  - Claude 앱에 Stata MCP 등록 없음, 일반 위치 `%APPDATA%\Claude\claude_desktop_config.json` 없음 [1차 확인: 사용자 PC의 Claude 점검]
  - 원인: 설치 도우미가 Claude 앱 연결을 `.mcpb`에 맡기고 앱 설정 파일을 쓰지 않음 [1차 확인: 코드] + `.mcpb`가 열리지 않음(§11.7)
- **정정**: §11.4와 설명서의 "채팅 앱은 PC 명령을 직접 실행할 수 없어 더 엄격"은 틀림
  - 건너뛴 확인: Claude 앱도 PC 명령·파일 도구(Desktop Commander 등)를 붙일 수 있다는 점을 확인하지 않고 [논리적 추론]으로 단정함
  - 같은 유형 점검: 설명서 비교표의 "이럴 때 A(민감자료)" 권고도 같은 전제 → 함께 수정
- 사용자 결정: (1) 설치 도우미가 Claude 앱 설정을 직접 등록, 연구자에게 PowerShell 등 진단을 요구하지 않음("쉽게 사용하게 하는 것") (2) Desktop Commander는 안내 + 차단 설정 자동 추가

### 17.2 구현 대응
| 구성 | 파일 | 내용 |
|---|---|---|
| 앱 위치 감지 | `client_config.claude_desktop_config_paths` | Microsoft Store판 `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\`(패키지 폴더가 있으면 설정 폴더가 없어도 대상) + 일반 설치 `%APPDATA%\Claude\`(폴더가 있을 때만). 감지된 곳 모두에 기록 |
| 설정 기록 | `merge_desktop_config` | 기존 서버·설정 유지 병합, 읽기는 BOM 허용, 쓰기는 BOM 없는 UTF-8을 같은 폴더 임시 파일 → 교체 |
| 백업 | `client_config.backup` | 같은 초에 두 번 고쳐도 첫 사본이 덮이지 않도록 번호 추가(아래 17.4 사고에서 발견한 결함) |
| 설치 도우미 | Stata `[5/6]`·SPSS `[4/5]` | Claude 앱을 자동 감지해 연결 대상에 포함, 결과를 "Claude 앱(Microsoft Store판): 등록 완료 / 설정 파일 / 이전 설정 백업"처럼 표시. 끝 화면에 "Claude 완전 종료(알림 영역 아이콘 포함) → 다시 실행 → 'Stata 연결 점검해줘'" |
| Desktop Commander | `dc_guard.py`, 설치 도우미 `[6/6]`·`[5/5]` | `~/.claude-server-commander/config.json`이 있을 때만 `blockedCommands`에 Stata·SPSS 실행파일 이름(소문자, .exe 있음·없음) 추가. 기존 항목·다른 설정 유지, 잠금(`config.json.lock`)이 30초 이내면 대기 후 포기, 백업 후 원자적 쓰기. 파일 읽기는 막지 못하므로 "분석 대화에서는 끌 것" 안내 |
| 서버 지침 | 두 `server.py`의 `instructions` | "분석은 이 서버 도구로만, 셸·파일 도구로 실행파일 실행·data 열람 금지, 연결 점검은 status·selftest" |
| 스킬·지침 | 두 SKILL.md, 두 `project.py` P2 | 같은 금지 규칙 추가, 템플릿 재생성 |
| 설명서 | `site/index.html`·`spss.html` | 비교표 원자료 보호 행 정정, FAQ "Desktop Commander가 켜져 있어요", "도구가 보이지 않아요" 절차 갱신 |
| 테스트 격리 | `tests/conftest.py` | 모든 테스트에서 APPDATA·LOCALAPPDATA·Desktop Commander 설정 위치를 임시 폴더로 바꿈 |

### 17.3 확인한 사실과 지위
- 스토어판(MSIX) Claude 앱은 설정을 `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`에서 읽고, 앱의 '설정 편집' 버튼은 `%APPDATA%\Claude\…`를 엶 → 일반 위치에 쓴 서버가 조용히 무시된다는 미해결 보고 [2차 확인: GitHub 보고, 개발사 답변 없음]. 패키지 이름 뒤 식별자는 설치마다 같은지 [미확인] → `Claude_*`로 찾음
- 사용자 PC 앱의 설치 형태(스토어판 여부) [미확인 — 다음 실기에서 설치 도우미 화면으로 확인]
- Desktop Commander 설정 파일 `~/.claude-server-commander/config.json`, 차단 규칙은 명령을 구분자 단위로 나눠 첫 낱말의 파일 이름을 소문자로 바꾼 뒤 목록과 정확히 비교 [1차 확인: DesktopCommanderMCP main 소스 `src/config.ts`·`src/command-manager.ts`, 이 환경의 0.3.1 `get_config`]
- 같은 README: 차단은 "우회 가능"하며 "샌드박스가 아님", 허용 폴더 설정은 파일 도구만 제한 [1차 확인] → 실행파일 이름 차단은 사고 방지 수준
- Claude Code는 MCP 서버 `instructions`를 AI 지시에 넣음 [1차 확인: Claude Code 세션의 'MCP Server Instructions' 절]. Claude 앱 반영 여부 [미확인]
- Claude 앱이 실행 중일 때 설정 파일을 다시 쓰면서 외부 변경을 지우는지 [미확인] → 끝 화면에서 완전 종료 후 재실행 안내
- **Claude Code 연결(2026-11-02 추가)**: Claude 앱의 Code 탭(로컬 세션)은 `~/.claude.json`·프로젝트 `.mcp.json`과 함께 `claude_desktop_config.json`의 MCP 서버를 읽음 [1차 확인: Claude Code 공식 문서 desktop.md "Shared configuration", 하위 조사 열람] → 설치 도우미의 Claude 앱 등록만으로 Code 탭에서도 Stata 도구 사용 가능. 터미널 `claude` 명령(CLI)은 `claude_desktop_config.json`을 읽지 않음 [1차 확인: 같은 문서] → CLI는 `claude mcp add --scope user`로 따로 등록
- Windows 기본 설치 프로그램은 `claude.exe`를 `%USERPROFILE%\.local\bin`에 두고 PATH를 바꾸지 않음 [1차 확인: 공식 문서 troubleshoot-install.md] → 설치 도우미가 이 위치도 찾음(§18). Code 탭은 앱이 내려받은 자체 Claude Code를 씀 [1차 확인: desktop.md] → `claude` 명령이 없어도 됨
- `~/.claude.json` 직접 편집은 문서화된 절차가 아니고 Claude Code도 이 파일을 씀 [1차 확인: 문서 "직접 편집할 필요 없음"] → 직접 편집하지 않음
- 같은 이름(stata)이 `~/.claude.json`(CLI 등록)과 `claude_desktop_config.json`에 함께 있을 때 Code 탭 처리 방식 [미확인] → 두 항목 모두 같은 실행파일을 가리키게 기록

### 17.4 개발 중 사고 기록
- 설치 도우미 테스트(`yes=True`, 실제 기록)가 개발 환경(클라우드 컨테이너)의 실제 Desktop Commander 설정에 차단 항목을 추가함 [1차 확인]
- 같은 초에 두 번 기록되어 백업 사본이 덮여 원본 사본이 남지 않음 → 추가된 항목(이 도구가 넣는 이름 목록과 정확히 일치)만 제거해 원래 33개 항목으로 복구, `get_config`로 복구 확인 [1차 확인]
- 재발 방지: 테스트 격리 fixture(17.2), 백업 이름 충돌 수정

### 17.5 실기 검증 체크리스트
- [ ] 새 설치 도우미 실행 → `[5/6]`에 "Claude 앱(…): 등록 완료"와 설정 파일 경로 표시
- [ ] Claude 앱 완전 종료·재실행 → "Stata 연결 점검해줘"에 Stata 도구(`stata_status`·`stata_selftest`)로 응답하는지
- [ ] `[6/6]` Desktop Commander 차단 추가 → Claude에게 Stata 직접 실행을 요청했을 때 Desktop Commander가 거부하는지
- [ ] 스토어판·일반판 각각에서 등록이 반영되는지(가능한 범위)

### 17.6 참고자료
1. 0xc4b4l. (2026, February 16). *[BUG] Windows MSIX: "Edit Config" opens wrong claude_desktop_config.json — MCP servers silently fail to load* (Issue #26073) [GitHub issue]. anthropics/claude-code. https://github.com/anthropics/claude-code/issues/26073
2. wonderwhy-er. (2026). *DesktopCommanderMCP* [Software, src/config.ts·src/command-manager.ts·README]. GitHub. https://github.com/wonderwhy-er/DesktopCommanderMCP
3. Anthropic. (n.d.). [Claude Code 데스크톱 안내, 문서 제목 미확인 — Shared configuration 절]. Claude Code Docs. https://code.claude.com/docs/en/desktop (하위 조사 열람)
4. Anthropic. (n.d.). [Claude Code 설치 문제 해결 안내, 문서 제목 미확인 — Verify your PATH 절]. Claude Code Docs. https://code.claude.com/docs/en/troubleshoot-install (하위 조사 열람)

## 18. 재설치 안정성 (2026-11-02)

### 18.1 배경
- 사용자 요구: "다시 받아서 다시 설치하면 작동할 수 있도록"(배포 후 설치 → 실패 → 재설치가 자주 일어남)
- 원칙: 같은 설치 도우미를 몇 번 실행해도 결과가 같고(이미 맞는 설정은 그대로), 앞선 실패가 남긴 상태 위에서도 끝까지 진행

### 18.2 재설치 때 걸리던 지점과 대응
| 지점 | 이전 동작 [1차 확인: 코드] | 대응 |
|---|---|---|
| 실행 중인 이전 버전 교체 | Claude 앱·Claude Code가 `stata-agent.exe`를 실행 중이면 덮어쓰기 실패 → "앱 종료 후 다시 실행"으로 멈춤 | 새 파일을 같은 폴더 임시 파일로 복사 → 교체, 교체가 막히면 실행 중인 파일을 `stata-agent.old-<시각>.exe`로 옮긴 뒤 교체(Windows는 실행 중 파일의 이름 바꾸기를 허용 [논리적 추론: Windows 파일 잠금 동작, 실기 미확인]). 옛 사본은 다음 실행 때 정리. 앱을 다시 시작하면 새 버전 사용 |
| 스킬 재복사 | 매번 스킬 폴더 안에 `stata-analysis.bak-…` 백업 생성 → SKILL.md가 있는 사본이 같은 이름의 스킬로 중복 인식될 수 있음 [논리적 추론] | 내용이 같으면 그대로 둠. 바꿀 때 백업은 스킬 폴더 밖(`~/.claude/skills-backups`, `~/.agents/skills-backups`). 예전 판이 남긴 폴더 안 백업도 밖으로 옮김 |
| 백업 이름 충돌 | 같은 초에 두 번 고치면 첫 백업(원본)이 덮임 | 번호 추가(§17) |
| 다시 받은 파일이 옛 파일 | 파일 이름이 버전(0.1.0)으로 고정 → 브라우저·사이트 캐시의 옛 파일을 받을 수 있음 [논리적 추론] | 버전 0.2.0으로 올림(배포 파일 이름 변경). 변경을 배포할 때마다 버전을 올리는 규칙 유지(AGENTS.md) |
| 설정 파일 | Claude 앱·Claude Code·Codex·Desktop Commander 설정은 병합 방식 | 같은 내용이면 "이미 등록됨", 백업 늘지 않음(테스트 확인). 빈 설정 파일은 새로 쓰고, 깨진 JSON은 손대지 않고 알림 |
| `claude` 명령 위치 | PATH에 없으면 Claude Code 등록 생략 | 알려진 설치 위치(`~/.local/bin`, `%APPDATA%\npm`)도 찾음 [논리적 추론: 설치 방식별 일반 위치] |

### 18.3 검증·한계
- [1차 확인] 자동 테스트: 실행 중 파일 교체 흉내(덮어쓰기 거부 → 옆으로 옮겨 교체 → 다음 실행 때 정리), 교체 불가 시 원래 파일 유지·안내, 설치 2회 연속 실행 시 오류 없음·백업 증가 없음, 빈·깨진 설정 파일
- [미확인: 실기] Windows에서 실행 중인 exe 이름 바꾸기, 백신 프로그램이 임시 파일·교체를 막는 경우
- 깨진 Claude 앱 설정(JSON 오류)은 다른 설정을 잃지 않도록 자동 복구하지 않음 → 화면에 파일 위치와 함께 알림

### 18.4 실기 검증 체크리스트
- [ ] Claude 앱(Stata 도구 연결 상태)을 켠 채로 새 설치 도우미 실행 → "설치 완료(… 앱을 다시 시작하면 새 버전으로 바뀜)" → 앱 재시작 후 새 버전 동작
- [ ] 같은 설치 도우미 2회 연속 실행 → 2회차 모든 항목 "이미 등록됨"·오류 없음
- [ ] 설치 도중 창을 닫은 뒤 다시 실행 → 끝까지 완료

### 18.5 실기 기록(2026-11-02, 0.2.0)
- 사용자가 설치 도우미 0.2.0 실행 뒤 **이전 대화를 이어서** "Stata 연결 점검해줘" 입력 → Claude가 "PC 연결이 끊김"이라고 답함(앱 완전 종료로 그 대화가 쓰던 PC 연결 도구가 해제됨) [1차 확인: 사용자 보고]
- 판단: 새 도구는 대화·세션을 시작할 때 불러오므로 이전 대화에는 나타나지 않음 [논리적 추론] → 시험 방법 문제이며 등록 결과는 아직 판정 전 [미확인]
- 사용자 사용 방식: PC 앞에서 Claude 앱(채팅·Code 탭) 사용 → 현재 등록 대상(Claude 앱 설정, Code 탭 공통)이 맞음
- 대응(0.2.1): 설치 도우미 끝 화면·설명서에 "새 채팅(Code 탭은 새 세션)에서 시험, 이전 대화에는 새 도구가 나타나지 않음" 명시

## 19. 연결 진단 (2026-11-02, 0.2.2)

### 19.1 실기 결과·결정
- 0.2.0 설치 도우미: "Claude 앱(…): 등록 완료" → Claude 앱 완전 종료·재실행 → PC의 Claude 앱 **새 채팅**에 "Stata 연결 점검해줘" → 도구 목록에 Stata 없음 [1차 확인: 사용자 보고·응답]
- 남는 원인 두 갈래 [논리적 추론]: (1) 앱이 기록한 위치의 설정을 읽지 않음 (2) 읽었지만 실행파일 시작 실패
- 이를 가를 근거가 화면에 없었고, 연구자에게 PC 조작(PowerShell 등)을 요구하지 않는다는 원칙(§17.1) → **제품이 스스로 진단**하도록 함

### 19.2 구현 대응
| 구성 | 파일 | 내용 |
|---|---|---|
| 도구 쪽 기록 | `connection_log.record`, 두 `server.py` | 서버 시작·첫 도구 목록 요청 때 설치 폴더 `serve_history.jsonl`에 시각·클라이언트 이름(MCP clientInfo)·버전만 기록(최근 50줄, 자료·코드 없음, 기록 실패는 무시) |
| 앱 쪽 기록 판독 | `connection_log.connection_report` | 감지된 Claude 앱 설정 폴더의 `logs\mcp-server-<이름>.log`·`logs\mcp.log`에서 이 서버의 흔적과 최근 오류 줄(spawn·ENOENT·failed 등) 표시 |
| 설치 도우미 | Stata `[5/6]`·SPSS `[4/5]` 뒤 | "연결 진단(지난번 Claude 앱 실행 기록)": 연결 기록 유무, 앱의 시작 기록·오류 |
| 화면 저장 | `save_transcript` | 설치 화면 전체를 `%LOCALAPPDATA%\StataAgent\setup_last.txt`(SPSS는 SpssAgent)에 저장하고 위치 표시(등록자·일련번호는 원래 화면에 없음) |
| doctor | `stata-agent doctor` | 설정 위치별 Stata 등록 여부 + 위 진단 |

### 19.3 지위
- Claude 앱 로그 파일 이름 규칙 `mcp-server-<이름>.log`·`mcp.log`, 위치 `<설정 폴더>\logs` [2차 확인: MCP 공식 디버깅 안내 — 이 작업 환경에서 modelcontextprotocol.io 접속 불가로 원문 재열람 못 함]. 스토어판에서 로그가 설정 파일과 같은 가상화 폴더에 있는지 [미확인]
- 진단 판독 규칙은 오류 낱말 기준 추정 [논리적 추론]

### 19.4 실기 검증 체크리스트
- [ ] 0.2.2 설치 도우미 실행 → "연결 진단" 줄 내용 확인(지난번 0.2.0 등록에 대한 앱 기록 유무·오류)
- [ ] Claude 앱 재시작·새 채팅 뒤 설치 도우미를 한 번 더 실행 → "연결된 마지막 기록"에 앱 이름 표시
