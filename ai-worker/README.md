# UniVoice AI 워커 — 실시간 번역 파이프라인 (RAG 제외 전 구간)

아키텍처 가이드의 **Python AI 워커**를 기능별 모듈로 나눠 구현한 것.
Core API(NestJS)는 음성을 만지지 않으므로, STT→번역→TTS 전 구간을 이 워커가 담당한다.
**RAG만 교체 가능한 인터페이스로 비워두고, 나머지는 조립하면 그대로 동작한다.**

## 데이터 흐름 (아키텍처 가이드 그대로)

```
교수 마이크 ─▶ LiveKit Room ─▶ [AI 워커]
                                  │
                                  ├─ Azure STT ──▶ 원문 자막(DataChannel topic="stt")
                                  ▼
                              Segmenter (완성 문장)
                                  ▼
                              RAG Trigger ──▶ (RagClient, 기본 NoOp = 건너뜀)
                                  ▼
                              OpenAI 번역 (다국어 JSON 동시)
                                  ├──▶ 번역 자막(DataChannel topic="caption", locale별)
                                  ▼
                              Azure TTS (locale별 음성)
                                  ▼
                           LiveKit track publish  tts.zh-CN / tts.vi-VN ...
                                  ▼
                              학생 앱: 자기 locale track + caption 구독
```

## 모듈 구성 (조립 단위)

| 파일 | 단계 | 역할 |
|------|------|------|
| `main.py` | 진입점 | Redis `sessions.started/ended` 구독, 세션당 워커 기동/정리, glossary·targetLocales 로드 |
| `config.py` | 설정 | env 로드 (LiveKit / Azure Speech / 번역 provider / voice map) |
| `glossary.py` | 공유 | prewarm glossary 파싱 (STT·번역·TTS 공통 참조) |
| `stt.py` | STT | Azure 스트리밍 STT + Phrase List(glossary 용어) |
| `segmenter.py` | 분리 | final 텍스트 → 완성 문장 (종결부호 기준, 꼬리 버퍼링) |
| `rag.py` | **RAG(seam)** | `RagClient` 인터페이스 + `NoOpRagClient`(기본) |
| `translator.py` | 번역 | OpenAI/Azure OpenAI 구조화 출력, glossary+context 주입 |
| `tts.py` | TTS | Azure Neural Voice → 16kHz PCM |
| `audio_publisher.py` | 송출 | locale별 `tts.{locale}` track publish, PCM 프레임 전송 |
| `pipeline.py` | 오케스트레이션 | 위 단계들을 조립 (STT final → 자막+음성) |
| `session_worker.py` | 세션 | Room 입장, track 관리, STT 콜백 ↔ pipeline 배선 |

각 단계는 독립 모듈이라 교체·테스트가 쉽다. 특히 **RAG는 `pipeline`이 `RagClient` 인터페이스에만 의존**하므로, 구현체만 갈아끼우면 된다(아래 참조).

## 자막 DataChannel payload

```jsonc
// topic "stt"  — 원문 한국어 (partial=lossy, final=reliable)
{ "type": "stt.partial" | "stt.final", "sessionId", "lang": "ko-KR", "text", "ts" }

// topic "caption" — 번역 자막 (locale별, reliable)
{ "type": "caption.final", "sessionId", "locale": "zh-CN", "text", "sourceKo", "ts" }
```

학생 앱은 자기 locale의 `tts.{locale}` 오디오 track을 subscribe하고, `caption` 중 자기 locale만 필터링해 자막을 띄우면 된다.

## 실행

```bash
cd ai-worker
python -m venv .venv
.venv\Scripts\activate        # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

cp .env.example .env
#   REDIS_URL, LIVEKIT_*, AZURE_SPEECH_*, OPENAI_API_KEY 채우기

python -m univoice_worker.main
```

## 필요 자격증명(API 키)

