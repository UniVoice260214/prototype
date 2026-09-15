# UniVoice 로컬 전체 실행 — 이 스크립트 하나로 인프라 + RAG 서비스 + AI 워커 + 백엔드를 띄운다.
#
#   .\start-all.ps1            # 전부 실행 (RAG 서비스·워커는 각각 새 창에서)
#   .\start-all.ps1 -NoWorker  # 백엔드만 (워커·RAG 없이 UI/업로드만 볼 때)
#
# RAG 서비스는 ai-worker\.env 에서 RAG_ENABLED=true 이고 RAG_URL 이 로컬(127.0.0.1/localhost)일 때만
# 띄운다. 인덱스는 미리 1회 빌드해 둬야 한다:  cd rag-experiment; python src\build_demo_indexes.py
# 종료는 .\stop-all.ps1
param([switch]$NoWorker)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# KEY=VALUE 형식의 .env 를 해시테이블로 읽는다 (주석·빈 줄 무시, 따옴표 제거).
function Read-DotEnv([string]$Path) {
  $values = @{}
  if (-not (Test-Path $Path)) { return $values }
  foreach ($line in Get-Content $Path) {
    if ($line -match '^\s*#') { continue }
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
      $values[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
    }
  }
  return $values
}

Write-Host "[1/4] Docker 인프라 (postgres, redis, azurite)..." -ForegroundColor Cyan
docker compose up -d postgres redis azurite

if (-not $NoWorker) {
  # ── RAG 서비스 (rag-experiment 의 FastAPI) ──
  # 워커는 RAG 가 안 떠 있어도 fail-open 으로 번역을 계속하므로, 여기서 안 띄우면
  # "켜 놨는데 문맥이 안 붙는" 상태가 조용히 생긴다. 교수 화면 상태줄이 원인을 보여준다.
  $workerEnv = Read-DotEnv "$PSScriptRoot\ai-worker\.env"
  $ragEnabled = ($workerEnv['RAG_ENABLED'] -match '^(1|true|yes|on)$')
  if ($ragEnabled) {
    $ragUrl = if ($workerEnv['RAG_URL']) { $workerEnv['RAG_URL'] } else { 'http://127.0.0.1:8000' }
    $uri = $null
    try { $uri = [System.Uri]$ragUrl } catch {}
    if ($null -eq $uri -or $uri.Host -notin @('127.0.0.1', 'localhost')) {
      Write-Host "[2/4] RAG 서비스 건너뜀 — RAG_URL($ragUrl) 이 로컬 주소가 아니다. 로컬 실행이면 ai-worker\.env 에 RAG_URL=http://127.0.0.1:8000 으로 바꿔라." -ForegroundColor Yellow
    } else {
      $port = if ($uri.IsDefaultPort) { 80 } else { $uri.Port }
      $listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
      if ($listening) {
        Write-Host "[2/4] RAG 서비스 이미 실행 중 (포트 $port)" -ForegroundColor Green
      } else {
        $indexFiles = Get-ChildItem "$PSScriptRoot\rag-experiment\indexes" -Recurse -Filter faiss.index -ErrorAction SilentlyContinue
        if (-not $indexFiles) {
          Write-Host "  경고: rag-experiment\indexes 에 인덱스가 없다 — 서비스는 뜨지만 문맥 주입은 안 된다(교수 화면 'RAG 인덱스 없음')." -ForegroundColor Yellow
          Write-Host "        빌드: cd rag-experiment; python src\build_demo_indexes.py" -ForegroundColor Yellow
        }
        $ragPython = "$PSScriptRoot\rag-experiment\.venv\Scripts\python.exe"
        if (-not (Test-Path $ragPython)) { $ragPython = "python" }
        Write-Host "[2/4] RAG 서비스 (새 창, http://127.0.0.1:$port)..." -ForegroundColor Cyan
        Start-Process powershell -ArgumentList @(
          "-NoExit",
          "-Command",
          "Set-Location '$PSScriptRoot\rag-experiment'; & '$ragPython' -m uvicorn server:app --app-dir src --host 127.0.0.1 --port $port"
        )
      }
    }
  } else {
    Write-Host "[2/4] RAG 서비스 건너뜀 — ai-worker\.env 의 RAG_ENABLED 가 true 가 아니다 (번역에 강의자료 문맥이 주입되지 않는다)" -ForegroundColor Yellow
  }

  # 이전 실행에서 남은 워커를 먼저 정리한다. 살아는 있지만 이벤트를 더 이상 처리하지
  # 않는 워커가 남아 있으면 교수 화면에 "AI 워커 응답 대기"로만 보인다.
  # (워커 1개 실행 시 python.exe 가 2개 뜨는 것은 정상이다 — LiveKit SDK 구조.)
  $stale = Get-WmiObject Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*univoice_worker*' }
  foreach ($p in $stale) {
    Write-Host "  기존 워커 종료 (PID $($p.ProcessId))" -ForegroundColor Yellow
    try { Stop-Process -Id $p.ProcessId -Force -Confirm:$false } catch {}
  }

  Write-Host "[3/4] AI 워커 (새 창)..." -ForegroundColor Cyan
  Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$PSScriptRoot\ai-worker'; .venv\Scripts\python.exe -m univoice_worker.main"
  )
} else {
  Write-Host "[2/4] RAG 서비스 건너뜀 (-NoWorker)" -ForegroundColor Yellow
  Write-Host "[3/4] AI 워커 건너뜀 (-NoWorker)" -ForegroundColor Yellow
}

Write-Host "[4/4] 백엔드 서버 (이 창, Ctrl+C 로 중지)..." -ForegroundColor Cyan
Write-Host "  교수 화면: http://localhost:3000/professor" -ForegroundColor Green
Write-Host "  Swagger  : http://localhost:3000/docs" -ForegroundColor Green
npm run start:dev
