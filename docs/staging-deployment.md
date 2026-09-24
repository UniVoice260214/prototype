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

PostgreSQL, Redis, NestJS 포트는 외부에 공개하지 않는다. 외부에서는
Caddy의 80/443 포트만 접근한다.

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
