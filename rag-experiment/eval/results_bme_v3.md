# 임베딩 모델 비교 평가 결과 (확장 지표)

- 질의 파일: `queries_bme_positive.json`, `queries_bme_hard.json` (index: `major_biomedical_bioengineering`, `lecture_lee_molbio`) (총 136개) / top-k = 5
- 평가 모델: kure
- Full-Recall@5: 정답 chunk 전부가 top-5에 포함된 질의 비율
- 라우터 정규화 적용: major=bme (RagRouter.normalize — 음차 치환 + 필러 제거)
- 완화 지표: 정답 chunk와 같은 장(chapter)에 속한 textbook/concept_doc chunk 전체를 정답으로 인정 (glossary 제외)

## 전체 평균 (positive 질의만, 엄격 기준)

| 모델 | R@1 | R@3 | R@5 | MRR | Full-R@5 | n |
|------|----:|----:|----:|----:|------:|---:|
| kure | 0.683 | 0.841 | 0.865 | 0.760 | 0.770 | 126 |

## 전체 평균 (positive 질의만, 완화 기준 — 같은 장 형제 chunk 허용)

Full-Recall@k는 표기하지 않는다 — 완화 정답 집합(같은 장 chunk 전체)이 보통 top-k보다 커서 '전부 포함'이 정의상 거의 항상 불가능하다. 완화 기준에서는 R@k(하나라도 맞으면 hit)만 의미가 있다.

| 모델 | R@1 | R@3 | R@5 | MRR | n |
|------|----:|----:|----:|----:|---:|
| kure | 0.841 | 0.944 | 0.968 | 0.892 | 126 |

## query_type별 분리 집계 (엄격 기준)

| 모델 | query_type | R@1 | R@3 | R@5 | MRR | Full-R@5 | n |
|------|-----------|----:|----:|----:|----:|------:|---:|
| kure | comparison | 0.792 | 0.958 | 0.958 | 0.868 | 0.875 | 24 |
| kure | definition | 0.531 | 0.719 | 0.812 | 0.635 | 0.750 | 32 |
| kure | principle | 0.750 | 0.844 | 0.844 | 0.797 | 0.719 | 32 |
| kure | paraphrase | 0.708 | 0.917 | 0.917 | 0.806 | 0.833 | 24 |
| kure | stt_noise | 0.643 | 0.786 | 0.786 | 0.702 | 0.643 | 14 |

## top-1 유사도 점수 분포 (positive vs negative)

| 모델 | positive 평균±표준편차 | negative 평균±표준편차 | 평균 차이 |
|------|--------------------:|--------------------:|--------:|
| kure | 0.5780 ± 0.0817 | 0.4062 ± 0.0585 | +0.1718 |

## 임계값별 필터링 효과

top-1 점수 < 임계값이면 'RAG OFF'로 판정한다고 가정.
셀 = negative 차단율 / positive 통과율 (둘 다 높을수록 좋음)

| 임계값 | kure |
|-------:|------:|
| 0.30 | 0% / 100% |
| 0.35 | 20% / 100% |
| 0.40 | 50% / 99% |
| 0.45 | 70% / 94% |
| 0.50 | 90% / 80% |
| 0.55 | 100% / 65% |
| 0.60 | 100% / 40% |
| 0.65 | 100% / 21% |
| 0.70 | 100% / 6% |

## R@5 미검색 질의 (모델별)

'완화 회수' = 엄격 기준으로는 놓쳤지만 같은 장의 형제 chunk는 top-k에 있음 (틀린 chunk가 아니라 같은 장의 다른 chunk를 준 경우).

