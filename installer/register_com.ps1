<#
.SYNOPSIS
  Stata Automation(COM) 등록·해제 — 관리자 권한 필요(설계서 §0.4 3단계, §6.4).

.DESCRIPTION
  Stata 공식 안내: Stata 폴더에서 `StataSE /Register`(또는 /Regserver), 해제는 /Unregister.
  ProgID(stata.StataOLEApp)는 하나뿐이므로 마지막으로 등록한 실행파일이 기본이 됨(논리적 추론).
  관리자 권한이 아니면 UAC 승인 창을 띄워 자기 자신을 다시 실행함.

.NOTES
  상태: 실기 미검증 → Phase 2 검수 대상.
  사용: powershell -ExecutionPolicy Bypass -File installer\register_com.ps1 -StataExe C:\Stata18\StataSE-64.exe [-Unregister]
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$StataExe,
  [switch]$Unregister
)

if (-not (Test-Path $StataExe)) {
  Write-Host "Stata 실행파일 없음: $StataExe" -ForegroundColor Red
  exit 1
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-StataExe', "`"$StataExe`"")
  if ($Unregister) { $argList += '-Unregister' }
  Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $argList -Wait
  exit $LASTEXITCODE
}

$flag = if ($Unregister) { '/Unregister' } else { '/Register' }
Start-Process -FilePath $StataExe -ArgumentList $flag -Wait

try {
  $clsid = (Get-ItemProperty -Path 'Registry::HKEY_CLASSES_ROOT\stata.StataOLEApp\CLSID' -ErrorAction Stop).'(default)'
  $server = (Get-ItemProperty -Path "Registry::HKEY_CLASSES_ROOT\CLSID\$clsid\LocalServer32" -ErrorAction Stop).'(default)'
  if ($Unregister) { Write-Host "해제 후에도 등록 정보가 남아 있음: $server" -ForegroundColor Yellow }
  else { Write-Host "COM 등록 완료: $server" -ForegroundColor Green }
} catch {
  if ($Unregister) { Write-Host 'COM 등록 해제 완료' -ForegroundColor Green }
  else { Write-Host 'COM 등록 확인 실패 → Stata를 관리자 권한으로 실행해 수동 등록 필요' -ForegroundColor Red; exit 1 }
}
