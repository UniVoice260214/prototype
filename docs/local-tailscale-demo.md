# UniVoice 로컬 PC + Tailscale 시연

이 구성은 별도 VM, 공개 도메인, Azure Blob Storage 없이 실제 기기에서 UniVoice를
시연하기 위한 환경이다.

## 구성

- 로컬 Docker: NestJS, AI Worker, PostgreSQL, Redis, Azurite
- 외부 서비스: 기존 LiveKit Cloud, Azure Speech, OpenAI 또는 Azure OpenAI
- HTTPS: Tailscale Serve
- 파일 저장: Microsoft Azurite 로컬 에뮬레이터

NestJS와 Azurite 포트는 `127.0.0.1`에만 바인딩된다. Tailscale에 로그인한 기기는
HTTPS 주소로만 접근한다.

`AZURE_BLOB_PUBLIC_ACCESS=true`는 이 데모의 Azurite 컨테이너에만 사용한다. 실제
Azure Storage 계정에서는 익명 공개 액세스 대신 SAS 또는 인증된 다운로드 API를
사용해야 한다.

## 1. 준비

1. Docker Desktop을 설치하고 실행한다.
2. 시연 PC와 교수·학생 테스트 기기에 Tailscale을 설치한다.
3. 모든 기기를 같은 tailnet에 로그인한다.
4. Tailscale 관리 화면에서 MagicDNS와 HTTPS 인증서를 활성화한다.
5. LiveKit, Azure Speech, 선택한 번역 제공자 자격 증명을 준비한다.

Tailscale 설치 후 PowerShell에서 PC의 DNS 이름을 확인한다.

```powershell
$status = tailscale status --json | ConvertFrom-Json
$status.Self.DNSName.TrimEnd('.')
```

결과는 `pc-name.tailnet-name.ts.net`과 같은 형식이어야 한다.

## 2. 환경변수

```powershell
Copy-Item .env.demo.example .env.demo
```

`.env.demo`에서 다음 항목을 실제 값으로 교체한다.

- `TAILSCALE_HOSTNAME`
- `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `JWT_SECRET`
- `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, `SEED_ADMIN_NAME`
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`
- OpenAI 또는 Azure OpenAI 항목

번역 제공자는 하나만 선택한다.

OpenAI:

```dotenv
TRANSLATE_PROVIDER=openai
OPENAI_API_KEY=...
```

Azure OpenAI:

```dotenv
TRANSLATE_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=<deployment-name>
```

`.env.demo`은 Git에서 제외된다. 메신저나 저장소에 올리지 않는다.

## 3. 검증 및 실행

```powershell
npm.cmd run demo:validate
docker compose --env-file .env.demo -f docker-compose.demo.yml config --quiet
npm.cmd run demo:up
docker compose --env-file .env.demo -f docker-compose.demo.yml ps
```

정상 상태:

- `migrate`, `seed`: `Exited (0)`
- `postgres`, `redis`, `azurite`, `app`: healthy
- `ai-worker`: running

## 4. Tailscale HTTPS 연결

NestJS 웹/API와 Azurite 파일 URL을 각각 Tailscale HTTPS로 연결한다.

```powershell
tailscale serve --bg --https=443 http://127.0.0.1:3000
tailscale serve --bg --https=8443 http://127.0.0.1:10000
tailscale serve status
```

Azurite의 8443 포트는 같은 tailnet 안에서만 접근 가능하며 데모 컨테이너는
파일 읽기 전용 공개 컨테이너를 만든다. 실제 Azure Storage 운영 설정에는 이 옵션을
사용하지 않는다.

tailnet ACL/grants를 사용하는 경우 시연 기기가 PC의 TCP 443과 8443에 접근할 수
있는지 확인한다. `tailscale funnel`은 사용하지 않는다.

## 5. 로컬 및 HTTPS smoke test

먼저 PC에서 loopback 포트를 확인한다.

```powershell
Invoke-WebRequest http://127.0.0.1:3000/health/live -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:3000/health/ready -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:3000/professor -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:3000/join -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:3000/app.js -UseBasicParsing
```

그다음 Tailscale HTTPS 경로를 확인한다.

```powershell
$hostName = (tailscale status --json | ConvertFrom-Json).Self.DNSName.TrimEnd('.')
Invoke-WebRequest "https://$hostName/health/ready" -UseBasicParsing
Invoke-WebRequest "https://$hostName/professor" -UseBasicParsing
Invoke-WebRequest "https://$hostName/join" -UseBasicParsing
```

교수 계정으로 강의자료를 업로드한 뒤 API 응답의 `blobUrl`이
`https://<TAILSCALE_HOSTNAME>:8443/devstoreaccount1/<container>/...` 형식인지
확인한다. 같은 tailnet의 모바일 브라우저에서 그 URL을 직접 열어 200 응답과 파일
내용이 표시되는지 확인한다. URL이 404이면 app 로그에서 컨테이너 초기화와 공개 읽기
ACL 설정 성공 여부를 먼저 확인한다.

## 6. 접속 및 시연

- 교수: `https://<TAILSCALE_HOSTNAME>/professor`
- 학생: 교수 화면의 QR 또는 `https://<TAILSCALE_HOSTNAME>/join`
- Swagger: `https://<TAILSCALE_HOSTNAME>/docs`
- 상태: `https://<TAILSCALE_HOSTNAME>/health/ready`

교수·학생 기기 모두 Tailscale 연결이 켜져 있어야 한다. 시연 중에는 PC, Docker
Desktop 및 Tailscale을 종료하지 않는다.

## 7. 종료

```powershell
npm.cmd run demo:down
tailscale serve --https=443 off
tailscale serve --https=8443 off
```

데이터는 Docker named volume에 유지된다. 데이터를 포함해 초기화하려면 대상 프로젝트가
`univoice-demo`인지 확인한 후 별도로 `docker compose ... down --volumes`를 실행한다.

## 과금 주의

이 구성은 VM, 도메인, Azure Blob 비용을 제거한다. LiveKit, Azure Speech,
OpenAI/Azure OpenAI는 제공 계정의 요금제에 따라 사용량이 발생할 수 있다. 과금 없는
테스트가 목표라면 LiveKit Build, Azure Speech F0 또는 보유 크레딧과 API 사용 한도를
먼저 확인한다.
