# 인공지능_입문_교재.pdf 편입 후 major_ai 재구축·평가 분석

- 실행일: 2026-07-12
- 변경: `major_ai` = glossary(101) + concept_doc(55) + **textbook(154)** = 310 chunks
- 인덱스: kure / bge-m3 / openai 3개 모델 모두 재빌드 (major_ai + 통합)
- 상세 수치: `results_split_textbook.md`(교재 질의), `results_split_after_textbook.md`(회귀),
  miss 원본: `_miss_analysis.txt`

## 1. 교재 기반 신규 질의 24개 (`queries_textbook.json`)

| 모델 | R@1 | R@3 | MRR |
|------|----:|----:|----:|
| kure | 0.958 | 1.000 | 0.979 |
| bge-m3 | 0.958 | 1.000 | 0.979 |
| openai | 0.792 | 0.917 | 0.851 |

- kure/bge-m3의 유일한 rank-2는 "계층적 군집 vs K-평균" — top-1이 인접 절(tb_ch08_s1,
  K-평균 설명)이라 사실상 부분 정답.
- openai는 5개 질의에서 순위 하락, 특히 "전이학습 원리" 질의는 top-5 전멸
  (top-1이 엉뚱한 glossary_learning_agent). 한국어 교재 질의에서 명확히 열세.

## 2. 기존 질의 회귀 평가 (`queries_positive.json`, major 34개)

| 모델 | R@1 (교재 전) | R@1 (교재 후) | 변화 |
|------|----:|----:|----|
| kure | 0.971 | 0.941 | −3.0%p |
| bge-m3 | 0.971 | 0.912 | −5.9%p |
| openai | 0.971 | 0.912 | −5.9%p |

R@3은 kure/bge-m3 모두 1.000 유지 → top-5 밖으로 밀려난 정답 없음.

### 하락 원인 판정 (miss별 top-1 검수)

R@1 하락의 대부분은 **라벨에 없는 교재 chunk가 실제로 정답을 담고 있어 miss로
집계된 것** (라벨링 아티팩트)이며 실제 품질 저하가 아님:

| 질의 | top-1으로 올라온 chunk | 판정 |
|------|----------------------|------|
| CNN 합성곱·풀링 역할 (kure·bge) | tb_ch12_s3 "풀링과 전형적 CNN 구조" | **정답인데 미라벨** |
| 경사하강법 원리 (bge) | tb_ch06_s3 "경사하강법의 원리" | **정답인데 미라벨** |
| RAG는 어떻게 환각을 줄여? (openai) | tb_ch16_s1 "RAG의 동기: 환각 완화" | **정답인데 미라벨** |
| 탐색은 상태공간에서 어떻게 (kure·bge) | glossary_search_problem | 교재 무관 (기존에도 rank 경쟁) |
| 분류 vs 군집화 (openai) | tb_ch08_s3 계층적 군집 | 부분 관련 (모델 열세) |
| 지도학습 vs 강화학습 (openai) | glossary_supervised_learning rank=4 | 교재 무관 (모델 열세) |

→ 미라벨 정답을 정답으로 인정하면 kure는 사실상 교재 추가 전 수준(≈0.971) 유지.

## 3. v2 라벨 보정 (2026-07-13)

`_miss_analysis.txt`/`_miss_analysis_hard.txt` 검수 결과를 반영해
**"해당 chunk만 읽어도 질문에 답이 되는" 미라벨 정답**을 추가한
`queries_positive_v2.json`(3개 질의), `queries_hard_v2.json`(12개 질의)을 생성.
v1 파일은 교재 편입 전 결과와의 비교용으로 보존.

### major_ai 분리 인덱스 (positive_v2, `results_split_v2.md`)

| 모델 | R@1 (교재 전) | R@1 (v1 라벨) | R@1 (v2 라벨) |
|------|----:|----:|----:|
| kure | 0.971 | 0.941 | **0.971** |
| bge-m3 | 0.971 | 0.912 | **0.971** |
| openai | 0.971 | 0.912 | 0.941 |

→ 라벨 보정 후 kure/bge-m3는 교재 편입 전과 완전 동일. **교재 154 chunk 편입으로
인한 실질적 검색 품질 저하 없음**이 확정됨.

### 하드 세트 (hard_v2 30개, 통합 인덱스, `results_hard_v2.md`)

- 세 모델 모두 R@1 0.900, R@3부터 1.000 (positive 20개 기준).
- 남은 진짜 miss: kure "백프로파게이션 어떻게 돌아가"(STT 음차, rank 2),
  bge-m3/openai "문장 처리 시 단어 가중치"(어텐션 우회 표현, rank 2~5) 등
  질의당 1~2건 — 전부 rank 5 이내라 top-5 검색에는 영향 없음.
- `queries_hard_newterms.json` 31개는 세 모델 모두 **전 질의 rank-1** (보정 불필요).

### RAG OFF 임계값 재산정 (v2 병합 78개, 통합 인덱스, `results_v2.md`)

교재 편입으로 negative(수업 잡담) 점수가 오르지 않았는지 확인 →
kure negative top-1 평균 0.407±0.05로 안전.

| 모델 | 권장 임계값 | negative 차단 / positive 통과 |
|------|----:|----|
| kure | **0.50** | 100% / 99% |
| bge-m3 | 0.55 | 100% / 99% |
| openai | 0.40 | 100% / 90% (점수 스케일이 낮고 통과율 손실 큼) |

## 4. 지연 벤치마크 재측정 (2026-07-13, `results_latency.md`)

인덱스 186 → 340 chunk 확대 후에도 지연 영향 없음 (109개 질의, CPU, 단건 임베딩):

| 모델 | E2E p95 (교재 전) | E2E p95 (교재 후) | 검색 p50 |
|------|----:|----:|----:|
| kure | 154ms | **119ms** | 0.16ms |
| bge-m3 | 151ms | 127ms | 0.17ms |
| openai | 542ms | 444ms | 0.48ms |

- FAISS IndexFlatIP 검색은 여전히 1ms 미만 — 코퍼스 2배는 병목이 아님.
  E2E 차이는 실행 간 편차(CPU 부하) 수준.
- 지연 예산 관점: kure 세그먼트당 ~120ms(p95) + 콜드 스타트 12s(사전 로드 1회) —
  실시간 파이프라인에 수용 가능.

## 5. 결론

1. **모델 선택: kure(nlpai-lab/KURE-v1) 유지.** 교재 질의·회귀 모두 1등
   (bge-m3와 동률이거나 우위, openai는 교재 질의에서 −16.6%p 열세).
2. 교재 154 chunk 편입은 검색 품질을 실질적으로 해치지 않음 — R@1 하락분은
   대부분 "교재가 같은 개념을 다뤄 생긴 미라벨 정답" 때문.
3. 후속 옵션: `queries_positive.json`의 해당 3개 질의에 tb_ch12_s3 / tb_ch06_s3 /
   tb_ch16_s1을 정답으로 추가하면 벤치마크가 코퍼스 확장을 반영하게 됨
   (단, 과거 결과와의 직접 비교는 깨짐 — 별도 파일로 버전 관리 권장).
