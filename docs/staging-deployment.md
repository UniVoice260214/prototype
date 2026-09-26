# UniVoice 최소 HTTPS 스테이징 배포

이 구성은 실제 모바일·태블릿 브라우저에서 마이크, LiveKit, 자막 및
TTS를 검증하기 위한 최소 스테이징 환경이다.

## 구성 요소

- Caddy: 공개 HTTPS와 인증서 자동 갱신
- NestJS API/Web: 교수·학생 화면과 Control Plane
- PostgreSQL: 영속 데이터
- Redis: 세션 상태, Pub/Sub, Worker 상태
- AI Worker: Azure Speech, 번역, TTS, LiveKit 처리
- migrate/seed: 배포 시 migration과 초기 관리자 생성을 순서대로 실행
- RAG: 전공 용어 문맥 검색
  - `rag-indexer`: 데모 코퍼스 인덱스 1회 빌드. 임베딩 모델(KURE-v1) 다운로드를
    포함해 첫 실행에 10~15분 걸린다. `rag-service`와 AI Worker는 이 작업이
    끝난 뒤에 시작한다.
  - `rag-indexer-daemon`: 업로드된 강의자료를 과목별 인덱스에 누적 인덱싱
  - `rag-service`: 검색 API. AI Worker가 세그먼트마다 최대 `RAG_TIMEOUT_SEC`
    만큼 기다린다

PostgreSQL, Redis, NestJS, RAG 포트는 외부에 공개하지 않는다. 외부에서는
Caddy의 80/443 포트만 접근한다.

### 강의자료 익명 읽기 (`AZURE_BLOB_PUBLIC_ACCESS`)

`rag-indexer-daemon`은 업로드된 자료를 URL로 직접 내려받는다. 그래서 업로드
자료를 RAG에 인덱싱하려면 `.env.staging`에서 `AZURE_BLOB_PUBLIC_ACCESS=true`와
`AZURE_BLOB_PUBLIC_BASE_URL`(https)을 설정해야 한다. 켜면 **URL을 아는 누구나
로그인 없이 자료를 받을 수 있다.** compose 기본값은 `false`이며, 운영 전환 전에
SAS 또는 인증된 다운로드 API로 바꿔야 한다. 끄더라도 데모 코퍼스 기반 RAG는
동작한다.

## 준비 사항

1. Docker Engine과 Docker Compose plugin이 설치된 Linux VM
2. VM 공인 IP를 가리키는 staging 도메인의 DNS A/AAAA 레코드
3. 방화벽에서 TCP 80/443 및 UDP 443 허용
4. LiveKit 접속 정보
5. Azure Speech, Azure Blob, OpenAI 또는 Azure OpenAI 접속 정보

LiveKit Cloud를 사용하면 LiveKit 자체 포트를 이 VM에 열 필요가 없다.

## 환경변수 준비

```bash
cp .env.staging.example .env.staging
```

`.env.staging`의 placeholder를 모두 실제 값으로 교체한다. 이 파일은
Git에서 제외되며 저장소에 커밋하면 안 된다.

비밀번호 생성 예:

```bash
openssl rand -base64 48 | tr -dc 'A-Za-z0-9_-' | head -c 40
```

배포 전에 다음 검증을 반드시 실행한다.

```bash
npm run staging:validate
npm run staging:audit
docker compose --env-file .env.staging -f docker-compose.staging.yml config --quiet
```

검증 도구는 비밀값을 출력하지 않고 누락·placeholder·길이·URL 형식만
확인한다.

`staging:audit`은 공개 배포 전에 critical runtime 취약점이 있으면
실패한다. 현재 TypeORM 0.3.x의 내부 파일 탐색 의존성에는 high 등급
`brace-expansion` 경고가 남아 있다. 애플리케이션은 glob 패턴을 사용자
입력으로 받지 않으므로 원격 요청 경로에서는 사용되지 않는다. npm이
제안하는 `audit fix --force`는 TypeORM 1.x로의 강제 major update이므로
자동 적용하지 않고 별도 호환성 작업으로 추적한다.

## 최초 배포

```bash
docker compose --env-file .env.staging -f docker-compose.staging.yml up -d --build
docker compose --env-file .env.staging -f docker-compose.staging.yml ps
```

배포 순서는 다음과 같다.

```text
PostgreSQL healthy
→ migration 완료
→ admin seed 완료
→ NestJS readiness 통과
→ AI Worker 및 Caddy 시작
```

상태 확인:

```bash
curl -fsS https://<STAGING_DOMAIN>/health/live
curl -fsS https://<STAGING_DOMAIN>/health/ready
docker compose --env-file .env.staging -f docker-compose.staging.yml logs --tail=100 app ai-worker caddy
```

정상 응답 예:

```json
{
  "status": "ok",
  "checks": {
    "database": "up",
    "redis": "up"
  },
  "timestamp": "..."
}
```

## 업데이트 배포

```bash
git pull
npm run staging:validate
npm run staging:audit
docker compose --env-file .env.staging -f docker-compose.staging.yml up -d --build
```

Migration과 seed는 멱등 실행된다. seed는 기존 관리자 비밀번호를
덮어쓰지 않는다.

서버에서 `docker-compose.staging.yml`을 직접 고치지 않는다. 서버마다 다른 값은
모두 `.env.staging`에 두고, compose 변경은 저장소에 커밋한 뒤 `git pull`로
받는다. 서버에서 고친 compose가 있으면 `git pull`이 거부된다.

지연 튜닝 값(`STT_SEGMENTATION_SILENCE_MS`, `CAPTION_DRAFT_ENABLED`,
`TTS_SPEAKING_RATE` 등)과 계측(`LATENCY_LOG_PATH`)도 `.env.staging`으로
조정한다. 값과 측정 결과는 `docs/latency-results-2026-09-26.md`를 따른다.
코드 변경 없이 값만 바꿨다면 빌드 없이 워커만 다시 만든다.

```bash
docker compose --env-file .env.staging -f docker-compose.staging.yml up -d ai-worker
```

## 롤백

애플리케이션 롤백은 이전 Git commit으로 이동한 뒤 이미지를 다시
빌드한다. 데이터베이스 migration rollback은 데이터 손실 가능성을
검토한 뒤 별도로 실행한다.

```bash
git checkout <KNOWN_GOOD_COMMIT>
docker compose --env-file .env.staging -f docker-compose.staging.yml up -d --build
```

## 보안 주의사항

- `.env.staging`을 메신저나 Git에 올리지 않는다.
- `AUTH_DISABLED`는 compose에서 항상 `false`다.
- production에서는 32자 미만 JWT secret과 HTTP QR URL을 거부한다.
- Swagger가 필요 없어진 뒤 `SWAGGER_ENABLED=false`로 변경한다.
- 테스트가 끝나면 seed 관리자 비밀번호를 교체한다.
- 운영 전환 전 DB 백업, secret manager, 로그 수집 및 모니터링을 추가한다.

## 실제 기기 테스트 URL

- 교수 모바일: `https://<STAGING_DOMAIN>/professor`
- 학생 태블릿: QR 또는 `https://<STAGING_DOMAIN>/join`
- Swagger: `https://<STAGING_DOMAIN>/docs`

구체적인 검증 항목은
[device-integration-checklist.md](device-integration-checklist.md)를 따른다.
