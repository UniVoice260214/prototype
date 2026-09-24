# AGENTS.md — UniVoice Core API Backend

## 서비스 개요
한국 대학 한국어 강의를 실시간으로 번역해 외국인 유학생에게
음성 + 자막으로 제공하는 시스템.
이 레포는 **NestJS 관리 서버(Control Plane)** 만 담당.
실시간 음성 처리는 별도 Python AI 워커가 담당하므로,
이 서버는 음성 프록시 역할을 하지 않음.

## 전체 시스템에서 이 서버의 위치
교수 웹/학생 앱 → LiveKit Room ← Python AI 워커
                         ↕
              [이 서버: NestJS Control Plane]
                    ↙    ↓    ↘
             PostgreSQL Redis  Azure Blob Storage

## 기술 스택
- Framework: NestJS (TypeScript)
- DB: PostgreSQL + TypeORM (migration 기반, `synchronize: false`)
- Cache / Event Bus: Redis (세션 상태, glossary prewarm, Pub/Sub 이벤트, TTL 자동 정리)
- File Storage: Azure Blob Storage (PDF/PPT 원본 + 전처리 결과)
- Auth: JWT (HS256, access token only; MVP 단계는 refresh token 미적용)
- Docs: Swagger 자동 생성 (`/docs`, Bearer auth 통합)
- Media: LiveKit Server SDK (room 생성 + token 발급만)
- Test: Jest (단위 + e2e)

## 도메인 모듈 목록
| 모듈 | 역할 |
|------|------|
| AuthModule | JWT 로그인/인증, Guard, 학생 JoinToken 발급 |
| UserModule | User CRUD (admin/professor 공통 인증 주체) |
| SchoolModule | 학교 CRUD |
| DepartmentModule | 학과 CRUD |
| CourseModule | 과목 CRUD |
| ProfessorModule | 교수 프로필 CRUD (User와 1:1) |
| StudentModule | 학생 CRUD (회원가입/조회) |
| SessionModule | 수업 시작/종료, LiveKit Room 생성, token 발급, 워커 트리거 |
| MaterialModule | PDF/PPT 업로드 → Blob 저장 → indexing 이벤트 발행 |
| GlossaryModule | 전공 용어 관리 (다국어 번역 포함), Redis prewarm |
| QrModule | 학생 입장 QR 생성 (JoinToken 임베드) |
| EventsModule | Redis Pub/Sub publisher (모든 외부 시스템 이벤트 발행 단일 진입점) |

## DB 스키마

> 모든 엔티티는 공통으로 `createdAt`, `updatedAt` 컬럼을 가짐 (TypeORM `@CreateDateColumn`, `@UpdateDateColumn`).
> 모든 FK는 별도 명시 없으면 `onDelete: RESTRICT`. 자세한 cascade 정책은 각 엔티티 주석에 표기.

- **User**: id, email(unique), passwordHash, name, role(`admin` | `professor`), createdAt, updatedAt
- **Professor**: id, userId(FK User, unique, 1:1), departmentId(FK), createdAt, updatedAt
- **Student**: id, email(unique), passwordHash, name, preferredLocale(nullable, e.g. `zh-CN`), createdAt, updatedAt
- **School**: id, name, createdAt, updatedAt
- **Department**: id, name, schoolId(FK), createdAt, updatedAt
- **Course**: id, name, departmentId(FK), professorId(FK Professor), createdAt, updatedAt
- **Session**: id, courseId(FK), liveKitRoomName(unique), status(`active` | `ended`, enum), targetLocales(`text[]`, 예: `['zh-CN','vi-VN','mn-MN']`), startedAt, endedAt(nullable), createdAt, updatedAt
- **Material**: id, sessionId(FK, nullable — 사전 업로드 가능), courseId(FK), blobUrl, originalFilename, sourceType(`lecture` | `major`, enum), week(nullable int), indexingStatus(`pending` | `processing` | `done` | `failed`, enum), createdAt, updatedAt
- **Glossary**: id, courseId(FK), term(한국어 원문), pronunciation(IPA/한글, nullable), definition(nullable), translations(`jsonb`, 예: `{ "zh-CN": "线粒体", "vi-VN": "Ty thể" }`), createdAt, updatedAt

## 인증 모델

### 로그인 주체
- **admin / professor**: `User` 엔티티 기반 email + password 로그인. JWT access token 발급.
- **student**: 두 가지 진입 경로
  - **회원 로그인**: `Student` 엔티티 기반 email + password 로그인. JWT access token 발급.
  - **QR 입장**: 회원 여부와 무관하게 QR 스캔 → 단기 JoinToken으로 세션 참여 (아래 QR 흐름 참조)

### JWT payload
```ts
// User token
{ sub: userId, role: 'admin' | 'professor', type: 'user' }
// Student token
{ sub: studentId, type: 'student' }
// Session JoinToken (QR)
{ sub: 'guest' | studentId, sessionId, type: 'session-join', exp: <24h> }
```

### Guard 정책
- `JwtAuthGuard`는 글로벌 적용. 공개 엔드포인트만 `@Public()` 데코레이터.
- 역할 검사는 `@Roles('admin' | 'professor' | 'student')` + `RolesGuard`.

## 주요 API
- POST   /auth/login                    → User(admin/professor) 로그인
- POST   /auth/student/login            → Student 로그인
- POST   /auth/student/signup           → Student 가입
- CRUD   /schools, /departments, /courses, /professors, /students
- POST   /sessions/start                → LiveKit Room 생성 + 교수 token 반환 + `sessions.started` 이벤트 발행
- POST   /sessions/:id/end              → 세션 종료 + `sessions.ended` 이벤트 발행
- POST   /sessions/:id/token            → 학생 LiveKit token 반환 (JoinToken 또는 Student JWT 필요)
- POST   /materials/upload              → Blob 업로드 후 `materials.indexing.requested` 이벤트 발행
- CRUD   /glossary
- GET    /qr/:sessionId                 → QR 이미지 반환 (JoinToken 임베드)

