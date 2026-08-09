# 완전 통합 RAG 데모

이 데모는 저장소에 포함된 PDF를 KURE로 임베딩하고 전공/강의별 FAISS 인덱스를 만든 뒤,
실시간 AI worker의 번역 직전에 검색 문맥을 주입한다.

## 데이터 흐름

```text
교수 음성 → Azure STT → RAG HTTP client
                         → 전공 Router(ai/hss/bme)
                         → KURE + FAISS 검색
                         → score gate
             → 검색 문맥을 번역 프롬프트에 주입
             → 다국어 자막 → Azure TTS → 학생 LiveKit track
```

RAG 서비스는 courseId 기준으로 인덱스를 좁힌다. `RAG_COURSE_INDEX_MAP`에 등록된
과목만 전공 인덱스 + 그 과목의 강의자료 인덱스를 함께 검색하고, 등록되지 않은
과목은 전공 인덱스만 검색한다(다른 과목 강의자료가 섞이지 않는다). 사용 가능한
조합:

- `ai`: `major_ai` (+ 등록 시 `lecture_kim_i2a`)
- `hss`: `major_humanities_social_sciences` (+ 등록 시 국어학개론/종교사회학 강의 중 그 과목 것만)
- `bme`: `major_biomedical_bioengineering` (+ 등록 시 분자생물학 강의)

## 처음 실행

첫 실행은 Docker 이미지 설치와 `nlpai-lab/KURE-v1` 다운로드/인덱싱 때문에 시간이 걸린다.
모델과 인덱스는 Docker named volume에 보존되므로 다음 실행부터 재사용한다.
For the CPU demo, `RAG_MAX_SEQ_LENGTH=512` matches the 500-token chunks and reduces indexing and live retrieval latency.

```powershell
npm.cmd run demo:validate
docker compose --env-file .env.demo -f docker-compose.demo.yml up -d --build
docker compose --env-file .env.demo -f docker-compose.demo.yml ps -a
```

정상 상태:

- `rag-indexer`: `Exited (0)`
- `rag-service`: `healthy`
- `ai-worker`: `running`
- `app`, `postgres`, `redis`, `azurite`: `healthy`

## RAG 단독 확인

RAG 서비스는 로컬 PC의 `127.0.0.1:8000`에만 노출된다.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready

$body = @{
  sentence = '그 피시알 그거 몇 단계라 했죠'
  major = 'auto'
  glossaryHits = @()
  courseId = 'manual-demo'
} | ConvertTo-Json
$bodyUtf8 = [System.Text.Encoding]::UTF8.GetBytes($body)
Invoke-RestMethod http://127.0.0.1:8000/retrieve `
  -Method Post -ContentType 'application/json; charset=utf-8' -Body $bodyUtf8