- **kure**: 17개 (완화 회수 13개 / 진짜 실패 4개)
  - (definition) 상보적 염기쌍 규칙이 뭐지? [진짜 실패] → top-5: bmetb_ch05_terms, bmetb_ch07_s1, bmetb_ch04_s1, bmetb_ch13_terms, bmetb_ch13_summary
  - (principle) 선도가닥과 지연가닥이 왜 나뉘어? [완화 회수] → top-5: bmetb_ch06_s2, bmetb_ch10_summary, bmetb_ch16_s2, bmetb_ch16_s4_2, bmetb_ch04_summary
  - (definition) GPCR이 뭐야? [완화 회수] → top-5: bmetb_ch06_terms, bmetb_ch16_terms, bmetb_ch11_s1, biolec_p38_38, bmetb_ch16_s4
  - (definition) 에피토프가 뭐야? [완화 회수] → top-5: bmetb_ch08_terms, bmetb_ch08_summary, bmetb_ch20_terms, bmetb_ch20_s1, bmetb_ch20_summary
  - (comparison) 점착말단과 평활말단의 차이는? [완화 회수] → top-5: bmetb_ch10_summary, bmetb_ch12_s2, bmetb_ch14_terms, bmetb_ch19_s3, bmetb_ch18_s2
  - (principle) 청백 선별은 어떤 원리야? [진짜 실패] → top-5: bmetb_ch12_s1, bmetb_ch15_s3, bmetb_ch13_s3, bmetb_ch04_summary, bmetb_ch11_summary
  - (definition) 표적이탈 효과가 뭐야? [완화 회수] → top-5: bmetb_ch12_summary, bmetb_ch16_s1, bmetb_ch12_terms, bmetb_ch03_s2_2, bmetb_ch17_s2
  - (principle) 커버리지가 왜 중요해? [완화 회수] → top-5: bmetb_ch09_s2_2, bmetb_ch19_summary, biolec_p46_46, bmetb_ch13_summary, bmetb_ch10_s2
  - (definition) 항체약물접합체가 뭐야? [완화 회수] → top-5: bmetb_ch17_terms, bmetb_ch16_s2, bmetb_ch08_terms, bmetb_ch17_s2, bmetb_ch08_s2_2
  - (principle) 응력차폐가 왜 문제가 돼? [완화 회수] → top-5: bmetb_ch20_summary, bmetb_ch18_terms, bmetb_ch20_s1, bmetb_ch18_s3, bmetb_ch18_summary
  - (principle) CMRR이 왜 중요해? [진짜 실패] → top-5: biolec_p58_58, bmetb_ch11_s1, biolec_p37_37, bmetb_ch11_s1_2, bmetb_ch12_summary
  - (definition) 에일리어싱이 뭐지? [완화 회수] → top-5: bmetb_ch19_summary, bmetb_ch11_s3, bmetb_ch19_terms, bmetb_ch16_s4, bmetb_ch03_s1
  - (paraphrase) 유전자 하나에서 여러 종류 단백질이 나오게 하는 그 이어붙이기 [완화 회수] → top-5: bmetb_ch10_s4, biolec_p63_63, bmetb_ch04_s3, bmetb_ch10_intro, bmetb_ch05_s4
  - (paraphrase) 표본을 너무 띄엄띄엄 뽑아서 없던 낮은 주파수가 생기는 왜곡 [완화 회수] → top-5: bmetb_ch19_summary, bmetb_ch14_s1_2, bmetb_ch19_s2, bmetb_ch13_s2, bmetb_ch12_s2
  - (stt_noise) 자 씨에이치오 세포 그거 항체 만들 때 쓴다고 하셨는데 [진짜 실패] → top-5: bmetb_ch17_s2, biolec_p61_61, bmetb_ch08_s3, bmetb_ch03_intro, bmetb_ch14_terms
  - (stt_noise) 그 엘라이자 그 흡광도로 재는 그 정량법 맞나요 [완화 회수] → top-5: bmetb_ch11_summary, bmetb_ch09_summary, bmetb_ch11_s1_2, bmetb_ch19_summary, bmetb_ch10_summary
  - (stt_noise) 그 케이엘에이 그거 산소 전달 잘 되는지 보는 지표였나요 [완화 회수] → top-5: bmetb_ch03_summary, bmetb_ch14_terms, biolec_p54_54, bmetb_ch03_terms, bmetb_ch18_s4_2
