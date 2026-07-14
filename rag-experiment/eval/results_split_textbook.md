# 전공 RAG vs 강의 RAG — 임베딩 모델 독립 비교

- 질의 파일: `queries_textbook.json` / top-k = 5
- major_ai(전공): glossary + concept_doc / definition·comparison·principle 질의
- lecture_kim_i2a(강의): lecture_slide / lecture 질의
- 인덱스 밖 doc_type의 정답 chunk는 라벨에서 제외하고 평가

## 인덱스 × 모델 지표

| 인덱스 | 모델 | R@1 | R@3 | MRR | n |
|--------|------|----:|----:|----:|---:|
| major_ai | kure | 0.958 | 1.000 | 0.979 | 24 |
| major_ai | bge-m3 | 0.958 | 1.000 | 0.979 | 24 |
| major_ai | openai | 0.792 | 0.917 | 0.851 | 24 |

## 인덱스별 1등 모델

- **major_ai: kure** — 2등 bge-m3 대비 R@1 +0.0%p, MRR +0.0%p (R@1 동률 → MRR로 판정)

## 판단 보조


## 라벨 조정 내역 (인덱스 밖 정답 제외)

- major_ai: 조정 없음
