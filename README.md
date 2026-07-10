# UniVoice Core API Backend (통합본)

UniVoice 시스템의 NestJS Control Plane.
음성 처리는 별도 Python AI 워커가 담당하며, 이 서버는 다음만 책임진다.

- 인증 (admin / professor / student)
- 학교 · 학과 · 과목 · 교수 · 학생 CRUD
- 세션 시작/종료 + LiveKit Room 생성 + token 발급
- 강의자료 업로드 (Azure Blob) → 인덱싱 큐 적재 + 이벤트 발행
- Glossary CRUD + Redis prewarm
- QR(JoinToken) 생성

> **이 폴더는 세 팀원(서영/세희/유민) 구현을 기능별로 비교해 합친 통합본이다.**
> 베이스는 세희, 여기에 서영의 강점(인덱싱 내구성 큐 `rag:index:queue`, Redis 키 규약 중앙화)을 이식하고
> 교차검증에서 발견한 공통 결함(비밀번호 노출·인덱싱 완료 미수신·세션 보상 트랜잭션·Blob 누수)을 수정했다.
> 자세한 채택 근거는 **[docs/통합_결정.md](docs/통합_결정.md)** 참조.

설계 배경은 [CLAUDE.md](CLAUDE.md), 아키텍처 설계서는 [docs/UniVoice_CoreAPI_설계.pdf](docs/UniVoice_CoreAPI_설계.pdf) 참조.

## AI/RAG 워커 인터페이스 (다른 팀과 합의 필요)

| 종류 | 이름 | 용도 |
|------|------|------|
| Redis key | `session:{id}:config`, `session:{id}:status`, `glossary:{courseId}` | 세션/glossary prewarm (AI 워커가 읽음) |
| Pub/Sub | `sessions.started`, `sessions.ended` | 세션 시작/종료 (AI 워커 구독) |
| Redis List | `rag:index:queue` | 인덱싱 잡 큐 — RAG 워커가 `BRPOP`으로 소비 (유실 없음) |
| Pub/Sub | `materials.indexing.requested` / `.completed` | 인덱싱 요청(라이브)/완료 보고 |

정의 위치: `src/common/redis-keys.ts`, `src/modules/events/events.types.ts`

## AI 워커 (실시간 번역 파이프라인) — `ai-worker/`

위 인터페이스를 소비하는 Python AI 워커가 [ai-worker/](ai-worker/README.md)에 있다.
`sessions.started` 구독 → glossary 주입 → LiveKit Room 입장 → **STT → 문장분리 → (RAG) → 번역 → TTS → locale별 track publish + 자막 DataChannel** 전 구간을 담당한다.
**RAG만 교체 가능한 인터페이스(`RagClient`, 기본 NoOp)로 비워 두었고 나머지는 조립하면 동작**한다. RAG 구현·주입 방법은 해당 README의 "RAG 붙이기" 절 참조.
새로 필요한 키: `AZURE_SPEECH_*`(STT+TTS), `OPENAI_API_KEY`(번역). LiveKit·Redis는 Core API와 공유.

## 요구사항
- Node.js 20+
- PostgreSQL 13+
- Redis 6+
- Azure Blob Storage 계정
- LiveKit (Cloud 또는 self-hosted)

## 빠른 시작
```bash
# 1. 의존성 설치
npm install

# 2. 환경변수 설정
cp .env.example .env
#   DATABASE_URL, REDIS_URL, JWT_SECRET, LIVEKIT_*, AZURE_BLOB_* 채우기

# 3. DB 마이그레이션 실행
npm run migration:run

# 4. 개발 서버 실행
npm run start:dev
```

- API: http://localhost:3000
- Swagger UI: http://localhost:3000/docs

## 스크립트
| 명령 | 설명 |
|------|------|
| `npm run start:dev` | watch 모드 개발 서버 |
| `npm run build` | TypeScript 컴파일 → `dist/` |
| `npm run start:prod` | 프로덕션 실행 (`dist/main.js`) |
| `npm run migration:run` | 대기 중 마이그레이션 실행 |
| `npm run migration:generate -- src/migrations/<Name>` | Entity 변경분으로 마이그레이션 생성 |
| `npm run migration:revert` | 직전 마이그레이션 롤백 |
| `npm test` | 단위 테스트 |
| `npm run test:e2e` | e2e 테스트 |
| `npm run lint` | ESLint 자동 수정 |

## 폴더 구조
```
src/
├── main.ts
├── app.module.ts
├── common/           # 데코레이터, 가드, 필터
├── config/           # env 검증, TypeORM datasource
├── infra/            # LiveKit, Azure Blob, Redis 클라이언트
├── modules/          # 도메인 모듈 (CLAUDE.md 참조)
└── migrations/       # TypeORM SQL 마이그레이션
```
