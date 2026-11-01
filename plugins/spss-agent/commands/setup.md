---
description: SPSS 에이전트 설치·연결(Windows) — 실행파일 내려받기·확인값 검증, SPSS 점검(22 이상·동봉 Python), 현재 폴더를 분석 폴더로 준비, Claude Code 연결
---

# SPSS 에이전트 설치(Claude Code가 대신 진행)

목표: 사용자는 확인·승인만 하고, 아래 단계를 Claude가 순서대로 실행함.
각 단계 결과를 한두 줄로 알려 줌. 실패하면 그 단계에서 멈추고 출력된 원인과 다음 조치를 설명함.
확인되지 않은 다른 방법을 연달아 시도하지 않음.

## 지킬 것
- 명령은 PowerShell 도구로 실행(Windows).
- `data/` 폴더 파일·원자료 파일(.sav·.zsav·.por 등)은 열지 않음.
- SPSS(stats.exe)나 SPSS 동봉 Python을 직접 실행하지 않음(설치 확인은 아래 `doctor`만 사용).

## 0. 실행 환경 확인
- 명령 실행 도구가 없는 환경(Claude 채팅 화면 등)이면 실행하지 말고, 설명서 https://beaver21c.github.io/stata_connect/spss.html 의 '방법 A(클릭 설치)'를 안내하고 끝냄.
- `[Environment]::OSVersion.Platform` 결과가 `Win32NT`가 아니면 현재 Windows만 지원함을 알리고 끝냄.
- 분석 폴더 = 현재 작업 폴더. 사용자에게 이 폴더를 분석 폴더로 써도 되는지 확인함. 사용자 홈·바탕화면·문서 폴더 전체처럼 넓은 폴더면 하위 폴더를 새로 만들어 그곳에서 다시 시작하도록 제안함.

## 1. 최신 배포 정보
```powershell
$info = Invoke-RestMethod https://beaver21c.github.io/stata_connect/downloads/latest.json
$info.version; $info.spss.exe.url
```

## 2. 실행파일 확인·내려받기
```powershell
$installed = Join-Path $env:LOCALAPPDATA 'SpssAgent\spss-agent.exe'
if (Test-Path $installed) { & $installed --version }
```
- 출력 버전이 `$info.version`과 같으면 `$exe = $installed`로 두고 3단계로 감.
- 없거나 버전이 다르면 내려받고 확인값(SHA-256)을 대조함:
```powershell
$exe = Join-Path $env:TEMP $info.spss.exe.file
Invoke-WebRequest -Uri $info.spss.exe.url -OutFile $exe -UseBasicParsing
(Get-FileHash $exe -Algorithm SHA256).Hash.ToLower() -eq $info.spss.exe.sha256
```
- 결과가 `False`이면 내려받은 파일을 지우고 중단함(손상·변조 가능성).

## 3. 설치 도우미 실행(질문 없이)
```powershell
& $exe setup --yes --clients claude-code-project --no-skill --project (Get-Location).Path
```
- 하는 일: 실행파일을 `%LOCALAPPDATA%\SpssAgent`에 복사, SPSS 확인, 분석 폴더 규약(`data/`·`output/`·지침·권한·실행 전 검사) 생성, 현재 폴더 `.mcp.json`에 `spss` 서버 등록.
- 스킬은 이 플러그인에 들어 있으므로 따로 복사하지 않음(`--no-skill`).
- 출력에 `[error]`나 '실패'가 있으면 그 줄을 사용자에게 보여 주고 중단함.
- SPSS를 찾지 못했다는 출력이면 사용자에게 SPSS 설치 폴더(stats.exe가 있는 폴더)를 물어 `--spss-home "<폴더>"`를 붙여 다시 실행함.
- '동봉 Python 없음'이면: SPSS 설치 때 'Python Essentials'(Integration Plug-in for Python)를 포함했는지 사용자에게 확인하도록 안내함. 다른 위치에 있는 python.exe를 사용자가 알려 주면 `--spss-python "<경로>"`를 붙여 다시 실행함.

## 4. SPSS 점검 결과 요약
```powershell
& $installed doctor --json
```
- 선택된 SPSS의 설치 폴더·버전·동봉 Python(2.7 또는 3.x)·지원 여부(`supported`)만 요약함.
- 버전이 22 미만이면 지원 범위(SPSS 22 이상) 밖임을 알림.

## 5. 마무리 안내(사용자에게 그대로 전달)
- 이 세션을 닫고 같은 폴더에서 새 세션을 시작함 → `spss` MCP 서버 사용 여부를 묻는 창에서 허용함.
- SPSS 창은 뜨지 않음(화면 없이 실행). 결과는 `output/logs`의 출력 파일과 대화로 확인함.
- 원자료는 `data/` 폴더에 넣음. AI는 `data/` 파일을 직접 열지 않고 `spss_schema`로 변수 구조만 확인함.
- 첫 시험 요청 예: "SPSS 연결 점검해줘", 이어서 "예제 자료로 기술통계와 t검정 해줘"
