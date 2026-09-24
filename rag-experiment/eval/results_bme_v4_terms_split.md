# 임베딩 모델 비교 평가 결과 (확장 지표)

- 질의 파일: `queries_bme_positive.json`, `queries_bme_hard.json` (index: `major_biomedical_bioengineering`, `lecture_lee_molbio`) (총 136개) / top-k = 5
- 평가 모델: kure
- Full-Recall@5: 정답 chunk 전부가 top-5에 포함된 질의 비율
- 라우터 정규화 적용: major=bme (RagRouter.normalize — 음차 치환 + 필러 제거)
- 완화 지표: 정답 chunk와 같은 장(chapter)에 속한 textbook/concept_doc chunk 전체를 정답으로 인정 (glossary 제외)

## 전체 평균 (positive 질의만, 엄격 기준)

| 모델 | R@1 | R@3 | R@5 | MRR | Full-R@5 | n |
|------|----:|----:|----:|----:|------:|---:|
| kure | 0.643 | 0.944 | 0.976 | 0.793 | 0.730 | 126 |

## 전체 평균 (positive 질의만, 완화 기준 — 같은 장 형제 chunk 허용)

Full-Recall@k는 표기하지 않는다 — 완화 정답 집합(같은 장 chunk 전체)이 보통 top-k보다 커서 '전부 포함'이 정의상 거의 항상 불가능하다. 완화 기준에서는 R@k(하나라도 맞으면 hit)만 의미가 있다.

| 모델 | R@1 | R@3 | R@5 | MRR | n |
|------|----:|----:|----:|----:|---:|
| kure | 0.960 | 0.992 | 0.992 | 0.976 | 126 |

## query_type별 분리 집계 (엄격 기준)

| 모델 | query_type | R@1 | R@3 | R@5 | MRR | Full-R@5 | n |
|------|-----------|----:|----:|----:|----:|------:|---:|
| kure | comparison | 0.500 | 0.917 | 0.958 | 0.696 | 0.833 | 24 |
| kure | definition | 0.875 | 0.969 | 1.000 | 0.928 | 0.688 | 32 |
| kure | principle | 0.719 | 0.938 | 0.969 | 0.836 | 0.688 | 32 |
| kure | paraphrase | 0.417 | 0.958 | 1.000 | 0.684 | 0.833 | 24 |
| kure | stt_noise | 0.571 | 0.929 | 0.929 | 0.738 | 0.571 | 14 |

## top-1 유사도 점수 분포 (positive vs negative)

| 모델 | positive 평균±표준편차 | negative 평균±표준편차 | 평균 차이 |
|------|--------------------:|--------------------:|--------:|
| kure | 0.6518 ± 0.0626 | 0.4116 ± 0.0628 | +0.2402 |

## 임계값별 필터링 효과

top-1 점수 < 임계값이면 'RAG OFF'로 판정한다고 가정.
셀 = negative 차단율 / positive 통과율 (둘 다 높을수록 좋음)

| 임계값 | kure |
|-------:|------:|
| 0.30 | 0% / 100% |
| 0.35 | 10% / 100% |
| 0.40 | 50% / 100% |
| 0.45 | 70% / 98% |
| 0.50 | 90% / 96% |
| 0.55 | 90% / 94% |
| 0.60 | 100% / 80% |
| 0.65 | 100% / 57% |
| 0.70 | 100% / 22% |

## R@5 미검색 질의 (모델별)

'완화 회수' = 엄격 기준으로는 놓쳤지만 같은 장의 형제 chunk는 top-k에 있음 (틀린 chunk가 아니라 같은 장의 다른 chunk를 준 경우).

- **kure**: 3개 (완화 회수 2개 / 진짜 실패 1개)
  - (principle) 선도가닥과 지연가닥이 왜 나뉘어? [완화 회수] → top-5: bmetb_ch04_term05, bmetb_ch16_term03, bmetb_ch06_s2, bmetb_ch02_term07, bmetb_ch10_summary
  - (comparison) 점착말단과 평활말단의 차이는? [완화 회수] → top-5: bmetb_ch10_term02, bmetb_ch10_summary, bmetb_ch20_term03, bmetb_ch19_term03, bmetb_ch12_s2
  - (stt_noise) 자 씨에이치오 세포 그거 항체 만들 때 쓴다고 하셨는데 [진짜 실패] → top-5: bmetb_ch17_s2, biolec_p61_61, bmetb_ch08_s3, bmetb_ch08_term04, bmetb_ch03_intro
