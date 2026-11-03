# UniVoice

**유학생을 위한 전공 특화 실시간 강의 통역 서비스**

[홈페이지](https://univoice260214.github.io/) · [시연 영상](https://youtu.be/UnD_QKKkiKM)

![UniVoice 교수자 화면과 학생 화면](https://univoice260214.github.io/assets/img/hero.webp)

## 핵심 기능

| | 기능 | 설명 |
|---|---|---|
| 01 | 실시간 자막 · 음성 | 교수자의 강의를 실시간으로 인식·번역해 학생의 언어로 자막과 음성을 동시에 제공합니다. |
| 02 | 전공 문맥 보정 | 강의자료와 전공 용어를 검색해 발화의 문맥을 파악하고 번역을 보정합니다. |
| 03 | 강의 기록 · 복습 | 실시간으로 생성된 번역 자막을 강의 기록으로 저장합니다. |
| 04 | 다국어 지원 | 하나의 교수자 음성을 여러 언어로 동시에 번역해 학생별 선택 언어로 제공합니다. |

## 화면

| 학생 수업 화면 | 학생 홈 |
|---|---|
| ![학생 수업 화면](https://univoice260214.github.io/assets/img/ui-student-live.webp) | ![학생 홈](https://univoice260214.github.io/assets/img/ui-student-home.webp) |
| 강의자료 옆에 번역 자막과 한국어 원문이 함께 표시됩니다. | QR로 입장하고 번역 언어를 고릅니다. |

| 교수자 수업 준비 | 교수자 수업 진행 |
|---|---|
| <img src="https://univoice260214.github.io/assets/img/ui-prof-setup.webp" width="260" alt="교수자 수업 준비"> | <img src="https://univoice260214.github.io/assets/img/ui-prof-live.webp" width="260" alt="교수자 수업 진행"> |
| 과목과 번역 언어를 고르고 강의자료를 올립니다. | 휴대폰 마이크로 수업하며 인식된 원문을 확인합니다. |

## 아키텍처

![UniVoice 아키텍처](https://univoice260214.github.io/assets/img/architecture.svg)

---

# 개발자 문서

이 저장소는 UniVoice를 구성하는 **세 개의 실행 단위**를 한 레포에 담고 있습니다.
아래 문서는 개발 환경 구성부터 실행·테스트·배포까지의 실제 절차를 다룹니다.

## 목차

- [시스템 구성](#시스템-구성)
- [기술 스택](#기술-스택)
- [저장소 구조](#저장소-구조)
- [빠른 시작 (로컬 실행)](#빠른-시작-로컬-실행)
- [Docker 데모 실행](#docker-데모-실행)
- [RAG 인덱스 빌드](#rag-인덱스-빌드-선택)
- [환경 변수](#환경-변수)
- [API 개요](#api-개요)
- [데이터 모델](#데이터-모델)
- [서비스 간 통신 계약 (Redis)](#서비스-간-통신-계약-redis)
- [세션 라이프사이클](#세션-라이프사이클)
- [DB 마이그레이션](#db-마이그레이션)
- [테스트](#테스트)
- [npm 스크립트](#npm-스크립트)
- [상세 문서](#상세-문서)
- [트러블슈팅](#트러블슈팅)

---

## 시스템 구성

UniVoice는 **제어 평면(Control Plane)과 미디어 평면(Media Plane)을 분리**한 구조입니다.
NestJS 서버는 음성 데이터를 중계하지 않습니다. 음성은 LiveKit Room 안에서만 흐르고,
NestJS는 세션·권한·메타데이터만 관리합니다.

```text
  ┌──────────────┐        ┌──────────────┐
  │ 교수 웹(모바일) │        │  학생 웹/앱   │
  └───────┬──────┘        └───────┬──────┘
          │  mic track             │ tts.{locale} track + DataChannel
          └────────┬───────────────┘
                   ▼
            ┌─────────────┐        ┌──────────────────────┐
            │ LiveKit Room │◀──────▶│  AI Worker (Python)  │
            └─────────────┘        │  STT → 분절 → RAG     │
                   ▲               │  → 번역 → TTS         │
                   │ token/room    └──────────┬───────────┘
                   │                          │ HTTP /retrieve
     ┌─────────────┴──────────────┐  ┌────────▼──────────┐
     │  Core API (NestJS)         │  │ RAG Service        │
     │  세션·권한·자료·용어·자막이력  │  │ (FastAPI + FAISS)  │
     └──┬──────────┬──────────┬───┘  └───────────────────┘
        │          │          │
   PostgreSQL    Redis    Azure Blob
   (영속 데이터) (상태/이벤트)  (강의자료 원본)
```

| 실행 단위 | 디렉터리 | 런타임 | 역할 |
|---|---|---|---|
| **Core API** | `src/` (레포 루트) | Node.js 20 / NestJS | 인증, 세션 생성, LiveKit 토큰 발급, 강의자료 업로드, 용어집, 자막 이력 저장, 교수/학생 웹 정적 서빙 |
| **AI Worker** | `ai-worker/` | Python 3.12 | LiveKit Room 입장, Azure STT, 발화 분절, 번역, Azure TTS, locale별 오디오 트랙 발행 |
| **RAG Service** | `rag-experiment/` | Python 3.12 / FastAPI | 전공 교재·강의자료 FAISS 인덱스 검색, 번역 직전 문맥 주입 (`POST /retrieve`) |

세 단위는 **직접 호출하지 않고 Redis Pub/Sub으로 느슨하게 연결**됩니다
(자세한 계약은 [서비스 간 통신 계약](#서비스-간-통신-계약-redis) 참조).

---

## 기술 스택

### Core API (NestJS)

| 영역 | 선택 | 비고 |
|---|---|---|
| Framework | NestJS 11 (TypeScript 5.7) | 모듈 기반 DI |
| DB | PostgreSQL 16 + TypeORM 0.3 | `synchronize: false` 고정, 스키마 변경은 migration으로만 |
| Cache / Event Bus | Redis 7 (ioredis) | 세션 상태, glossary prewarm, Pub/Sub |
| File Storage | Azure Blob Storage | 로컬은 Azurite 에뮬레이터 |
| Auth | JWT (HS256, access token only) | MVP 단계에서 refresh token 미적용 |
| Media | LiveKit Server SDK | Room 생성 + 토큰 발급만 담당 |
| API Docs | Swagger (`/docs`) | Bearer auth 통합 |
| Test | Jest (단위 + e2e/Supertest) | |

### AI Worker (Python)

| 영역 | 선택 |
|---|---|
| STT | Azure Speech (기본) / OpenAI Realtime `gpt-4o-transcribe` (`STT_PROVIDER`로 전환) |
| 번역 | OpenAI `gpt-4o-mini` 또는 Azure OpenAI (`TRANSLATE_PROVIDER`로 전환) |
| TTS | Azure Speech Neural Voice (locale별 음성 맵) |
| Media | LiveKit Python SDK |
| Test | pytest (외부 의존성은 전부 fake로 대체) |

### RAG Service (Python)

| 영역 | 선택 |
|---|---|
| 임베딩 | `nlpai-lab/KURE-v1` (한국어 특화, 비교 대상: bge-m3 / OpenAI text-embedding-3-large) |
| 벡터 검색 | FAISS (전공별 인덱스 + 과목별 강의자료 인덱스) |
| 서빙 | FastAPI + uvicorn |

> 임베딩 모델 선정 근거와 검색 품질 평가 수치는 [`rag-experiment/REPORT.md`](rag-experiment/REPORT.md)에 정리되어 있습니다.

---

## 저장소 구조

```text
prototype/
├── src/                          # ── Core API (NestJS) ──────────────────
│   ├── main.ts                   # 부트스트랩: 정적 서빙, Swagger, CORS, ValidationPipe
│   ├── app.module.ts             # 루트 모듈
│   ├── common/                   # 공용 데코레이터·가드·필터·유틸
│   │   ├── access/               # CourseAccessService, StudentSessionAccessService (권한 판정)
│   │   ├── decorators/           # @Public, @Roles, @CurrentUser
│   │   ├── filters/              # GlobalExceptionFilter (에러 응답 표준화)
│   │   ├── guards/               # JwtAuthGuard(글로벌), RolesGuard
│   │   ├── redis-keys.ts         # Redis 키 네임스페이스 상수 (워커와의 계약)
│   │   └── supported-locales.ts  # 지원 번역 언어 화이트리스트
│   ├── config/                   # 환경변수 검증(env.validation), TypeORM DataSource
│   ├── infra/                    # 외부 시스템 어댑터 (서비스는 여기에만 의존)
│   │   ├── blob/                 # Azure Blob 업로드/SAS
│   │   ├── livekit/              # Room 생성, access token 발급
│   │   └── redis/                # ioredis 클라이언트 provider
│   ├── modules/                  # 도메인 모듈 (module/controller/service/entity/dto)
│   │   ├── auth/                 # 로그인, JWT 전략, 학생 가입
│   │   ├── user/ professor/ student/
│   │   ├── school/ department/ course/
│   │   ├── session/              # 수업 시작·종료, LiveKit 토큰, 출석(SessionAttendance)
│   │   ├── transcript/           # 자막 저장(subscriber) + 이력 조회 API
│   │   ├── material/             # PDF/PPT 업로드, 미리보기 생성, 인덱싱 상태 수신
│   │   ├── glossary/             # 전공 용어집 + Redis prewarm
│   │   ├── qr/                   # 학생 입장 QR (JoinToken 임베드)
│   │   ├── events/               # Redis Pub/Sub publisher (외부 이벤트 단일 진입점)
│   │   ├── health/               # /health/live, /health/ready
│   │   └── web/                  # /professor, /student, /join → SPA 서빙
│   ├── migrations/               # TypeORM 마이그레이션 (5개)
│   └── scripts/                  # seed.ts (최초 admin 생성), smoke.ts
│
├── ai-worker/                    # ── AI Worker (Python) ─────────────────
│   ├── univoice_worker/
│   │   ├── main.py               # Redis Pub/Sub 진입점 + 활성 세션 복구
│   │   ├── session_worker.py     # LiveKit Room 생명주기, 교수 트랙 attach/detach
│   │   ├── stt.py / stt_openai.py# Azure 스트리밍 STT / OpenAI Realtime 전사
│   │   ├── segmenter.py          # STT final 텍스트를 발화 단위로 분절
│   │   ├── pipeline.py           # 세그먼트 큐 → 번역 → caption 이벤트 → TTS enqueue
│   │   ├── rag.py                # RAG Service HTTP 클라이언트 (fail-open)
│   │   ├── translator.py         # OpenAI / Azure OpenAI 번역
│   │   ├── tts.py / tts_queue.py # Azure TTS + locale별 bounded 큐
│   │   ├── audio_publisher.py    # tts.{locale} 오디오 트랙 발행
│   │   ├── glossary.py lexicon.py dedupe.py latency.py worker_status.py
│   │   └── config.py models.py evaluation.py
│   ├── rag_assets/               # lexicon_{ai,hss,bme}.json (STT 전공 용어 교정 자산)
│   ├── tools/                    # 개발용 CLI (아래 "개발 도구" 참조)
│   ├── bench_data/               # STT 벤치마크용 샘플 음성·전사
│   ├── tests/                    # pytest (외부 의존성 fake)
│   └── README.md                 # 워커 상세 문서 (파이프라인 보장 조건, 수동 E2E 체크리스트)
│
├── rag-experiment/               # ── RAG Service & 실험 ──────────────────
│   ├── src/
│   │   ├── server.py             # FastAPI: /retrieve, /admin/reload, /health/{live,ready}
│   │   ├── runtime.py            # 인덱스 로딩, score gate, 전공 라우팅 런타임
│   │   ├── ingest.py             # PDF → 청킹 (교재 장/절 구조 인식)
│   │   ├── embed.py search.py    # 임베딩 생성 / FAISS 검색
│   │   ├── router.py             # 전공(ai/hss/bme) 자동 판별
│   │   ├── build_demo_indexes.py # 데모용 인덱스 일괄 빌드 (1회 실행)
│   │   ├── indexer_daemon.py     # 업로드 큐 소비 → 강의자료 인덱싱
│   │   └── evaluate*.py benchmark.py
│   ├── data/raw/                 # 전공별 교재·강의안 PDF (ai / HSS / BME)
│   ├── eval/                     # 평가 질의셋 + 결과 리포트 (results_*.md)
│   ├── tools/                    # 교재 본문 빌드 스크립트
│   └── REPORT.md                 # 임베딩 모델 선정 실험 보고서
│
├── public/                       # 교수/학생 웹 클라이언트 (바닐라 JS SPA)
│   ├── index.html app.js styles.css logo.svg
│
├── docs/                         # 설계·배포·측정 문서 (아래 "상세 문서" 참조)
├── deploy/Caddyfile              # 스테이징 리버스 프록시 (HTTPS 종단)
├── scripts/                      # 환경변수 검증 · 웹 프리뷰 (Node 스크립트)
├── test/jest-e2e.json            # e2e 테스트 설정
│
├── docker-compose.yml            # 로컬 인프라 (postgres / redis / azurite)
├── docker-compose.demo.yml       # 전체 스택 데모 (app + worker + rag + 인프라)
├── docker-compose.staging.yml    # 스테이징 (Caddy HTTPS 포함)
├── Dockerfile                    # Core API 멀티스테이지 빌드
├── start-all.ps1 / stop-all.ps1  # Windows 로컬 통합 실행/종료 스크립트
├── .env.example                  # Core API 환경변수 템플릿
└── CLAUDE.md / AGENTS.md         # 코딩 컨벤션·도메인 규칙 (AI 코딩 에이전트용)
```

---

## 빠른 시작 (로컬 실행)

### 사전 요구사항

| 도구 | 버전 | 용도 |
|---|---|---|
| Node.js | 20.x 이상 | Core API |
| Python | 3.12 | AI Worker, RAG Service |
| Docker Desktop | 최신 | PostgreSQL / Redis / Azurite |
| (선택) Azure Speech 키 | — | STT·TTS. 없으면 실시간 음성 기능 비활성 |
| (선택) LiveKit Cloud 프로젝트 | — | 무료 티어 가능 |
| (선택) OpenAI API 키 | — | 번역 |

### 1. 저장소 클론 및 의존성 설치

```bash
git clone https://github.com/UniVoice260214/prototype.git
cd prototype

# Core API
npm ci
```

### 2. 환경 변수 파일 생성

```bash
# Core API
cp .env.example .env

# AI Worker
cp ai-worker/.env.example ai-worker/.env
```

`.env`에서 최소한 아래 값을 채웁니다. (전체 목록은 [환경 변수](#환경-변수) 참조)

```ini
LIVEKIT_URL=wss://<your-project>.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
JWT_SECRET=<임의의 긴 문자열>
```

`ai-worker/.env`에는 다음을 채웁니다.

```ini
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=koreacentral
OPENAI_API_KEY=...          # TRANSLATE_PROVIDER=openai 일 때
LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET  # Core API 와 동일 값
```

> **인증 없이 UI만 확인하려면** `.env`에 `AUTH_DISABLED=true`를 설정하면 토큰 없이 API를 호출할 수 있습니다. **운영에서는 반드시 `false`로 두세요.**

### 3. 인프라 컨테이너 기동

```bash
docker compose up -d postgres redis azurite
```

| 서비스 | 포트 | 비고 |
|---|---|---|
| PostgreSQL | 5432 | `postgres / postgres / univoice` |
| Redis | 6379 | 비밀번호 없음 |
| Azurite (Blob) | 10000 | Azure Blob 로컬 에뮬레이터 |

### 4. 스키마 마이그레이션 + 초기 관리자 계정 생성

```bash
npm run migration:run
npm run seed
```

`seed`는 `admin@univoice.local / Admin1234!` 계정을 만듭니다
(환경변수 `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, `SEED_ADMIN_NAME`으로 변경 가능).
이미 존재하면 덮어쓰지 않고 종료합니다.

### 5. AI Worker 가상환경 준비

```bash
cd ai-worker
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt
cd ..
```

### 6. 실행

#### Windows — 통합 스크립트 (권장)

```powershell
.\start-all.ps1            # 인프라 + RAG 서비스 + AI 워커 + 백엔드를 한 번에
.\start-all.ps1 -NoWorker  # 백엔드만 (UI·업로드만 확인할 때)
.\stop-all.ps1             # 전체 종료
```

`start-all.ps1`은 다음을 순서대로 수행합니다.

1. `docker compose up -d postgres redis azurite`
2. `ai-worker/.env`의 `RAG_ENABLED=true`이고 `RAG_URL`이 로컬 주소일 때만 RAG 서비스를 새 창에서 기동
3. 이전 실행에서 남은 워커 프로세스를 정리한 뒤 AI 워커를 새 창에서 기동
4. 현재 창에서 `npm run start:dev`

#### macOS / Linux — 터미널 3개로 수동 실행

```bash
# 터미널 1 — Core API
npm run start:dev

# 터미널 2 — AI Worker
cd ai-worker && source .venv/bin/activate
python -m univoice_worker.main

# 터미널 3 — RAG Service (RAG_ENABLED=true 로 쓸 때만)
cd rag-experiment && source .venv/bin/activate
uvicorn server:app --app-dir src --host 127.0.0.1 --port 8000
```

### 7. 접속 확인

| 화면 | URL |
|---|---|
| 교수자 | http://localhost:3000/professor |
| 학생 (QR 입장) | http://localhost:3000/join |
| 학생 홈 | http://localhost:3000/student |
| Swagger API 문서 | http://localhost:3000/docs |
| 헬스체크 | http://localhost:3000/health/ready |

`GET /health/ready`가 `{"status":"ok","checks":{"database":"up","redis":"up"}}`를 반환하면
DB·Redis 연결이 정상입니다.

---

## Docker 데모 실행

전체 스택(Core API + AI Worker + RAG Service + 인프라)을 컨테이너로 한 번에 띄웁니다.
첫 실행은 KURE-v1 모델 다운로드와 인덱싱 때문에 시간이 걸리며, 모델·인덱스는
named volume에 보존되어 다음 실행부터 재사용됩니다.

```bash
cp .env.demo.example .env.demo
# .env.demo 의 비밀번호·API 키를 채운 뒤

npm run demo:validate    # 필수 환경변수 누락 검사
npm run demo:up          # docker compose -f docker-compose.demo.yml up -d --build
npm run demo:down        # 종료
```

정상 상태:

| 서비스 | 기대 상태 |
|---|---|
| `postgres`, `redis`, `azurite`, `app`, `rag-service` | `healthy` |
| `migrate`, `seed`, `rag-indexer` | `Exited (0)` |
| `ai-worker`, `rag-indexer-daemon` | `running` |

RAG 서비스는 보안상 `127.0.0.1:8000`에만 바인딩됩니다.

자세한 절차는 [`docs/rag-demo.md`](docs/rag-demo.md), 스테이징 HTTPS 배포는
[`docs/staging-deployment.md`](docs/staging-deployment.md)를 참고하세요.

---

## RAG 인덱스 빌드 (선택)

RAG는 **기본 off**입니다. 켜려면 아래 세 가지가 모두 필요합니다.

1. 인덱스 빌드 (최초 1회, KURE-v1 모델 다운로드 포함)
2. RAG 서비스 실행
3. `ai-worker/.env`에서 `RAG_ENABLED=true`

```bash
cd rag-experiment
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-runtime.txt

python src/build_demo_indexes.py                     # 인덱스 빌드 (1회)
uvicorn server:app --app-dir src --host 127.0.0.1 --port 8000
```

동작 확인:

```bash
curl http://127.0.0.1:8000/health/ready

curl -X POST http://127.0.0.1:8000/retrieve \
  -H 'Content-Type: application/json; charset=utf-8' \
  -d '{"sentence":"그 피시알 그거 몇 단계라 했죠","major":"auto","glossaryHits":[],"courseId":"manual-demo"}'
```

응답의 `useRag`, `major`, `matchedTerms`, `topScore`, `context`를 확인합니다.
관련 없는 문장은 `useRag=false`, `reason=NO_TRIGGER`로 돌아옵니다.

> RAG는 **fail-open**입니다. 서비스가 꺼져 있거나 타임아웃이 나도 번역은 문맥 없이 계속 진행됩니다.
> 실제 적용 여부는 교수 화면 상태줄(`RAG 연결 안 됨` / `RAG 인덱스 없음`)과 워커 로그의 `RAG ON/OFF`로 확인하세요.

---

## 환경 변수

### Core API (`.env`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PORT` / `HOST` | `3000` / `0.0.0.0` | 리슨 주소 |
| `NODE_ENV` | `development` | `production`이면 Swagger 기본 비활성 |
| `DATABASE_URL` | — | PostgreSQL 접속 문자열 |
| `REDIS_URL` | — | Redis 접속 문자열 |
| `JWT_SECRET` | — | **운영에서 반드시 교체** |
| `JWT_EXPIRES_IN` | `1d` | access token 수명 |
| `JWT_JOIN_TOKEN_EXPIRES_IN` | `24h` | QR JoinToken 수명 |
| `AUTH_DISABLED` | `false` | `true`면 인증·역할 검사를 전부 건너뜀 (개발 전용) |
| `CORS_ORIGINS` | — | 쉼표 구분. 미설정 시 development에서만 전체 허용 |
| `TRUST_PROXY` | `false` | 리버스 프록시 뒤에 둘 때 `true` |
| `SWAGGER_ENABLED` | `true` | `/docs` 노출 여부 |
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | — | LiveKit 서버 자격증명 |
| `LIVEKIT_TOKEN_TTL_SEC` | `14400` | 발급 토큰 수명 |
| `AZURE_BLOB_CONNECTION_STRING` / `AZURE_BLOB_CONTAINER` | — | 강의자료 저장소 |
| `QR_BASE_URL` | — | QR에 임베드할 학생 입장 URL |
| `RAG_INDEX_QUEUE` | `rag:index:queue` | 자료 업로드 시 인덱싱 잡을 넣는 Redis List |
| `WORKER_STOP_TIMEOUT_SEC` | `8` | 세션 종료 시 워커 정지 대기 상한 |
| `WORKER_STOP_POLL_INTERVAL_MS` | `200` | 워커 상태 폴링 간격 |

환경변수는 부팅 시 `src/config/env.validation.ts`에서 검증되며, 필수값이 비면 서버가 뜨지 않습니다.

### AI Worker (`ai-worker/.env`)

주요 그룹만 정리합니다. 각 값의 선정 이유는 `ai-worker/.env.example`의 주석에 상세히 적혀 있습니다.

| 그룹 | 변수 |
|---|---|
| 연결 | `REDIS_URL`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` |
| STT | `STT_PROVIDER`(`azure`\|`openai`), `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `STT_LANGUAGE`, `STT_OPENAI_*` |
| STT 튜닝 | `STT_SEGMENTATION_SILENCE_MS`(800), `STT_SEGMENTATION_MAX_TIME_MS`, `STT_INITIAL_SILENCE_MS`, `STT_TRUE_TEXT`, `STT_PROFANITY_RAW`, `STT_PHRASE_LIST_*` |
| 번역 | `TRANSLATE_PROVIDER`(`openai`\|`azure`), `OPENAI_API_KEY`, `OPENAI_MODEL`, `AZURE_OPENAI_*`, `TRANSLATE_TIMEOUT_SEC` |
| RAG | `RAG_ENABLED`, `RAG_URL`, `RAG_DEFAULT_MAJOR`, `RAG_COURSE_MAJOR_MAP`, `RAG_TIMEOUT_SEC`, `RAG_ASSETS_DIR` |
| 분절 | `SEGMENT_MAX_CHARS`(60), `SEGMENT_IDLE_FLUSH_MS`, `SEGMENT_SPLIT_KOREAN_ENDINGS`, `SEGMENT_QUEUE_MAX_SIZE` |
| TTS | `TTS_TIMEOUT_SEC`, `TTS_MAX_RETRIES`, `TTS_MAX_CONCURRENCY`, `TTS_QUEUE_MAX_SIZE`, `TTS_DEDUPE_TTL_SEC`, `TTS_VOICE_MAP` |
| 종료 | `SESSION_STOP_TIMEOUT_SEC`, `PIPELINE_FLUSH_TIMEOUT_SEC`, `TTS_FLUSH_TIMEOUT_SEC`, `WORKER_STATUS_TTL_SEC` |
| 계측 | `LATENCY_LOG_PATH` (기본 off) |

> 튜닝 기본값은 Azure 기본값이 아니라 **한국어 강의 발화 기준으로 조정한 값**입니다.
> 예: `STT_SEGMENTATION_SILENCE_MS=800`은 조사 뒤 휴지를 문장 끝으로 오인해 절 중간을 자르는 문제를 막기 위한 값입니다.

---

## API 개요

전체 스펙과 요청/응답 스키마는 서버 기동 후 **Swagger UI (`/docs`)** 에서 확인할 수 있습니다.

### 인증 (`@Public`)

| Method | Path | 설명 |
|---|---|---|
| POST | `/auth/login` | 관리자/교수 로그인 → JWT |
| POST | `/auth/student/login` | 학생 로그인 → JWT |
| POST | `/auth/student/signup` | 학생 가입 |

### 마스터 데이터

| 리소스 | 엔드포인트 | 권한 |
|---|---|---|
| 사용자 | `POST/GET /users`, `GET/DELETE /users/:userId` | `admin` |
| 학교 | `POST/GET /schools`, `GET/PATCH/DELETE /schools/:schoolId` | `admin`, `professor` |
| 학과 | `POST/GET /departments`, `GET/PATCH/DELETE /departments/:departmentId` | `admin`, `professor` |
| 과목 | `POST/GET /courses`, `GET/PATCH /courses/:courseId`, `DELETE`(admin) | `admin`, `professor` |
| 교수 | `POST/GET /professors`, `GET/PATCH/DELETE /professors/:professorId` | `admin`, `professor` |
| 학생 | `GET /students`, `GET/PATCH/DELETE /students/:studentId` | `admin` (+본인) |
| 학생 본인 수업 | `GET /students/me/sessions` | `student` |
| 용어집 | `POST/GET /glossary`, `GET/PATCH/DELETE /glossary/:glossaryId` | `admin`, `professor` |

### 수업 세션

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| POST | `/sessions/start` | `professor`, `admin` | Session 생성 + LiveKit Room 생성 + 교수 토큰 반환 + `sessions.started` 발행 |
| GET | `/sessions` | `admin`, `professor` | 세션 목록 |
| GET | `/sessions/active` | `admin`, `professor` | 진행 중인 세션 조회 |
| GET | `/sessions/:sessionId` | `admin`, `professor` | 세션 상세 |
| GET | `/sessions/:sessionId/status` | `admin`, `professor` | 세션·워커 상태 (교수 화면 폴링용) |
| GET | `/sessions/:sessionId/public` | `@Public` | 학생 입장 전 노출용 최소 정보 |
| POST | `/sessions/:sessionId/end` | `professor`, `admin` | 세션 종료 + `sessions.ended` 발행 + 워커 정지 대기 후 Room 삭제 |
| POST | `/sessions/:sessionId/token` | `@Public` | 학생 LiveKit 토큰 발급 (JoinToken 또는 Student JWT 필요) |
| POST | `/sessions/:sessionId/professor-token` | `professor`, `admin` | 교수 LiveKit 토큰 재발급 |

### 자막 이력

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| GET | `/sessions/:sessionId/transcripts` | `admin`, `professor` | 자막 이력 조회 (`afterSequence`, `limit`) |
| POST | `/sessions/:sessionId/transcripts/query` | `@Public` | 학생용 조회 (Student JWT 또는 body의 joinToken) |

### 강의자료 · QR · 헬스

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| POST | `/materials/upload` | `admin`, `professor` | Blob 업로드 후 `materials.indexing.requested` 발행 |
| GET | `/materials`, `/materials/:materialId` | `admin`, `professor` | 자료 목록·상세 |
| DELETE | `/materials/:materialId` | `admin`, `professor` | 자료 삭제 |
| POST | `/sessions/:sessionId/materials/query` | `@Public` | 학생용 자료 목록 (JoinToken) |
| POST | `/sessions/:sessionId/materials/:materialId/file` | `@Public` | 학생용 자료 파일 스트리밍 |
| GET | `/qr/:sessionId` | `admin`, `professor` | JoinToken이 임베드된 QR PNG |
| GET | `/health/live` | `@Public` | 프로세스 liveness |
| GET | `/health/ready` | `@Public` | DB·Redis readiness |

> 학생 쪽 조회가 `GET`이 아니라 `POST .../query`인 이유: QR JoinToken을 URL 쿼리스트링이 아닌 **body로** 받기 위해서입니다 (서버 로그·Referer 유출 방지).

### 인증 모델

```ts
// 관리자/교수 토큰
{ sub: userId, role: 'admin' | 'professor', type: 'user' }
// 학생 토큰
{ sub: studentId, type: 'student' }
// QR JoinToken (단기)
{ sub: 'guest' | studentId, sessionId, type: 'session-join', exp: <24h> }
```

- `JwtAuthGuard`가 **글로벌로 적용**되며, 공개 엔드포인트만 `@Public()`을 답니다.
- 역할 검사는 `@Roles('admin' | 'professor' | 'student')` + `RolesGuard`.

### 에러 응답 형식

성공 응답은 envelope 없이 데이터 객체를 그대로 반환하고, 에러만 `GlobalExceptionFilter`가 통일합니다.

```json
{
  "statusCode": 400,
  "error": "BAD_REQUEST",
  "message": "...",
  "path": "/sessions/start",
  "timestamp": "2026-05-23T00:00:00.000Z"
}
```

---

## 데이터 모델

모든 엔티티는 `createdAt`, `updatedAt`을 공통으로 가지며, 별도 명시가 없는 FK는 `onDelete: RESTRICT`입니다.

| 엔티티 | 주요 컬럼 |
|---|---|
| **User** | `email`(unique), `passwordHash`, `name`, `role`(`admin`\|`professor`) |
| **Professor** | `userId`(FK User, 1:1), `departmentId`(FK) |
| **Student** | `email`(unique), `passwordHash`, `name`, `preferredLocale`(nullable) |
| **School** | `name` |
| **Department** | `name`, `schoolId`(FK) |
| **Course** | `name`, `departmentId`(FK), `professorId`(FK), `major`(nullable: `ai`\|`hss`\|`bme`) |
| **Session** | `courseId`(FK), `liveKitRoomName`(unique), `status`(`active`\|`ended`), `targetLocales`(`text[]`), `startedAt`, `endedAt` |
| **SessionAttendance** | 세션별 학생 참여 기록 |
| **Material** | `sessionId`(nullable, 사전 업로드 허용), `courseId`(FK), `blobUrl`, `originalFilename`, `sourceType`(`lecture`\|`major`), `week`, `indexingStatus`(`pending`\|`processing`\|`done`\|`failed`) |
| **Glossary** | `courseId`(FK), `term`, `pronunciation`, `definition`, `translations`(jsonb: `{"zh-CN":"线粒体"}`) |
| **TranscriptSegment** | `sessionId`(FK, CASCADE), `segmentId`(unique, `{sessionId}-seg-{seq}`), `sequence`, `textKo`, `rawTextKo`, `sttConfidence`, `translations`(jsonb: locale → `{text, isFallback}`) |

`Course.major`는 수업 시작 시 워커로 전달되어 **해당 전공의 RAG 인덱스와 STT lexicon만** 사용하게 합니다. `null`이면 워커 설정값으로 폴백합니다.

---

## 서비스 간 통신 계약 (Redis)

세 실행 단위는 서로를 직접 호출하지 않습니다. 이 표가 사실상의 인터페이스 명세입니다.

### 키 네임스페이스

| Key | Writer | Reader | TTL |
|---|---|---|---|
| `session:{id}:config` | Core API (세션 시작) | AI Worker | 세션 종료 시 삭제 또는 24h |
| `session:{id}:status` | Core API | 모두 | 24h |
| `session:{id}:worker:status` | AI Worker | Core API | `WORKER_STATUS_TTL_SEC` |
| `glossary:{courseId}` | Core API (prewarm) | AI Worker | 24h |

워커 상태값: `starting` → `ready` → `stopping` → `stopped` (실패 시 `failed`)

### Pub/Sub 채널

| Channel | Publisher | Subscriber | Payload |
|---|---|---|---|
| `sessions.started` | Core API | AI Worker | `{ sessionId, courseId, liveKitRoomName, targetLocales, major? }` |
| `sessions.ended` | Core API | AI Worker, RAG Worker | `{ sessionId }` |
| `materials.indexing.requested` | Core API | RAG Indexer | `{ materialId, blobUrl, sourceType, courseId, week? }` |
| `materials.indexing.completed` | RAG Indexer | Core API (`Material.indexingStatus` 갱신) | `{ materialId, status, error? }` |
| `transcripts.segment` | AI Worker | Core API (`TranscriptSegment` upsert) | `{ sessionId, segmentId, sequence, textKo, rawTextKo?, sttConfidence?, translations, ts }` |

### LiveKit DataChannel 토픽

| 토픽 | 발행 주체 | 내용 |
|---|---|---|
| `stt` | AI Worker | 한국어 원문 (interim/final) |
| `caption` | AI Worker | locale별 번역 자막 (`caption.final`) |
| `audio-status` | AI Worker | TTS 재생 상태 |

`segmentId`와 `sequence`는 `stt` / `caption` / `audio-status` / DB 저장 전 구간에서 **동일한 값**으로 유지되어, 자막·음성·기록을 하나의 발화로 묶는 키 역할을 합니다.

---

## 세션 라이프사이클

### 수업 시작

1. 교수가 `POST /sessions/start { courseId, targetLocales }` 호출
2. Core API:
   1. `Session` 레코드 생성 (`status=active`)
   2. LiveKit `RoomService.createRoom()`
   3. **Redis prewarm** — `session:{id}:config`, `glossary:{courseId}`
   4. **Pub/Sub publish** — `sessions.started`
   5. 교수용 LiveKit 토큰 반환
3. AI Worker가 `sessions.started`를 수신 → Room 입장 → `worker:status=ready`
4. 교수 화면이 워커 상태를 폴링해 "수업 시작 가능" 상태로 전환

### 학생 입장 (QR)

1. `GET /qr/:sessionId` → 단기 JoinToken(JWT, 24h)이 임베드된 QR PNG
2. 학생 앱이 `POST /sessions/:id/token { locale }` 호출
3. Core API가 JoinToken 검증 → 해당 세션·locale의 LiveKit 토큰 발급
4. 학생이 Room 입장 → `tts.{locale}` 오디오 트랙 구독 + DataChannel 자막 수신

### 실시간 파이프라인 (AI Worker 내부)

```text
STT final
  → Segmenter                       # 분절 (최대 60자 / idle 1.2s / 한국어 종결어미)
  → SpeechSegment(segmentId, sequence)
  → segment queue                   # bounded, 역압(back-pressure) 적용
  → RAG 검색 + 번역                   # RAG는 fail-open
  → caption.final 발행               # 번역 완료 즉시 (TTS를 기다리지 않음)
  → locale별 TTS queue               # locale 내 순서 보장, 중복 발행 없음
  → audio-status
  → LiveKit audio track tts.{locale}
```

보장 조건:

- 동일 locale 내에서 TTS 재생이 겹치지 않음
- locale별 `sequence` 순서 보존
- 자막은 TTS보다 먼저 나감
- TTS 타임아웃·재시도·dedupe 적용
- 교수 트랙이 끊겼다 재연결돼도 프로세스 재시작 없이 재부착
- 워커 재시작 시 Redis 상태에서 활성 세션 복구

### 수업 종료

`POST /sessions/:id/end` → `sessions.ended` 발행 → 워커가 큐를 flush하고 `stopped`로 전이
→ Core API가 최대 `WORKER_STOP_TIMEOUT_SEC`(기본 8초) 대기 후 LiveKit Room 삭제.
종료 시점에 남은 TTS 백로그는 폐기됩니다(룸 삭제 후 재생은 의미가 없음).

---

## DB 마이그레이션

`synchronize: false`가 고정이므로 **스키마 변경은 항상 마이그레이션 파일로** 합니다.

```bash
npm run migration:generate -- src/migrations/<Name>   # 엔티티 변경분으로 생성
npm run migration:create -- src/migrations/<Name>     # 빈 파일 생성
npm run migration:run                                 # 적용
npm run migration:revert                              # 직전 1개 롤백
```

운영(빌드 산출물) 환경에서는 `npm run migration:run:prod`, `npm run seed:prod`를 사용합니다.

현재 마이그레이션:

| 파일 | 내용 |
|---|---|
| `1716470000000-InitSchema` | 기본 스키마 |
| `1716480000000-AddTranscriptSegments` | 자막 세그먼트 테이블 |
| `1716490000000-AddSessionAttendances` | 세션 출석 |
| `1716500000000-AddMaterialPreview` | 강의자료 미리보기 |
| `1716510000000-AddCourseMajor` | 과목 전공(`major`) 컬럼 |

---

## 테스트

### Core API

```bash
npm test              # 단위 테스트 (*.spec.ts)
npm run test:watch
npm run test:cov      # 커버리지
npm run test:e2e      # e2e (Supertest + 테스트 DB)
npm run lint          # ESLint + Prettier (--fix)
npm run format
```

- 단위 테스트는 서비스 로직 중심(`src/**/*.spec.ts`)
- e2e는 `test/jest-e2e.json` 설정 사용
- LiveKit / Blob / Redis Pub/Sub 등 외부 시스템은 인터페이스 모킹

### AI Worker

```bash
cd ai-worker
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m compileall univoice_worker
python -m pytest -q
```

테스트는 전부 fake를 사용하므로 **Azure·OpenAI·LiveKit·Redis 없이 실행**됩니다.

### RAG Service

```bash
cd rag-experiment
python -m pytest tests -q
```

### 개발 도구 (AI Worker)

| 도구 | 용도 |
|---|---|
| `tools/student_subscriber.py` | 학생으로 입장해 자막·오디오 출력을 캡처 |
| `tools/professor_audio_publisher.py` | 교수 WAV 파일을 세션에 발행 (실제 마이크 없이 테스트) |
| `tools/local_pipeline_demo.py` | LiveKit·클라우드 없이 파이프라인만 구동 |
| `tools/stt_benchmark.py` | STT 정확도 벤치마크 (`bench_data/` 사용) |
| `tools/latency_probe.py`, `tools/latency_report.py` | 구간별 지연 계측·집계 |

수동 E2E 체크리스트는 [`ai-worker/README.md`](ai-worker/README.md) 하단에 있습니다.

---

## npm 스크립트

| 스크립트 | 설명 |
|---|---|
| `start` / `start:dev` / `start:debug` | 서버 실행 / watch / 디버그 |
| `start:prod` | `node dist/main` (빌드 산출물 실행) |
| `build` | `nest build` |
| `lint` / `format` | ESLint(--fix) / Prettier |
| `test` / `test:watch` / `test:cov` / `test:e2e` | 테스트 |
| `migration:generate` / `migration:create` / `migration:run` / `migration:revert` | TypeORM 마이그레이션 |
| `migration:run:prod` / `seed:prod` | 빌드 산출물 기준 마이그레이션·시드 |
| `seed` | 최초 admin 계정 생성 |
| `demo:validate` / `demo:up` / `demo:down` | Docker 데모 환경변수 검증·기동·종료 |
| `staging:validate` / `staging:audit` | 스테이징 환경변수 검증 / 프로덕션 의존성 취약점 감사 |
| `preview:web` | 웹 클라이언트 프리뷰 |

---

## 상세 문서

| 문서 | 내용 |
|---|---|
| [`docs/UniVoice_CoreAPI_설계.md`](docs/UniVoice_CoreAPI_설계.md) | Core API 설계 명세 (경계·책임 정의 포함) |
| [`docs/통합_결정.md`](docs/통합_결정.md) | 팀원 3인 구현본을 하나로 통합한 근거 기록 |
| [`docs/rag-demo.md`](docs/rag-demo.md) | 통합 RAG 데모 실행 절차 |
| [`docs/staging-deployment.md`](docs/staging-deployment.md) | 최소 HTTPS 스테이징 배포 |
| [`docs/paid-deployment-azure.md`](docs/paid-deployment-azure.md) | Azure 유료 배포 전환 체크리스트 |
| [`docs/local-tailscale-demo.md`](docs/local-tailscale-demo.md) | 로컬 PC + Tailscale 시연 구성 |
| [`docs/device-integration-checklist.md`](docs/device-integration-checklist.md) | 실기기(모바일·태블릿) 통합 테스트 체크리스트 |
| [`docs/latency-measurement.md`](docs/latency-measurement.md) | 지연 측정 재현 절차 |
| [`docs/latency-results.md`](docs/latency-results.md) | 실측 결과 (2026-08-12) |
| [`rag-experiment/REPORT.md`](rag-experiment/REPORT.md) | 임베딩 모델 비교·선정 실험 보고서 |
| [`ai-worker/README.md`](ai-worker/README.md) | AI 워커 파이프라인 상세 |
| [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) | 코딩 컨벤션 및 도메인 규칙 |

---

## 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| 서버가 뜨지 않고 환경변수 에러 | `src/config/env.validation.ts`의 필수값 누락. `.env.example`과 대조 |
| `/health/ready`가 503 | PostgreSQL 또는 Redis 미기동. `docker compose ps`로 확인 |
| 교수 화면에 "AI 워커 응답 대기" | 워커 미기동이거나 이전 워커가 좀비 상태. `stop-all.ps1` 후 재기동 (워커 1개 실행 시 `python.exe`가 2개 보이는 것은 LiveKit SDK 구조상 정상) |
| 교수 화면에 "RAG 연결 안 됨" | RAG 서비스 미기동. `RAG_URL`이 Docker용 `rag-service` 이름으로 되어 있지 않은지 확인 (로컬은 `127.0.0.1`) |
| 교수 화면에 "RAG 인덱스 없음" | `rag-experiment/indexes`가 비어 있음. `python src/build_demo_indexes.py` 실행 |
| 자막은 나오는데 번역에 전공 문맥이 안 붙음 | `RAG_ENABLED=true`인지, 과목에 `major`가 설정되었는지 확인. RAG는 fail-open이라 조용히 넘어감 |
| 자막이 절 중간에서 잘림 | `STT_SEGMENTATION_SILENCE_MS` 상향 (기본 800) |
| 유령 자막·TTS가 나감 | 소음을 발화로 오인한 환청. `STT_OPENAI_VAD_THRESHOLD` 상향, `STT_OPENAI_MIN_CONFIDENCE` 설정 |
| 번역이 한 번 멈추면 전부 멈춤 | 컨슈머가 직렬. `TRANSLATE_TIMEOUT_SEC`(기본 8초) 확인 |
| 태블릿에서 PDF가 빈 화면 | pdf.js CMap/표준 폰트 정적 서빙 경로 확인 (`/vendor/pdfjs/*`) |
| 세션 종료가 걸려 다음 수업이 안 열림 | `SESSION_STOP_TIMEOUT_SEC`, `WORKER_STOP_TIMEOUT_SEC` 확인. 어느 단계도 무제한 대기하지 않도록 설계됨 |

---

## 라이선스

UNLICENSED (사내/학내 프로토타입)
