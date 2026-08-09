# 유료(Azure 기반) 배포 전환 체크리스트

무료 티어/데모 환경에서 발생하는 콜드스타트·용량 제한·연결 불안정을 없애기 위한
유료 배포 전환 가이드. 기존 [staging-deployment.md](./staging-deployment.md)의 절차를
그대로 따르되, 아래 항목을 유료 리소스로 바꾼다.

## 전환 대상 리소스

| 구성 요소 | 현재(무료/데모) | 전환 대상 | 비고 |
|-----------|----------------|-----------|------|
| 파일 저장 | 로컬/무료 Blob | **Azure Blob Storage (Standard, Hot tier)** | 코드는 이미 `@azure/storage-blob` 사용 — 연결 문자열만 교체 |
| DB | 컨테이너 Postgres | Azure Database for PostgreSQL Flexible Server (B1ms~) | `synchronize:false` 유지, `npm run migration:run:prod` 로 스키마 반영 |
| Redis | 컨테이너 Redis | Azure Cache for Redis (Basic C0~) | Pub/Sub + 세션 상태 + TTS dedupe 공용 |
| LiveKit | 셀프호스팅 | LiveKit Cloud 또는 VM 상시 인스턴스 | 재연결 안정성이 곧 수업 품질 |
| STT/TTS | Azure Speech F0(무료) | **Azure Speech S0(Standard)** | F0 는 동시 연결 1개·쿼터 제한으로 수업 중 끊김의 주 원인 |
| 번역 | OpenAI/AOAI 무료 크레딧 | 유료 결제 계정 + 사용량 알림 | 타임아웃 8s 기준 재검토 |

## 전환 절차

1. **Azure Blob (Standard) 생성**
   - Storage Account: `Standard LRS`, Hot tier, 컨테이너 `materials`
   - `.env.staging` 의 `AZURE_BLOB_CONNECTION_STRING`, `AZURE_BLOB_CONTAINER` 교체
   - 수명주기 정책: 세션 종료 90일 후 Cool tier 이동(비용 절감)
2. **Azure Speech S0 로 업그레이드**
   - `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` 교체 (워커 `.env`)
   - S0 전환 후 `STT_MAX_RECONNECTS`(기본 3) 초과 실패가 사라지는지 모니터링
3. **관리형 Postgres / Redis 연결**
   - `DATABASE_URL`, `REDIS_URL` 교체 (백엔드 + 워커 양쪽)
   - Redis 는 `notify-keyspace-events` 기본값으로 충분 (Pub/Sub 만 사용)
4. **검증**
   - `npm run staging:validate` 로 환경변수 확인
   - `npm run migration:run:prod` → `npm run seed:prod`
   - 수업 시작→학생 입장→자막/음성 수신→종료 전체 플로우 리허설
5. **모니터링/알림**
   - Azure Cost Alert (월 예산), Speech 사용량 쿼터 알림
   - 백엔드 `/health` 외부 모니터링(UptimeRobot 등) 연결

## 주의

- Blob 연결 문자열에는 계정 키가 포함된다 — 저장소 커밋 금지, 배포 환경 변수로만 주입.
- Speech 리소스는 STT/TTS 공용이므로 리전은 LiveKit 서버와 가까운 곳(예: koreacentral)으로.
- 전환 후에도 `docker-compose.staging.yml` 의 로컬 Postgres/Redis 서비스는 제거해야
  이중 연결 사고(로컬에 쓰고 관리형에서 읽는)가 없다.
