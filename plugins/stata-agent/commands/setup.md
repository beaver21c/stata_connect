---
description: Stata 에이전트 설치·연결(Windows) — 실행파일 내려받기·확인값 검증, Stata 점검, 현재 폴더를 분석 폴더로 준비, Claude Code 연결
---

# Stata 에이전트 설치(Claude Code가 대신 진행)

목표: 사용자는 확인·승인만 하고, 아래 단계를 Claude가 순서대로 실행함.
각 단계 결과를 한두 줄로 알려 줌. 실패하면 그 단계에서 멈추고 출력된 원인과 다음 조치를 설명함.
확인되지 않은 다른 방법을 연달아 시도하지 않음.

## 지킬 것
- 명령은 PowerShell 도구로 실행(Windows).
- `data/` 폴더 파일·원자료 파일(.dta·.sav 등)은 열지 않음.
- Stata 등록자 이름·일련번호는 출력·요약에 넣지 않음(`doctor --json`은 이미 제외함).
- 관리자 승인 창(UAC)이 뜨는 단계는 먼저 이유를 설명하고 동의를 받은 뒤 실행.

## 0. 실행 환경 확인
- 명령 실행 도구가 없는 환경(Claude 채팅 화면 등)이면 실행하지 말고, 설명서 https://beaver21c.github.io/stata_connect/ 의 '방법 A(클릭 설치)'를 안내하고 끝냄.
- `[Environment]::OSVersion.Platform` 결과가 `Win32NT`가 아니면 현재 Windows만 지원함을 알리고 끝냄.
- 분석 폴더 = 현재 작업 폴더. 사용자에게 이 폴더를 분석 폴더로 써도 되는지 확인함. 사용자 홈·바탕화면·문서 폴더 전체처럼 넓은 폴더면 하위 폴더를 새로 만들어 그곳에서 다시 시작하도록 제안함.

## 1. 최신 배포 정보
```powershell
$info = Invoke-RestMethod https://beaver21c.github.io/stata_connect/downloads/latest.json
$info.version; $info.exe.url
```

## 2. 실행파일 확인·내려받기
```powershell
$installed = Join-Path $env:LOCALAPPDATA 'StataAgent\stata-agent.exe'
if (Test-Path $installed) { & $installed --version }
```
- 출력 버전이 `$info.version`과 같으면 `$exe = $installed`로 두고 3단계로 감.
- 없거나 버전이 다르면 내려받고 확인값(SHA-256)을 대조함:
```powershell
$exe = Join-Path $env:TEMP $info.exe.file
Invoke-WebRequest -Uri $info.exe.url -OutFile $exe -UseBasicParsing
(Get-FileHash $exe -Algorithm SHA256).Hash.ToLower() -eq $info.exe.sha256
```
- 결과가 `False`이면 내려받은 파일을 지우고 중단함(손상·변조 가능성).

## 3. 설치 도우미 실행(질문 없이)
```powershell
& $exe setup --yes --com no --clients claude-code-project --no-skill --project (Get-Location).Path
```
- 하는 일: 실행파일을 `%LOCALAPPDATA%\StataAgent`에 복사, Stata 확인, 분석 폴더 규약(`data/`·`output/`·지침·권한·실행 전 검사) 생성, 현재 폴더 `.mcp.json`에 `stata` 서버 등록.
- 스킬은 이 플러그인에 들어 있으므로 따로 복사하지 않음(`--no-skill`).
- 출력에 `[error]`나 '실패'가 있으면 그 줄을 사용자에게 보여 주고 중단함.
- Stata를 찾지 못했다는 출력이 나오면 사용자에게 Stata 실행파일 위치를 물어 `--stata-exe "<경로>"`를 붙여 다시 실행함.

## 4. Stata 점검 결과 요약
```powershell
& $installed doctor --json
```
- 선택된 Stata의 경로·에디션·버전·라이선스 유효 여부·COM 등록 여부만 요약함.
- 버전이 17 미만이면 지원 범위(Stata 17 이상) 밖임을 알림.

## 5. (선택) Stata 화면 연동(COM) 등록
사용자에게 먼저 설명함: "분석 과정을 Stata 창에서 직접 보려면 Windows 관리자 승인이 1회 필요함. 하지 않아도 배치 실행으로 분석은 가능함."
동의하면 실행하고, 화면에 뜨는 승인 창에서 '예'를 누르도록 안내함:
```powershell
& $installed register-com
```

## 6. 마무리 안내(사용자에게 그대로 전달)
- 이 세션을 닫고 같은 폴더에서 새 세션을 시작함 → `stata` MCP 서버 사용 여부를 묻는 창에서 허용함.
- 원자료는 `data/` 폴더에 넣음. AI는 `data/` 파일을 직접 열지 않고 `stata_schema`로 변수 구조만 확인함.
- 첫 시험 요청 예: "Stata 상태 확인하고, auto 예제로 가격·연비 기술통계 내줘"
