# 전공 RAG vs 강의 RAG — 임베딩 모델 독립 비교

- 질의 파일: `queries_positive_v2.json` / top-k = 5
- major_ai(전공): glossary + concept_doc / definition·comparison·principle 질의
- lecture_kim_i2a(강의): lecture_slide / lecture 질의
- 인덱스 밖 doc_type의 정답 chunk는 라벨에서 제외하고 평가

## 인덱스 × 모델 지표

| 인덱스 | 모델 | R@1 | R@3 | MRR | n |
|--------|------|----:|----:|----:|---:|
| major_ai | kure | 0.971 | 1.000 | 0.985 | 34 |
| major_ai | bge-m3 | 0.971 | 1.000 | 0.985 | 34 |
| major_ai | openai | 0.941 | 0.971 | 0.963 | 34 |
| lecture_kim_i2a | kure | 0.786 | 0.929 | 0.857 | 14 |
| lecture_kim_i2a | bge-m3 | 0.786 | 0.929 | 0.871 | 14 |
| lecture_kim_i2a | openai | 0.571 | 0.857 | 0.726 | 14 |

## 인덱스별 1등 모델

- **major_ai: kure** — 2등 bge-m3 대비 R@1 +0.0%p, MRR +0.0%p (R@1 동률 → MRR로 판정)
- **lecture_kim_i2a: bge-m3** — 2등 kure 대비 R@1 +0.0%p, MRR +1.4%p (R@1 동률 → MRR로 판정)

## 판단 보조

- 두 인덱스의 1등 모델이 **다름**: 전공=kure, 강의=bge-m3
- 강의 인덱스에서 bge-m3가 전공 1등(kure)보다 R@1 **+0.0%p** 높음
- lecture 질의 14개 기준 이 격차는 **질의 0.0개 차이** — 표본이 작으니 해석에 주의

## 라벨 조정 내역 (인덱스 밖 정답 제외)

- major_ai | 일부 제외: 합리적 에이전트가 뭐야? → lec02_p07_07
- major_ai | 일부 제외: 탐색은 상태공간에서 어떻게 이루어져? → lec03_p10_10
- lecture_kim_i2a | 일부 제외: 지각열이 무슨 뜻이야? → glossary_percept_sequence
- lecture_kim_i2a | 일부 제외: 에이전트는 아키텍처와 프로그램으로 어떻게 나뉘어? → glossary_agent_program
- lecture_kim_i2a | 일부 제외: 성과 측도는 어떻게 설계하는 게 좋아? → glossary_performance_measure
- lecture_kim_i2a | 일부 제외: 원자적 표현, 분해된 표현, 구조적 표현은 뭐가 달라? → glossary_representation
- lecture_kim_i2a | 일부 제외: 상태 공간 표현에 그래프와 트리를 왜 써? → glossary_graph_tree
