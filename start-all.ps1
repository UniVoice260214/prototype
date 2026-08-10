# UniVoice 로컬 전체 실행 — 이 스크립트 하나로 인프라 + AI 워커 + 백엔드를 띄운다.
#
#   .\start-all.ps1            # 전부 실행 (워커는 새 창에서)
#   .\start-all.ps1 -NoWorker  # 백엔드만 (워커 없이 UI/업로드만 볼 때)
#
# 종료는 .\stop-all.ps1
param([switch]$NoWorker)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "[1/3] Docker 인프라 (postgres, redis, azurite)..." -ForegroundColor Cyan
docker compose up -d postgres redis azurite

if (-not $NoWorker) {
  # 이전 실행에서 남은 워커를 먼저 정리한다. 살아는 있지만 이벤트를 더 이상 처리하지
  # 않는 워커가 남아 있으면 교수 화면에 "AI 워커 응답 대기"로만 보인다.
  # (워커 1개 실행 시 python.exe 가 2개 뜨는 것은 정상이다 — LiveKit SDK 구조.)
  $stale = Get-WmiObject Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*univoice_worker*' }
  foreach ($p in $stale) {
    Write-Host "  기존 워커 종료 (PID $($p.ProcessId))" -ForegroundColor Yellow
    try { Stop-Process -Id $p.ProcessId -Force -Confirm:$false } catch {}
  }

  Write-Host "[2/3] AI 워커 (새 창)..." -ForegroundColor Cyan
  Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$PSScriptRoot\ai-worker'; .venv\Scripts\python.exe -m univoice_worker.main"
  )
} else {
  Write-Host "[2/3] AI 워커 건너뜀 (-NoWorker)" -ForegroundColor Yellow
}

Write-Host "[3/3] 백엔드 서버 (이 창, Ctrl+C 로 중지)..." -ForegroundColor Cyan
Write-Host "  교수 화면: http://localhost:3000/professor" -ForegroundColor Green
Write-Host "  Swagger  : http://localhost:3000/docs" -ForegroundColor Green
npm run start:dev
