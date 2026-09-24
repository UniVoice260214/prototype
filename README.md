# UniVoice Core API Backend

NestJS control plane for the UniVoice realtime lecture translation system.
This server manages auth, metadata, sessions, storage, and worker orchestration.
Realtime speech processing is handled by the separate Python worker in
[ai-worker](C:/UniVoice/prototype-Yumin/ai-worker/README.md).

## Responsibilities

- User, professor, and student authentication
- CRUD for schools, departments, professors, courses, and students
- Session lifecycle management and LiveKit token issuance
- Material upload to Azure Blob Storage and indexing job dispatch
- Glossary CRUD and Redis prewarm
- QR generation for student join flow

## Worker Interfaces

The backend shares these Redis keys and channels with the AI worker and RAG worker:

- Keys: `session:{id}:config`, `session:{id}:status`, `session:{id}:worker:status`, `glossary:{courseId}`
- Queue: `rag:index:queue`
- Channels: `sessions.started`, `sessions.ended`, `materials.indexing.requested`, `materials.indexing.completed`

Definitions live in:

- [src/common/redis-keys.ts](/C:/UniVoice/prototype-Yumin/src/common/redis-keys.ts:1)
- [src/modules/events/events.types.ts](/C:/UniVoice/prototype-Yumin/src/modules/events/events.types.ts:1)

## Requirements

- Node.js 20+
- PostgreSQL 13+
- Redis 6+
- Azure Blob Storage account
- LiveKit Cloud or self-hosted LiveKit

## Quick Start

```bash
npm install
cp .env.example .env
npm run migration:run
npm run start:dev
```

Fill at least these variables in `.env`:

- `DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET`
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `AZURE_BLOB_CONNECTION_STRING`
- `AZURE_BLOB_CONTAINER`

Useful local URLs:

- API: `http://localhost:3000`
- Swagger: `http://localhost:3000/docs`

## HTTPS Staging

실제 모바일·태블릿 통합 테스트용 Docker Compose와 Caddy HTTPS 구성이
포함되어 있습니다.

- 배포 절차: [docs/staging-deployment.md](docs/staging-deployment.md)
- 실제 기기 체크리스트:
  [docs/device-integration-checklist.md](docs/device-integration-checklist.md)
- 환경변수 예시: [.env.staging.example](.env.staging.example)

## Local Tailscale Demo

로컬 PC에서 PostgreSQL, Redis, Azurite, API 및 AI Worker를 실행하고 Tailscale
Serve로 실제 모바일·태블릿 HTTPS 시연을 할 수 있습니다.

- 실행 절차: [docs/local-tailscale-demo.md](docs/local-tailscale-demo.md)
- 환경변수 예시: [.env.demo.example](.env.demo.example)
- Compose: [docker-compose.demo.yml](docker-compose.demo.yml)
- 완전 통합 RAG 시연: [docs/rag-demo.md](docs/rag-demo.md)

## Scripts

- `npm run start:dev`: Start the API in watch mode
- `npm run build`: Build TypeScript into `dist/`
- `npm run start:prod`: Run the production build
- `npm run migration:run`: Apply pending migrations
- `npm run migration:generate -- <name>`: Generate a migration from entity changes
- `npm run migration:revert`: Revert the latest migration
- `npm run seed`: Create the initial admin user
- `npm test`: Run unit tests
- `npm run test:e2e`: Run end-to-end tests
- `npm run lint`: Run ESLint with autofix

## Project Layout

```text
src/
  main.ts
  app.module.ts
  common/
  config/
  infra/
  modules/
  migrations/
```

## 병합 내역 — Yumin × Sehui 프로토타입 통합 (2026-08-10)

`Yumin` 브랜치(1번 음성 파이프라인·세션 복구 + 6번 RAG 품질)와 `Sehui` 브랜치
(4번 강의 관리·자막 + 5번 테스트·STT·인프라)를 git merge 로 통합한 기록이다.
병합 커밋: `f529fbf` (78개 파일, +15,953 / -222).

### 통합된 기능

**Yumin 쪽에서 온 것 (1 · 6번)**

- 교수 세션 복구: `GET /sessions/active` 조회 + `POST /sessions/:id/professor-token` 재발급
- RAG 과목별 인덱스 격리 (`RAG_COURSE_INDEX_MAP`) — 다른 과목 강의자료가 검색에 섞이지 않음
- RAG 크리티컬 패스 지연 최적화 — 검색 캐시(LRU+TTL), 세마포어 동시성, 타임아웃 0.4초
- BME 교재 "핵심 용어" chunk 를 용어당 1개로 분해 (정의형 질의 검색 품질)
- 평가 하네스가 프로덕션 검색(전공+강의 인덱스 병합, 라우터 정규화)을 재현
- 대만어·우크라이나어 TTS 로케일, HTTPS 스테이징 환경

**Sehui 쪽에서 온 것 (4 · 5번)**

- 수업(과목) 선택 + 강의 자료(PDF) 업로드 UI
- 업로드 자료 자동 인덱싱: `rag:index:queue`(Redis) → `indexer_daemon` → 과목별
  `lecture_{courseId}` 인덱스 누적 → rag-service `/admin/reload` 즉시 반영
