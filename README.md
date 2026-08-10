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

## Related Docs

- [docs/병합_내역.md](docs/병합_내역.md) — Yumin × Sehui 프로토타입 통합 기록 (무엇을 어떻게 합쳤는지)
- [AGENTS.md](/C:/UniVoice/prototype-Yumin/AGENTS.md)
- [CLAUDE.md](/C:/UniVoice/prototype-Yumin/CLAUDE.md)
- [docs/통합_결정.md](/C:/UniVoice/prototype-Yumin/docs/%ED%86%B5%ED%95%A9_%EA%B2%B0%EC%A0%95.md)
- [docs/UniVoice_CoreAPI_설계.md](/C:/UniVoice/prototype-Yumin/docs/UniVoice_CoreAPI_%EC%84%A4%EA%B3%84.md)