```

응답에서 `useRag=true`, `major`, `matchedTerms`, `topScore`, `results`, `context`를 확인한다.
관련 없는 문장은 `useRag=false`, `reason=NO_TRIGGER`가 된다.

## 실시간 시연

1. 교수 화면(`/professor`)에서 기존 방식으로 수업을 시작한다.
2. 학생 화면(`/join`)에서 QR 또는 참가 URL로 들어간다.
3. 제공 PDF에 있는 전공 용어를 포함해 말한다.
4. RAG 로그와 학생 자막/TTS를 함께 확인한다.

권장 문장:

- AI: `컨볼루션이 이미지에서 특징을 뽑아낸다고 했죠.`
- HSS: `기능주의와 갈등이론의 차이를 설명합니다.`
- BME: `그 피시알 그거 몇 단계라 했죠.`
- OFF 비교: `오늘 점심 메뉴가 무엇인가요.`

```powershell
docker compose --env-file .env.demo -f docker-compose.demo.yml logs -f rag-service ai-worker
```

`rag-service`에는 Router/검색 결정이, `ai-worker`에는 번역 프롬프트 문맥 주입 여부가 기록된다.

## 전공 선택

기본값 `RAG_DEFAULT_MAJOR=auto`는 세 전공 Router 중 검색 점수가 가장 높은 결과를 사용한다.
특정 과목을 고정하려면 `.env.demo`에 다음 중 하나를 설정한다.

```dotenv
RAG_DEFAULT_MAJOR=ai
# RAG_DEFAULT_MAJOR=hss
# RAG_DEFAULT_MAJOR=bme
```

과목 UUID별로 다르게 고정할 수도 있다.

```dotenv
RAG_COURSE_MAJOR_MAP={"course-uuid-1":"ai","course-uuid-2":"bme"}
```

`RAG_COURSE_MAJOR_MAP`은 ai-worker가 RAG 서비스로 보낼 `major`(auto 회피용)를
정할 뿐, 어떤 인덱스를 검색할지는 정하지 않는다. 인덱스 자체는 RAG 서비스의
`RAG_COURSE_INDEX_MAP`이 정하고, 이 값이 있으면 요청의 `major`를 덮어쓴다.

## 과목별 인덱스 격리 (RAG_COURSE_INDEX_MAP)

`rag-service`는 `courseId`가 `RAG_COURSE_INDEX_MAP`에 등록돼 있으면 그 과목의
전공+강의 인덱스만 검색하고, 등록돼 있지 않으면 전공 인덱스만 검색한다(다른
과목 강의자료가 섞이지 않도록 하는 안전한 기본값). 값은 `.env.demo`에 JSON으로
설정한다.

```dotenv
RAG_COURSE_INDEX_MAP={"course-uuid-1":{"major":"bme","indexes":["major_biomedical_bioengineering","lecture_lee_molbio"]}}
```

- `major`는 `ai` | `hss` | `bme` 중 하나여야 한다.
- `indexes`는 `rag-experiment/src/config.py`의 `INDEX_SUBSETS` 키 중에서 골라야
  하며, 잘못된 값은 `rag-service` 기동 시 즉시 실패한다(무음 오검색 방지).
- 데모 UI로 만든 과목의 실제 `courseId`는 사전에 알 수 없다. 강의자료 인덱스
  증강까지 확인하려면 `GET /courses`(또는 관리자 UI)로 방금 만든 과목의 id를
  확인한 뒤 `.env.demo`에 추가하고 `rag-service`를 재시작한다. 추가하지 않아도
  전공 인덱스만으로 데모는 정상 동작한다.

## 실시간 지연

RAG는 번역 프롬프트에 문맥을 붙이는 동기 단계라 검색이 느리면 자막·TTS 전체가
밀린다. 세 가지로 지연을 관리한다.

- **타임아웃**: `RAG_TIMEOUT_SEC`(기본 `0.4`초). ai-worker의 `HttpRagClient`는
  타임아웃·네트워크·응답 오류 시 로그만 남기고 `None`으로 fail-open 하므로,
  RAG가 느리거나 죽어도 번역 자체는 계속된다 — 그 문장만 문맥 없이 번역된다.
  이전 기본값(5초)은 최악의 경우 자막을 5초 밀릴 수 있어 실시간 자막에는 너무
  길었다.
- **검색 동시성**: `RAG_SEARCH_CONCURRENCY`(기본 `2`, `rag-service`). 임베딩+FAISS
  호출만 이 크기의 세마포어로 감싼다. 예전에는 전역 락이 모든 세션의 검색을
  완전히 직렬화했는데, CPU 임베딩 모델의 스레드 오버섭스크립션은 막으면서도
  여러 세션 검색이 어느 정도 겹쳐 돌 수 있도록 세마포어로 바꿨다.
- **검색 캐시**: `RAG_SEARCH_CACHE_SIZE`(기본 `256`) / `RAG_SEARCH_CACHE_TTL_SEC`
  (기본 `300`초, `rag-service`). 같은 (인덱스 조합, 정규화된 질의)로 재검색하면
  임베딩·FAISS를 다시 하지 않고 캐시된 결과를 재사용한다. 강의 중 같은 용어가
  반복 언급되는 경우를 노린 것이다(TTS의 `dedupe.py`와 비슷한 문제의식이지만,
  이쪽은 "결과를 재사용"하는 캐시이지 중복 실행을 막는 락이 아니다).

**범위 밖으로 남긴 것**: STT 부분 결과(partial)로 문장이 끝나기 전에 RAG를
미리 실행해 두는 프리페치는 하지 않았다. 세션 전반의 investigative 구조 변경이
필요해 별도 작업으로 남겼다 — 지금은 타임아웃 단축 + 캐시만으로 대부분의
반복 용어는 사실상 즉시 응답된다.

## 인덱스 재생성

PDF 또는 청킹 규칙을 바꿨다면 데모 RAG 볼륨을 제거한 뒤 다시 실행한다. 이 작업은 기존
RAG 인덱스만 삭제하며 다운로드한 KURE 모델 캐시는 유지한다.

```powershell
docker compose --env-file .env.demo -f docker-compose.demo.yml down
docker volume rm univoice-demo_demo-rag-indexes univoice-demo_demo-rag-chunks
npm.cmd run demo:up
```
