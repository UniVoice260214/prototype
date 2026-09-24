# UniVoice 로컬 전체 종료 — 백엔드/워커/RAG 서비스 프로세스를 내리고 Docker 컨테이너를 중지한다.
# (DB 데이터는 볼륨에 보존된다. 컨테이너까지 지우려면: docker compose down)
Set-Location $PSScriptRoot

# 백엔드 (포트 3000)
$conns = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) { try { Stop-Process -Id $c.OwningProcess -Force -Confirm:$false } catch {} }

# AI 워커 (univoice_worker 를 실행 중인 python)
Get-WmiObject Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like '*univoice_worker*' } |
  ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -Confirm:$false } catch {} }

# RAG 서비스 (start-all.ps1 이 띄운 rag-experiment 의 uvicorn server:app)
Get-WmiObject Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like '*uvicorn*server:app*' } |
  ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -Confirm:$false } catch {} }

docker compose stop
Write-Host "모든 UniVoice 프로세스와 컨테이너를 중지했습니다." -ForegroundColor Green
