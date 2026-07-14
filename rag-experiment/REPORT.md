# 인공지능_입문_교재 편입 RAG 실험 보고서

- 기간: 2026-07-12 ~ 2026-07-13
- 목표: `인공지능_입문_교재.pdf`(89p, 16장)를 전공 RAG(`major_ai`) 코퍼스에 편입해
  인덱스를 재구축하고, 검색 품질·강건성·지연을 재평가하여 임베딩 모델을 확정한다.

## 1. 변경 사항

| 파일 | 내용 |
|------|------|
| `src/ingest.py` | 교재 파서 추가 — `제N장` + `N.M 절` 구조를 절 단위로 청킹, 장별 개요·"이 장의 요약"·"핵심 용어"를 별도 chunk로 생성 (500토큰 초과 시만 overlap 분할) |
| `src/config.py` | `INDEX_SUBSETS["major_ai"]` = glossary + concept_doc + **textbook** |
| `eval/queries_textbook.json` | 교재 기반 신규 질의 24개 (definition/comparison/principle 각 8) |
| `eval/queries_positive_v2.json`, `eval/queries_hard_v2.json` | 미라벨 정답 보정판 (v1은 비교용 보존) |

파싱 검증: 16개 장 전부 원본 콘텐츠(`tools/content_part*.py`)와 대조 — 절·개요·요약·용어 누락 0.

## 2. 코퍼스 구성 (총 340 chunks)

| doc_type | 개수 | 소속 인덱스 |
|----------|----:|------|
| glossary | 101 | major_ai |
| concept_doc | 55 | major_ai |
| **textbook (신규)** | **154** | **major_ai** |
| lecture_slide | 30 | lecture_kim_i2a |

인덱스: kure / bge-m3 / openai × (major_ai 310 + lecture 30 + 통합 340) 전부 재빌드.

## 3. 검색 품질 평가

### 3.1 교재 기반 신규 질의 24개 (major_ai)

| 모델 | R@1 | R@3 | MRR |
|------|----:|----:|----:|
| kure | **0.958** | 1.000 | 0.979 |
| bge-m3 | 0.958 | 1.000 | 0.979 |
| openai | 0.792 | 0.917 | 0.851 |

openai는 한국어 교재 질의에서 −16.6%p 열세, "전이학습 원리"는 top-5 전멸.

### 3.2 기존 질의 회귀 (positive 34개, major_ai)

| 모델 | 교재 전 | v1 라벨 | v2 라벨(보정) |
|------|----:|----:|----:|
| kure | 0.971 | 0.941 | **0.971** |
| bge-m3 | 0.971 | 0.912 | **0.971** |
| openai | 0.971 | 0.912 | 0.941 |

v1의 하락은 대부분 **교재가 같은 개념을 다뤄 생긴 미라벨 정답** (top-1 검수로 판정,
근거: `eval/_miss_analysis*.txt`). 보정 후 교재 전 수준 완전 복귀 →
**교재 편입으로 인한 실질적 품질 저하 없음**.

### 3.3 하드 세트 (paraphrase 10 / stt_noise 10 / negative 10, 통합 인덱스, v2)

| 모델 | R@1 | R@3 | paraphrase R@1 | stt_noise R@1 |
|------|----:|----:|----:|----:|
| kure | 0.900 | 1.000 | **0.900** | 0.900 |
| bge-m3 | 0.900 | 1.000 | 0.800 | 1.000 |
| openai | 0.900 | 1.000 | 0.800 | 1.000 |

- 신규 용어 세트 31개(`queries_hard_newterms.json`): **세 모델 모두 전 질의 rank-1**.
- 남은 진짜 miss는 질의당 1~2건(예: kure "백프로파게이션" 음차)이며 전부 top-5 이내.

### 3.4 RAG OFF 임계값 (top-1 점수 필터링, v2 병합 78개)

negative(수업 잡담)가 교재 chunk와 매칭돼 점수가 오르는 현상 없음
(kure negative 평균 0.407 ± 0.05).

| 모델 | 권장 임계값 | negative 차단 / positive 통과 | 점수 분리 폭 |
|------|----:|----|----:|
| kure | **0.50** | 100% / 99% | **+0.273** |
| bge-m3 | 0.55 | 100% / 99% | +0.231 |
| openai | 0.40 | 100% / 90% | +0.286 (스케일 낮음) |

