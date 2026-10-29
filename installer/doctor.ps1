<#
.SYNOPSIS
  Stata 에이전트 사전 점검(설계서 §6·§13): Stata 설치·라이선스·COM 등록·Python·클라이언트 설정.

.DESCRIPTION
  Python이 없는 PC에서도 실행되도록 PowerShell만 사용.
  라이선스 일련번호는 출력하지 않음. 등록자는 기관 라이선스 확인용으로 이 화면에만 표시.

.NOTES
  상태: 실기 미검증(작성 환경에 Windows·Stata 없음) → Phase 2에서 Stata 17·18·19.5로 검수.
  사용: powershell -ExecutionPolicy Bypass -File installer\doctor.ps1 [-StataExe C:\Stata18\StataSE-64.exe] [-NoAbout]
#>
[CmdletBinding()]
param(
  [string]$StataExe,
  [switch]$NoAbout
)

$ErrorActionPreference = 'Continue'
$exeRegex = '^Stata(MP|SE|BE|IC)?-64\.exe$'

function Find-StataExe {
  $roots = @('C:\', $env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ } | Select-Object -Unique
  foreach ($root in $roots) {
    Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -like 'Stata*' } |
      ForEach-Object {
        Get-ChildItem -Path $_.FullName -File -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -match $exeRegex } |
          ForEach-Object { $_.FullName }
      }
  }
}

function Get-ComRegistration {
  try {
    $clsid = (Get-ItemProperty -Path 'Registry::HKEY_CLASSES_ROOT\stata.StataOLEApp\CLSID' -ErrorAction Stop).'(default)'
    $server = (Get-ItemProperty -Path "Registry::HKEY_CLASSES_ROOT\CLSID\$clsid\LocalServer32" -ErrorAction Stop).'(default)'
    return $server
  } catch {
    return $null
  }
}

function Get-StataAbout([string]$Exe) {
  $tmp = Join-Path $env:TEMP ('sa_about_' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $tmp | Out-Null
  try {
    Set-Content -Path (Join-Path $tmp '_sa_about.do') -Value 'about' -Encoding ASCII
    # /e: 배치 실행 후 대기 없이 종료. 로그는 현재 폴더에 do-file 이름으로 생성됨
    Start-Process -FilePath $Exe -ArgumentList '/e', 'do', '_sa_about.do' -WorkingDirectory $tmp -Wait -WindowStyle Hidden | Out-Null
    $log = Join-Path $tmp '_sa_about.log'
    if (Test-Path $log) { return (Get-Content -Path $log -Raw -Encoding UTF8) }
    return $null
  } finally {
    Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
  }
}

function ConvertFrom-About([string]$Text) {
  $info = [ordered]@{ Product = $null; Edition = $null; Version = $null; Expires = $null; Perpetual = $false; Refused = $false; LicensedTo = @() }
  if (-not $Text) { return $info }
  if ($Text -match 'request ignored because of batch mode') { $info.Refused = $true }
  if ($Text -match '(?m)^(StataNow|Stata)(?:/(MP|SE|BE|IC))?\s+(\d+(?:\.\d+)?)\s+for\s+') {
    $info.Product = $Matches[1]; $info.Edition = $Matches[2]; $info.Version = $Matches[3]
  }
  if ($Text -match '(?m)^\s*Stata license:\s*(.+)$') {
    $lic = $Matches[1]
    if ($lic -match 'perpetual') { $info.Perpetual = $true }
    if ($lic -match 'expiring\s+(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})') {
      $info.Expires = [datetime]::ParseExact(('{0:00} {1} {2}' -f [int]$Matches[1], $Matches[2], $Matches[3]), 'dd MMM yyyy', [Globalization.CultureInfo]::InvariantCulture)
    }
  }
  if ($Text -match '(?m)^\s*Licensed to:\s*(.+)$') { $info.LicensedTo += $Matches[1].Trim() }
  return $info
}

Write-Host '== Stata 에이전트 사전 점검 ==' -ForegroundColor Cyan

# 1. Stata 설치
$exes = @()
if ($StataExe) { $exes += $StataExe }
$exes += Find-StataExe
$exes = $exes | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
if (-not $exes) {
  Write-Host '[실패] Stata 설치를 찾지 못함 → -StataExe로 경로 지정' -ForegroundColor Red
} else {
  foreach ($exe in $exes) {
    $line = "[발견] $exe"
    if (-not $NoAbout) {
      $about = ConvertFrom-About (Get-StataAbout $exe)
      if ($about.Refused) {
        $line += ' → 배치 실행 거부(라이선스 만료 가능성)'
      } elseif ($about.Version) {
        $state = if ($about.Perpetual) { '영구' } elseif ($about.Expires) { if ($about.Expires -ge (Get-Date).Date) { '유효(만료 ' + $about.Expires.ToString('yyyy-MM-dd') + ')' } else { '만료(' + $about.Expires.ToString('yyyy-MM-dd') + ')' } } else { '미확인' }
        $line += " → $($about.Product)/$($about.Edition) $($about.Version), 라이선스 $state"
        if ($about.LicensedTo) { $line += "`n        등록자(로컬 표시 전용): $($about.LicensedTo -join ' / ')" }
      } else {
        $line += ' → about 출력 해석 실패'
      }
    }
    Write-Host $line
  }
}

# 2. COM 등록
$com = Get-ComRegistration
if ($com) { Write-Host "[통과] COM 등록: $com" -ForegroundColor Green }
else { Write-Host '[주의] COM 미등록 → installer\register_com.ps1 실행(관리자 승인). 미등록이면 배치 모드로만 작동' -ForegroundColor Yellow }

# 3. Python(개발 단계에서만 필요, 배포본은 단일 exe 예정)
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) { Write-Host "[정보] Python: $($py.Source)" } else { Write-Host '[정보] Python 없음(배포용 단일 exe 사용 시 불필요)' }

# 4. 클라이언트
$desktopCfg = Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'
if (Test-Path $desktopCfg) {
  $hasStata = (Get-Content $desktopCfg -Raw -Encoding UTF8) -match '"stata"\s*:'
  Write-Host ("[정보] Claude Desktop 설정: {0} (stata 서버 {1})" -f $desktopCfg, $(if ($hasStata) { '등록됨' } else { '없음' }))
} else {
  Write-Host '[정보] Claude Desktop 설정 파일 없음(미설치 또는 경로 상이 — 경로는 공식 문서 미확인)'
}
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$codexCfg = Join-Path $codexHome 'config.toml'
if (Test-Path $codexCfg) {
  $hasStata = (Get-Content $codexCfg -Raw -Encoding UTF8) -match '(?m)^\[mcp_servers\.stata\]'
  Write-Host ("[정보] Codex 설정: {0} (stata 서버 {1})" -f $codexCfg, $(if ($hasStata) { '등록됨' } else { '없음' }))
} else {
  Write-Host '[정보] Codex 설정 파일 없음'
}
$claudeCli = Get-Command claude -ErrorAction SilentlyContinue
Write-Host ("[정보] Claude Code CLI: {0}" -f $(if ($claudeCli) { $claudeCli.Source } else { '없음' }))