## 세션 시작 워크플로우
1. 교수가 `POST /sessions/start { courseId, targetLocales }` 호출
2. NestJS:
   1. `Session` 레코드 생성 (status=active, targetLocales 저장)
   2. LiveKit `RoomService.createRoom()`로 Room 생성
   3. **Redis prewarm**:
      - `session:{id}:config` ← `{ courseId, targetLocales, ... }`
      - `glossary:{courseId}` ← Glossary 전체 (translations 포함)
   4. **Redis Pub/Sub publish**: 채널 `sessions.started`, payload `{ sessionId, courseId, liveKitRoomName, targetLocales }`
   5. 교수용 LiveKit token 발급 후 응답
3. Python 워커가 `sessions.started` 구독 → Room 입장 → 음성 처리 시작

## QR / 학생 입장 흐름
1. `GET /qr/:sessionId` → NestJS가 단기 JoinToken(JWT, 24h) 생성, QR PNG에 URL 임베드 (`https://app.example.com/join?token=...`)
2. 학생 앱이 token으로 `POST /sessions/:id/token { locale }` 호출
3. NestJS가 JoinToken 검증 → 해당 sessionId, locale에 대한 LiveKit token 발급
4. 학생은 LiveKit token으로 Room 입장 → `tts.{locale}` 트랙 구독

## Redis 키 / 채널 표준

### Key namespace
| Key | Writer | Reader | TTL |
|-----|--------|--------|-----|
| `session:{id}:config` | NestJS (세션 시작) | Python 워커 | 세션 종료 시 삭제 또는 24h |
| `session:{id}:status` | NestJS | 모두 | 24h |
| `glossary:{courseId}` | NestJS (prewarm) | Python 워커 | 24h, 세션 종료 시 갱신 가능 |

### Pub/Sub 채널
| Channel | Publisher | Subscriber | Payload |
|---------|-----------|------------|---------|
| `sessions.started` | NestJS | Python 워커 | `{ sessionId, courseId, liveKitRoomName, targetLocales }` |
| `sessions.ended` | NestJS | Python 워커, RAG 워커 | `{ sessionId }` |
| `materials.indexing.requested` | NestJS | RAG 워커 | `{ materialId, blobUrl, sourceType, courseId, week? }` |
| `materials.indexing.completed` | RAG 워커 | NestJS (Material.indexingStatus 갱신) | `{ materialId, status, error? }` |

## 코딩 컨벤션

### 폴더 구조
```
src/
├── main.ts
├── app.module.ts
├── common/                  # 공용 데코레이터, 필터, 인터셉터, 가드, 파이프
│   ├── decorators/          # @Public, @Roles, @CurrentUser
│   ├── filters/             # GlobalExceptionFilter
│   └── guards/              # JwtAuthGuard, RolesGuard
├── config/                  # 환경변수 스키마, TypeORM/Redis/LiveKit 설정
├── modules/
│   └── <domain>/
│       ├── <domain>.module.ts
│       ├── <domain>.controller.ts
│       ├── <domain>.service.ts
│       ├── entities/
│       ├── dto/
│       └── tests/
├── infra/                   # 외부 시스템 클라이언트 (LiveKit, Azure Blob, Redis Pub/Sub)
└── migrations/              # TypeORM migration 파일
```

### 모듈 구조
- 기본: Module / Controller / Service / Entity / DTO
- 외부 시스템(LiveKit, Blob, Redis Pub/Sub)은 `infra/`에 어댑터로 분리 후 Service에서 주입

### 인증
- `JwtAuthGuard`를 글로벌 적용, 공개 엔드포인트는 `@Public()`
- 역할 검사는 `@Roles(...)` + `RolesGuard`

### 응답 / 에러 포맷
- 성공 응답: 컨트롤러는 데이터 객체 그대로 반환 (envelope 미사용)
- 에러 응답: `GlobalExceptionFilter`가 일관된 모양으로 변환
  ```json
  { "statusCode": 400, "error": "BAD_REQUEST", "message": "...", "path": "/sessions/start", "timestamp": "2026-05-23T..." }
  ```
- 도메인 에러는 NestJS `HttpException` 상속 클래스 사용

### 환경변수 (.env)
- `DATABASE_URL`
- `REDIS_URL`
- `AZURE_BLOB_CONNECTION_STRING`, `AZURE_BLOB_CONTAINER`
- `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_URL`
- `JWT_SECRET`, `JWT_EXPIRES_IN` (default 1d), `JWT_JOIN_TOKEN_EXPIRES_IN` (default 24h)
- `PORT` (default 3000)

### Migration
- `synchronize: false` 고정. 스키마 변경은 항상 migration 파일로.
- 명령: `npm run migration:generate -- <name>`, `npm run migration:run`

### 테스트
- 단위 테스트: `*.spec.ts` (서비스 로직 위주)
- e2e: `test/<domain>.e2e-spec.ts` (Supertest + 테스트 DB)
- 외부 시스템(LiveKit, Blob, Redis Pub/Sub)은 인터페이스 모킹

### Swagger
- 경로: `/docs`
- 모든 컨트롤러에 `@ApiTags`, DTO에 `@ApiProperty` 필수
- Bearer auth 글로벌 등록 (`addBearerAuth`)