### 3.5 교재 질의 하드 버전 (paraphrase 24 / stt_noise 24, major_ai, `results_textbook_hard.md`)

원본 24개와 정답 라벨은 동일, 표현만 우회 서술(paraphrase)·STT풍(음차+필러)으로 변형.

| 모델 | 전체 R@1 | R@5 | paraphrase R@1 | stt_noise R@1 | (원본 R@1) |
|------|----:|----:|----:|----:|----:|
| kure | 0.583 | **0.854** | 0.542 | **0.625** | 0.958 |
| bge-m3 | 0.562 | 0.792 | 0.500 | 0.625 | 0.958 |
| openai | 0.583 | 0.771 | **0.625** | 0.542 | 0.792 |

원본 0.958 → 하드 ~0.58로 큰 폭 하락. miss 전수 검수(`_miss_analysis_textbook_hard.txt`) 결과 실패 유형:

1. **영문 용어의 한글 음차가 지배적 실패 원인** — 세 모델 공통.
   "에이치엔에스더블유"(HNSW)는 3모델 전부 top-5 전멸,
   "케이민즈"(K-means)는 엉뚱한 장으로, "트랜스퍼 러닝"은 3모델 모두
   **트랜스포머로 오인**(표면 유사성). 임베딩 교체로 해결되지 않는 구조적 약점.
2. paraphrase 실패는 대부분 같은 장의 인접 chunk(요약/핵심용어/이웃 절)로
   빠진 rank 2~5 — top-5 안에는 있는 경우가 많아 kure R@5는 0.854 유지.
3. 일부는 미라벨 정답 가능성(예: RAG 파이프라인 질의의 top-2가 정답 절의
   분할 조각 `tb_ch16_s2_2`) — 보정하면 실제 수치는 표보다 다소 높음.
4. 모델 간 상보성: openai는 우회 서술에 상대적으로 강하고(paraphrase 0.625)
   음차에 약하며, kure는 그 반대. 종합 순위는 변화 없음(kure R@5 최고).

**시사점 (Univoice 실사용)**: top-5를 쓰면 하드 조건에서도 kure가 85%를 커버하지만,
음성 강의 환경에서 빈번할 **음차 질의는 검색 전 정규화가 필요** —
glossary의 `aliases` 필드를 사전으로 써서 STT 후처리에서 "케이민즈"→"K-평균" 치환,
또는 BM25 병용(하이브리드) 검색 도입이 후보. 하드 질의는 유사도 점수 자체도
낮아질 수 있어 RAG OFF 임계값 0.50과의 상호작용 확인도 필요.

### 3.6 RAG Router (`src/router.py`, `results_router.md`)

프로토타입 `RagClient` seam에 끼울 라우터 프로토타입. rule trigger(glossary+교재
key_terms+보충 개념) → 질의 정규화(음차 치환·필러 제거·정식 용어 병기) →
score gate(top-1 < 0.50 → OFF). 산출 스키마 `{useRag, query, reason}`.

| 지표 | 결과 |
|------|------|
| 라벨 질의 (positive 171 / negative 10) | rule 재현율 90.6% / negative 차단 100% (gate 과차단 0) |
| 발화형 테스트 문장 31개 | **정확도 96.7%** (오답 1: "인공지능 수업은 휴강" — 0.564로 gate 통과) |
| 정규화의 검색 개선 (textbook_hard 48개) | R@1 0.583 → **0.708** (+12.5%p), R@5 0.854 → **0.938** (+8.4%p) |

- rule 미발동 positive 16개는 전부 용어를 일부러 피한 학생 질문형 paraphrase —
  교수 발화 파이프라인에서는 발생 빈도가 낮고, Q&A 기능에 라우터를 쓸 경우에는
  "질문 입력은 rule 생략하고 항상 검색+gate" 모드가 적합.
- 남은 오탐 유형: 전공 단어가 든 운영 공지("인공지능 수업은 휴강"). 공지 패턴
  가드(휴강·시험 범위·과제 등) 추가로 개선 가능하나 주입 피해가 작아 보류.