- 자막 DB 저장(`TranscriptModule`, `transcript_segments` 테이블) + 자막 이력(스크롤백) 조회 UI
- 학생 프로필 DB 연결(학생 회원 로그인, 출석 `session_attendances`)
- Dual STT: Azure ↔ OpenAI Realtime 교체 가능(`STT_PROVIDER`), STT 벤치마크 도구
- STT 세그멘테이션 튜닝, 전공 용어 lexicon 교정(`rag_assets/lexicon_*.json`)
- 워커 테스트 대폭 확충(재연결, 종료 타임아웃, 파이프라인, STT 등 141개)
- Redis Pub/Sub 재구독 루프, 워커 기동 실패 상태 기록, sequence 이어가기
- `/health/live`·`/health/ready` 헬스체크, Azure 유료 배포 문서

### 충돌 해결 결정과 근거

원칙: **RAG 검색 경로는 Yumin 우선, 강의 관리·STT·자막은 Sehui 우선.**
단, 상호 배타가 아닌 것은 결합했다.

| 영역 | 결정 | 근거 |
|------|------|------|
| `rag-experiment/src/runtime.py` | 양쪽 결합 | Yumin 의 격리(`RAG_COURSE_INDEX_MAP`)·캐시·세마포어를 유지하고, 그 위에 Sehui 의 동적 `lecture_{courseId}` 인덱스 로딩을 얹음. 동적 인덱스는 그 과목 자신의 업로드 자료라 격리 원칙을 깨지 않는다 |
| RAG 타임아웃 | Yumin 0.4초 (Sehui 는 5초) | RAG 는 자막·TTS 크리티컬 패스에 동기로 걸린다. fail-open 이라 타임아웃돼도 그 문장만 문맥 없이 번역될 뿐 파이프라인은 계속된다 |
| `ai-worker/.../rag.py` (`HttpRagClient`) | Sehui 구조 + Yumin 기본값 | 세그먼트마다 TLS 핸드셰이크를 반복하지 않는 영속 클라이언트, 연속 실패 카운터, 종료 시 "세션 내내 RAG 미동작" 진단은 Sehui 것이 우수. 타임아웃 기본값만 Yumin 의 0.4초 |
| `ai-worker/.../main.py` | Sehui 측 채택 | Sehui 브랜치가 Yumin 의 초기 워커 안정화가 이미 merge 된 지점에서 출발한 상위집합(재구독 루프, 자막 발행, lexicon, sequence 이어가기). HEAD 잔여는 구버전 중복이었다 |
| `session.service.ts` / `session.controller.ts` | 중복 제거 + 양쪽 유지 | 양쪽이 동일한 `findActive` 를 각자 구현 → 하나로 정리. Yumin 의 `professor-token` 엔드포인트는 유지 |
| `public/` 프론트엔드 | 대부분 Sehui + 일부 Yumin | 자료 업로드·자막 이력·학생 로그인·소리 켜기 오버레이는 Sehui. 복구 버튼 스타일은 Yumin 의 전용 `.recover-button`(시작 버튼과 시각적으로 구분) |
| `evaluate.py`, `ingest.py`, eval 질의 JSON, 교재 메타 JSON | Yumin | RAG 품질(6번) 담당 산출물이며 Sehui 쪽은 그 이전 버전 |
| `docker-compose.demo.yml`, `.env.demo.example` | 유니온 | Sehui 의 `rag-indexer-daemon` 서비스 + Yumin 의 RAG 튜닝 환경변수 모두 포함 |

### 병합 과정에서 추가로 수정한 것

병합 자체가 요구한 보강 3건:

- **reload 시 검색 캐시 무효화** (`runtime.py`) — 검색 캐시 키에 인덱스 이름은
  들어가지만 내용 버전은 안 들어간다. 자료 업로드 → 인덱스 갱신 직후에도 TTL(5분)
  동안 옛 결과가 나오는 것을 막기 위해 `reload_course_index()` 가 캐시를 비운다.
- **`load_index` 존재 확인을 faiss import 앞으로 이동** (`search.py`) — 아직 업로드
  자료가 없는 과목의 "인덱스 없음" 판정(동적 인덱스 폴백)에 faiss 설치가 필요하지
  않게 했다. faiss 없는 환경(테스트 포함)에서도 전공 인덱스 폴백이 동작한다.
- **`_search` 의 인덱스 조회를 `dict.get` 으로 방어** (`runtime.py`) — reload 가
  동시에 인덱스를 빼는 드문 경합에서 `KeyError` 대신 해당 인덱스만 건너뛴다.

정리성 수정:

- `app.module.ts` — 양쪽이 각자 추가한 `HealthModule` import 중복 제거
- `session.service.ts` — 동일 구현이던 `findActive` 중복 선언 제거

### 검증

- `nest build` 통과 (TypeScript 컴파일 에러 없음)
- 백엔드 Jest: 45/45 통과
- AI 워커 pytest: 141/141 통과
- rag-experiment pytest: 20/20 통과
- 충돌 마커 잔여 0건, `app.js` 참조 DOM id 전부 `index.html` 에 존재,
  NestJS ↔ indexer_daemon 의 `rag:index:queue` 계약 일치 확인

## Related Docs

- [AGENTS.md](/C:/UniVoice/prototype-Yumin/AGENTS.md)
- [CLAUDE.md](/C:/UniVoice/prototype-Yumin/CLAUDE.md)
- [docs/통합_결정.md](/C:/UniVoice/prototype-Yumin/docs/%ED%86%B5%ED%95%A9_%EA%B2%B0%EC%A0%95.md)
- [docs/UniVoice_CoreAPI_설계.md](/C:/UniVoice/prototype-Yumin/docs/UniVoice_CoreAPI_%EC%84%A4%EA%B3%84.md)