| 환경변수 | 어디서 | 용도 |
|---|---|---|
| `REDIS_URL` | Core API와 동일 | 이벤트/prewarm |
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | Core API `.env`와 동일 | Room 입출력 |
| `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` | **Azure Speech 리소스** | STT + TTS 공용 |
| `OPENAI_API_KEY` (+ `OPENAI_MODEL`) | **OpenAI** | 번역 (기본 provider) |
| 또는 `AZURE_OPENAI_*` | **Azure OpenAI** | `TRANSLATE_PROVIDER=azure`일 때 |

> 즉 **새로 필요한 키는 (1) Azure Speech, (2) OpenAI(또는 Azure OpenAI)** 두 가지. LiveKit·Redis는 Core API와 공유.

## 동작 확인 (Core API와 함께)

1. `docker compose up -d` (Redis 등)
2. Core API 기동 → `POST /sessions/start { courseId, targetLocales: ["zh-CN"] }`
3. 워커 로그: `room ... 입장 완료` → `track 'tts.zh-CN' publish 완료` → `파이프라인 준비 완료`
4. 교수 토큰으로 Room 입장해 마이크 publish (교수 웹 또는 LiveKit Agents Playground)
5. 로그에 `final: ...` 확인, 학생 클라이언트에서 `tts.zh-CN` track 재생 + `caption` 자막 수신

---

## RAG 붙이기 (다음 단계)

지금은 `NoOpRagClient`가 항상 `None`을 반환해 **문맥 주입 없이 번역**한다.
실제 RAG를 넣으려면 **파이프라인/번역/TTS는 손대지 말고** `RagClient` 하나만 구현해서 주입한다.

### 1) 인터페이스 (이미 정의됨 — `rag.py`)

```python
class RagClient(Protocol):
    async def retrieve(self, sentence: str, glossary_hits: list[str]) -> str | None:
        # 검색 불필요/결과 없음 → None, 있으면 번역 프롬프트에 넣을 context 문자열
        ...
```

### 2) 구현체 작성 (예: `rag_azure_search.py`)

아키텍처 가이드의 검색 설계를 그대로 옮기면 된다:

```python
class AzureSearchRagClient:
    def __init__(self, search_client, glossary_terms):
        self._search = search_client
        self._terms = set(glossary_terms)

    async def retrieve(self, sentence, glossary_hits):
        # (a) RAG Trigger — 매번 검색하지 않는다
        #     glossary_hits 있음 / 약어·기호(ATP, PCR) / 저신뢰 구간 / 다의어 → 검색
        if not glossary_hits and not _has_abbrev(sentence):
            return None
        # (b) 하이브리드 검색: BM25 + Vector + RRF (검색 우선순위: 이번주자료>보조>지식팩>교재)
        hits = await self._search.hybrid_search(query=sentence, top=3)
        if not hits:
            return None
        # (c) 상위 chunk를 context 문자열로 반환 → translator가 프롬프트에 주입
        return "\n".join(h.content for h in hits)
```

필요한 재료(앞서 정리한 **RAG 작업 문서** 참고):
- **인덱싱 파이프라인**: Core API가 이미 `materials.indexing.requested` 이벤트 + `rag:index:queue`를 발행한다. 이 큐를 **별도 RAG 인덱싱 워커**가 `BRPOP`으로 소비 → Blob에서 자료 다운로드 → chunk → 임베딩(KURE/BGE-m3) → 벡터DB(Qdrant/OpenSearch) 적재. (실시간 워커와 분리)
- **검색 백엔드**: Azure AI Search 또는 오픈소스(OpenSearch BM25 + Qdrant dense + RRF).
- **RAG Trigger 규칙**: glossary hit(이미 `translator.detect_glossary_hits`로 감지) + 약어/기호 정규식 + STT confidence(필요 시 `stt.py`에서 confidence 노출 추가).

### 3) 주입 (한 줄)

`main.py`의 `start_session()`에서 워커 생성 시 넘기면 끝:

```python
worker = SessionWorker(
    ..., glossary=glossary,
    rag=AzureSearchRagClient(search_client, [g.term for g in glossary]),
)
```

`pipeline.py`는 `self._rag.retrieve(...)`만 호출하므로, 이 주입 한 줄 외에 **다른 코드 변경이 없다.** 이게 RAG를 마지막에 끼우기 쉽게 인터페이스로 비워둔 이유다.