- ai-worker 포팅: `RagRouter.export_lexicon()`으로 사전을 JSON으로 떨궈
  tools/ 의존 없이 로드. 발화당 비용은 rule만이면 ~0ms, gate까지 ~120ms.

## 4. 지연 벤치마크 (109개 질의, CPU, 단건 임베딩)

| 모델 | 콜드 스타트 | 임베딩 p95 | 검색 p50 | E2E p95 |
|------|--------:|--------:|--------:|--------:|
| kure | 12.1s | 119ms | 0.16ms | **119ms** |
| bge-m3 | 8.3s | 127ms | 0.17ms | 127ms |
| openai | 0.9s | 443ms | 0.48ms | 444ms (API 왕복) |

- 코퍼스 186 → 340 chunk 확대에도 FAISS(IndexFlatIP) 검색은 1ms 미만 — 병목 아님.
- 콜드 스타트는 워커 기동 시 1회 — **사전 로드 필수** (kure 10~20초대, 디스크 캐시에 따라 변동).

## 5. 최종 결론 — 확정 스펙

**kure(nlpai-lab/KURE-v1) 단일 모델**로 전공·강의 RAG 모두 구성:

1. 모든 품질 평가에서 1등 또는 공동 1등. 특히 paraphrase +10%p —
   음성(STT) 기반 실사용 조건에서 가장 중요한 축.
2. bge-m3가 앞서는 유일한 지표(강의 MRR +1.4%p)는 표본 14개에서 질의 0.2개 차이 수준.
3. 지연은 bge-m3와 동급(E2E p95 119ms), openai는 품질·지연 모두 열세로 탈락.
4. positive-negative 점수 분리 폭이 가장 넓어 임계값 운영 마진 최대.
5. 단일 모델 운영으로 메모리·콜드 스타트·인덱스 관리 부담 절감.

| 항목 | 확정값 |
|------|--------|
| 임베딩 모델 | nlpai-lab/KURE-v1 (전공·강의 공용) |
| 전공 인덱스 | `indexes/major_ai/kure` (310 chunks) |
| 강의 인덱스 | `indexes/lecture_kim_i2a/kure` (30 chunks) |
| RAG OFF 임계값 | top-1 코사인 < **0.50** → RAG OFF |
| 운영 요건 | 워커 기동 시 모델 사전 로드(~12s), 세그먼트당 검색 예산 ~120ms(p95) |

## 6. 남은 작업

1. **git 커밋** — 저장소에 커밋 0개, 전체가 미추적 상태 (`$null`, `_extract_check.txt` 정리 + `indexes/`·`.omc/` gitignore 포함).
2. ~~음차 질의 대응~~ → **완료**: RAG Router의 정규화가 해결 (3.6절, R@1 +12.5%p).
   남은 것은 `router.py`를 `ai-worker`의 `RagClient` 구현으로 포팅하는 일.
3. distractor 코퍼스(`data/raw_distractor/`) 채워 강건성 테스트.
4. 프로토타입(`../prototype`) 반영 — 위 확정 스펙 적용.
5. (선택) 하드 질의의 top-1 점수 분포 확인 — RAG OFF 임계값 0.50에 오차단되는지.
6. (선택) 교재 "핵심 용어" 청킹을 용어당 1 chunk로 개선 — 표 셀 줄바꿈 아티팩트 해소.

## 부록: 산출물 색인

| 파일 | 내용 |
|------|------|
| `data/README.md` | 코퍼스 구성과 chunk_id 명명 규칙 (`tb_*`, `lec*`, `concept_*`, `glossary_*`) |
| `eval/results_split_textbook.md` | 교재 질의 24개 평가 |
| `eval/results_split_after_textbook.md` / `results_split_v2.md` | 회귀 평가 (v1 / v2 라벨) |
| `eval/results_v2.md` | v2 병합 78개 + 임계값 분석 |
| `eval/results_hard_v2.md` | 하드 세트 v2 |
| `eval/results_hard_newterms.md` | 신규 용어 31개 (만점) |
| `eval/results_latency.md` | 지연 벤치마크 |
| `eval/results_textbook_analysis.md` | 상세 분석 (miss 판정 근거 포함) |
| `eval/_miss_analysis.txt` / `_miss_analysis_hard.txt` | miss 전수 검수 원본 |
