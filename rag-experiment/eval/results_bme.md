# 임베딩 모델 비교 평가 결과 (확장 지표)

- 질의 파일: `queries_bme_positive.json`, `queries_bme_hard.json` (index: `major_biomedical_bioengineering`) (총 136개) / top-k = 5
- 평가 모델: kure, bge-m3, openai
- Full-Recall@5: 정답 chunk 전부가 top-5에 포함된 질의 비율

## 전체 평균 (positive 질의만)

| 모델 | R@1 | R@3 | R@5 | MRR | Full-R@5 | n |
|------|----:|----:|----:|----:|------:|---:|
| kure | 0.690 | 0.833 | 0.857 | 0.760 | 0.762 | 126 |
| bge-m3 | 0.603 | 0.778 | 0.794 | 0.683 | 0.706 | 126 |
| openai | 0.563 | 0.730 | 0.833 | 0.665 | 0.762 | 126 |

## query_type별 분리 집계

| 모델 | query_type | R@1 | R@3 | R@5 | MRR | Full-R@5 | n |
|------|-----------|----:|----:|----:|----:|------:|---:|
| kure | comparison | 0.792 | 0.958 | 0.958 | 0.868 | 0.875 | 24 |
| kure | definition | 0.562 | 0.750 | 0.812 | 0.653 | 0.750 | 32 |
| kure | principle | 0.781 | 0.844 | 0.844 | 0.812 | 0.750 | 32 |
| kure | paraphrase | 0.708 | 0.917 | 0.917 | 0.806 | 0.833 | 24 |
| kure | stt_noise | 0.571 | 0.643 | 0.714 | 0.621 | 0.500 | 14 |
| bge-m3 | comparison | 0.667 | 0.875 | 0.875 | 0.771 | 0.792 | 24 |
| bge-m3 | definition | 0.438 | 0.625 | 0.688 | 0.535 | 0.625 | 32 |
| bge-m3 | principle | 0.750 | 0.812 | 0.812 | 0.776 | 0.750 | 32 |
| bge-m3 | paraphrase | 0.625 | 0.917 | 0.917 | 0.743 | 0.792 | 24 |
| bge-m3 | stt_noise | 0.500 | 0.643 | 0.643 | 0.560 | 0.500 | 14 |
| openai | comparison | 0.667 | 0.833 | 0.875 | 0.760 | 0.792 | 24 |
| openai | definition | 0.438 | 0.625 | 0.688 | 0.545 | 0.656 | 32 |
| openai | principle | 0.781 | 0.812 | 0.906 | 0.812 | 0.812 | 32 |
| openai | paraphrase | 0.458 | 0.750 | 0.958 | 0.643 | 0.833 | 24 |
| openai | stt_noise | 0.357 | 0.571 | 0.714 | 0.481 | 0.714 | 14 |

## top-1 유사도 점수 분포 (positive vs negative)

| 모델 | positive 평균±표준편차 | negative 평균±표준편차 | 평균 차이 |
|------|--------------------:|--------------------:|--------:|
| kure | 0.5704 ± 0.0856 | 0.3903 ± 0.0583 | +0.1801 |
| bge-m3 | 0.5703 ± 0.0886 | 0.4150 ± 0.0488 | +0.1553 |
| openai | 0.3989 ± 0.1105 | 0.1985 ± 0.0507 | +0.2004 |

## 임계값별 필터링 효과

top-1 점수 < 임계값이면 'RAG OFF'로 판정한다고 가정.
셀 = negative 차단율 / positive 통과율 (둘 다 높을수록 좋음)

| 임계값 | kure | bge-m3 | openai |
|-------:|------:|------:|------:|
| 0.30 | 0% / 100% | 0% / 100% | 90% / 79% |
| 0.35 | 30% / 100% | 0% / 100% | 100% / 62% |
| 0.40 | 70% / 98% | 50% / 96% | 100% / 49% |
| 0.45 | 80% / 91% | 80% / 89% | 100% / 34% |
| 0.50 | 90% / 75% | 90% / 79% | 100% / 20% |
| 0.55 | 100% / 60% | 100% / 62% | 100% / 11% |
| 0.60 | 100% / 37% | 100% / 39% | 100% / 3% |
| 0.65 | 100% / 20% | 100% / 20% | 100% / 1% |
| 0.70 | 100% / 6% | 100% / 7% | 100% / 0% |

## R@5 미검색 질의 (모델별)

- **kure**: 18개
  - (definition) 상보적 염기쌍 규칙이 뭐지? → top-5: bmetb_ch05_terms, bmetb_ch07_s1, bmetb_ch04_s1, bmetb_ch13_terms, bmetb_ch13_summary
  - (principle) 선도가닥과 지연가닥이 왜 나뉘어? → top-5: bmetb_ch06_s2, bmetb_ch10_summary, bmetb_ch16_s2, bmetb_ch16_s4_2, bmetb_ch04_summary
  - (definition) GPCR이 뭐야? → top-5: bmetb_ch06_terms, bmetb_ch16_terms, bmetb_ch11_s1, bmetb_ch16_s4, bmetb_ch15_s4
  - (definition) 에피토프가 뭐야? → top-5: bmetb_ch08_terms, bmetb_ch08_summary, bmetb_ch20_terms, bmetb_ch20_s1, bmetb_ch20_summary
  - (comparison) 점착말단과 평활말단의 차이는? → top-5: bmetb_ch10_summary, bmetb_ch12_s2, bmetb_ch14_terms, bmetb_ch19_s3, bmetb_ch18_s2
  - (principle) 청백 선별은 어떤 원리야? → top-5: bmetb_ch12_s1, bmetb_ch15_s3, bmetb_ch13_s3, bmetb_ch04_summary, bmetb_ch11_summary
  - (definition) 표적이탈 효과가 뭐야? → top-5: bmetb_ch12_summary, bmetb_ch16_s1, bmetb_ch12_terms, bmetb_ch03_s2_2, bmetb_ch17_s2
  - (principle) 커버리지가 왜 중요해? → top-5: bmetb_ch09_s2_2, bmetb_ch19_summary, bmetb_ch13_summary, bmetb_ch10_s2, bmetb_ch16_s1
  - (definition) 항체약물접합체가 뭐야? → top-5: bmetb_ch17_terms, bmetb_ch16_s2, bmetb_ch08_terms, bmetb_ch17_s2, bmetb_ch08_s2_2
  - (principle) 응력차폐가 왜 문제가 돼? → top-5: bmetb_ch20_summary, bmetb_ch18_terms, bmetb_ch20_s1, bmetb_ch18_s3, bmetb_ch18_summary
  - (principle) CMRR이 왜 중요해? → top-5: bmetb_ch11_s1, bmetb_ch11_s1_2, bmetb_ch12_summary, bmetb_ch12_s1, bmetb_ch19_summary
  - (definition) 에일리어싱이 뭐지? → top-5: bmetb_ch19_summary, bmetb_ch11_s3, bmetb_ch19_terms, bmetb_ch16_s4, bmetb_ch03_s1
  - (paraphrase) 유전자 하나에서 여러 종류 단백질이 나오게 하는 그 이어붙이기 → top-5: bmetb_ch10_s4, bmetb_ch04_s3, bmetb_ch10_intro, bmetb_ch05_s4, bmetb_ch10_terms
  - (paraphrase) 표본을 너무 띄엄띄엄 뽑아서 없던 낮은 주파수가 생기는 왜곡 → top-5: bmetb_ch19_summary, bmetb_ch14_s1_2, bmetb_ch19_s2, bmetb_ch13_s2, bmetb_ch12_s2
  - (stt_noise) 그 엠아르엔에이 인가 그 전령 알엔에이가 정보 나른다고 했잖아요 → top-5: bmetb_ch13_summary, bmetb_ch08_summary, bmetb_ch13_s2, bmetb_ch06_intro, bmetb_ch08_s3
  - (stt_noise) 자 씨에이치오 세포 그거 항체 만들 때 쓴다고 하셨는데 → top-5: bmetb_ch17_s2, bmetb_ch08_s3, bmetb_ch08_summary, bmetb_ch17_terms, bmetb_ch08_s4
  - (stt_noise) 그 엘라이자 그 흡광도로 재는 그 정량법 맞나요 → top-5: bmetb_ch09_summary, bmetb_ch11_summary, bmetb_ch19_summary, bmetb_ch11_s1_2, bmetb_ch10_summary
  - (stt_noise) 그 케이엘에이 그거 산소 전달 잘 되는지 보는 지표였나요 → top-5: bmetb_ch03_summary, bmetb_ch03_terms, bmetb_ch07_s3, bmetb_ch14_terms, bmetb_ch11_s1_2
- **bge-m3**: 26개
  - (definition) 상보적 염기쌍 규칙이 뭐지? → top-5: bmetb_ch05_terms, bmetb_ch04_s3, bmetb_ch15_terms, bmetb_ch07_s1, bmetb_ch04_terms
  - (principle) 선도가닥과 지연가닥이 왜 나뉘어? → top-5: bmetb_ch06_s2, bmetb_ch15_s1, bmetb_ch10_summary, bmetb_ch05_s1, bmetb_ch10_terms
  - (comparison) 인트론과 엑손의 차이가 뭐지? → top-5: bmetb_ch11_s2, bmetb_ch19_s3, bmetb_ch04_terms, bmetb_ch09_s2_2, bmetb_ch18_s2
  - (comparison) 침투도와 발현도의 차이는? → top-5: bmetb_ch08_s1, bmetb_ch09_s4, bmetb_ch04_s4, bmetb_ch08_summary, bmetb_ch15_s1
  - (definition) GPCR이 뭐야? → top-5: bmetb_ch11_s1, bmetb_ch06_terms, bmetb_ch15_s4, bmetb_ch16_terms, bmetb_ch11_s1_2
  - (definition) 에피토프가 뭐야? → top-5: bmetb_ch08_terms, bmetb_ch08_summary, bmetb_ch20_terms, bmetb_ch17_terms, bmetb_ch17_s1
  - (definition) 단일클론항체가 뭔가요? → top-5: bmetb_ch08_summary, bmetb_ch08_terms, bmetb_ch08_s1, bmetb_ch17_s2, bmetb_ch08_s3
  - (comparison) 점착말단과 평활말단의 차이는? → top-5: bmetb_ch10_summary, bmetb_ch18_s1, bmetb_ch01_s2, bmetb_ch01_s4, bmetb_ch14_terms
  - (principle) 청백 선별은 어떤 원리야? → top-5: bmetb_ch15_s3, bmetb_ch04_intro, bmetb_ch12_s1, bmetb_ch04_terms, bmetb_ch04_summary
  - (definition) ELISA가 뭐지? → top-5: bmetb_ch03_s1, bmetb_ch14_terms, bmetb_ch09_s3, bmetb_ch17_s4, bmetb_ch11_s2
  - (definition) 표적이탈 효과가 뭐야? → top-5: bmetb_ch12_summary, bmetb_ch16_s1, bmetb_ch09_s4, bmetb_ch03_summary, bmetb_ch16_terms
  - (principle) 커버리지가 왜 중요해? → top-5: bmetb_ch10_s2, bmetb_ch14_s4, bmetb_ch19_summary, bmetb_ch15_s4, bmetb_ch14_terms
  - (definition) 치료지수가 뭐지? → top-5: bmetb_ch17_s3, bmetb_ch17_terms, bmetb_ch18_s4, bmetb_ch16_terms, bmetb_ch20_s3
  - (definition) 항체약물접합체가 뭐야? → top-5: bmetb_ch17_terms, bmetb_ch16_s2, bmetb_ch17_s2, bmetb_ch08_terms, bmetb_ch08_s1
  - (principle) 응력차폐가 왜 문제가 돼? → top-5: bmetb_ch20_summary, bmetb_ch18_s3, bmetb_ch18_terms, bmetb_ch20_s1, bmetb_ch14_s4
  - (principle) CMRR이 왜 중요해? → top-5: bmetb_ch11_s1, bmetb_ch11_s1_2, bmetb_ch12_summary, bmetb_ch12_s1, bmetb_ch12_intro
  - (definition) 에일리어싱이 뭐지? → top-5: bmetb_ch19_summary, bmetb_ch16_s4, bmetb_ch11_s3, bmetb_ch03_s1, bmetb_ch11_s2
  - (definition) 점탄성이 무슨 성질이야? → top-5: bmetb_ch02_s4, bmetb_ch07_terms, bmetb_ch02_terms, bmetb_ch01_s4, bmetb_ch01_summary
  - (principle) 혈액투석은 어떤 원리로 작동해? → top-5: bmetb_ch20_terms, bmetb_ch20_s1, bmetb_ch07_s3, bmetb_ch18_s4, bmetb_ch04_intro
  - (paraphrase) 유전자 하나에서 여러 종류 단백질이 나오게 하는 그 이어붙이기 → top-5: bmetb_ch10_s4, bmetb_ch10_intro, bmetb_ch05_terms, bmetb_ch05_s4, bmetb_ch02_s2
  - (paraphrase) 표본을 너무 띄엄띄엄 뽑아서 없던 낮은 주파수가 생기는 왜곡 → top-5: bmetb_ch19_summary, bmetb_ch19_s2, bmetb_ch14_s1_2, bmetb_ch12_s2, bmetb_ch13_s2
  - (stt_noise) 어 그 피시알 그거 변성 결합 신장 이렇게 세 단계라 했나요 → top-5: bmetb_ch03_s4, bmetb_ch06_s1, bmetb_ch03_terms, bmetb_ch11_summary, bmetb_ch03_summary
  - (stt_noise) 그 엠아르엔에이 인가 그 전령 알엔에이가 정보 나른다고 했잖아요 → top-5: bmetb_ch08_summary, bmetb_ch13_summary, bmetb_ch04_s2, bmetb_ch06_terms, bmetb_ch06_intro
  - (stt_noise) 자 씨에이치오 세포 그거 항체 만들 때 쓴다고 하셨는데 → top-5: bmetb_ch17_s2, bmetb_ch08_s3, bmetb_ch08_summary, bmetb_ch08_s1, bmetb_ch08_s2
  - (stt_noise) 그 엘라이자 그 흡광도로 재는 그 정량법 맞나요 → top-5: bmetb_ch09_summary, bmetb_ch19_summary, bmetb_ch11_summary, bmetb_ch11_s2, bmetb_ch10_summary
  - (stt_noise) 그 케이엘에이 그거 산소 전달 잘 되는지 보는 지표였나요 → top-5: bmetb_ch07_s3, bmetb_ch19_terms, bmetb_ch16_s2, bmetb_ch03_summary, bmetb_ch03_terms
- **openai**: 21개
  - (definition) 상보적 염기쌍 규칙이 뭐지? → top-5: bmetb_ch11_s2, bmetb_ch03_s3, bmetb_ch03_s2, bmetb_ch03_s3_2, bmetb_ch11_terms
  - (principle) 선도가닥과 지연가닥이 왜 나뉘어? → top-5: bmetb_ch05_s2, bmetb_ch05_terms, bmetb_ch04_s4, bmetb_ch02_s3, bmetb_ch05_s1
  - (comparison) 인트론과 엑손의 차이가 뭐지? → top-5: bmetb_ch12_s4, bmetb_ch12_terms, bmetb_ch12_intro, bmetb_ch01_s2, bmetb_ch08_s1
  - (definition) 보인자가 무슨 뜻이야? → top-5: bmetb_ch09_s2_2, bmetb_ch08_terms, bmetb_ch03_s2, bmetb_ch19_terms, bmetb_ch06_terms
  - (comparison) 침투도와 발현도의 차이는? → top-5: bmetb_ch19_s3, bmetb_ch10_s3, bmetb_ch03_s4, bmetb_ch05_s2, bmetb_ch01_terms
  - (principle) 네프론은 어떻게 오줌을 만들어? → top-5: bmetb_ch04_s2, bmetb_ch10_s4, bmetb_ch15_s2, bmetb_ch14_s1_2, bmetb_ch14_s1
  - (definition) 에피토프가 뭐야? → top-5: bmetb_ch09_terms, bmetb_ch19_terms, bmetb_ch17_terms, bmetb_ch04_terms, bmetb_ch12_terms
  - (definition) 플라스미드가 뭐지? → top-5: bmetb_ch14_s4, bmetb_ch09_terms, bmetb_ch12_s4, bmetb_ch14_s1_2, bmetb_ch06_s3
  - (comparison) 점착말단과 평활말단의 차이는? → top-5: bmetb_ch10_s3, bmetb_ch10_terms, bmetb_ch11_terms, bmetb_ch18_s3, bmetb_ch18_s1
  - (definition) His-태그가 뭔가요? → top-5: bmetb_ch10_terms, bmetb_ch15_s3, bmetb_ch12_terms, bmetb_ch10_s1, bmetb_ch11_terms
  - (definition) 표적이탈 효과가 뭐야? → top-5: bmetb_ch16_s1, bmetb_ch06_terms, bmetb_ch03_s2_2, bmetb_ch16_terms, bmetb_ch18_s4_2
  - (definition) 치료지수가 뭐지? → top-5: bmetb_ch19_terms, bmetb_ch17_terms, bmetb_ch17_s3, bmetb_ch20_s2, bmetb_ch17_summary
  - (definition) 항체약물접합체가 뭐야? → top-5: bmetb_ch17_s2, bmetb_ch08_terms, bmetb_ch08_s4, bmetb_ch08_s2_2, bmetb_ch08_intro
  - (principle) 응력차폐가 왜 문제가 돼? → top-5: bmetb_ch14_s4, bmetb_ch14_s1_2, bmetb_ch14_s3, bmetb_ch03_s1, bmetb_ch11_s2
  - (definition) 점탄성이 무슨 성질이야? → top-5: bmetb_ch02_s3, bmetb_ch19_s3, bmetb_ch02_terms, bmetb_ch06_s4, bmetb_ch18_s4_2
  - (definition) 볼프의 법칙이 뭐야? → top-5: bmetb_ch20_summary, bmetb_ch05_s1, bmetb_ch20_terms, bmetb_ch04_s1, bmetb_ch03_s3_2
  - (paraphrase) 표본을 너무 띄엄띄엄 뽑아서 없던 낮은 주파수가 생기는 왜곡 → top-5: bmetb_ch19_s2, bmetb_ch14_s1_2, bmetb_ch19_terms, bmetb_ch19_summary, bmetb_ch11_s4
  - (stt_noise) 어 그 피시알 그거 변성 결합 신장 이렇게 세 단계라 했나요 → top-5: bmetb_ch14_s4, bmetb_ch14_summary, bmetb_ch14_intro, bmetb_ch02_s2, bmetb_ch14_terms
  - (stt_noise) 그 엠아르엔에이 인가 그 전령 알엔에이가 정보 나른다고 했잖아요 → top-5: bmetb_ch13_s3, bmetb_ch13_terms, bmetb_ch13_summary, bmetb_ch13_s4, bmetb_ch04_s2
  - (stt_noise) 음 엠에이치씨 클래스 원이랑 투 그거 뭐가 다른 거였나 → top-5: bmetb_ch05_s1, bmetb_ch12_s4, bmetb_ch01_s2, bmetb_ch12_terms, bmetb_ch02_intro
  - (stt_noise) 자 씨에이치오 세포 그거 항체 만들 때 쓴다고 하셨는데 → top-5: bmetb_ch17_s2, bmetb_ch17_terms, bmetb_ch08_s3, bmetb_ch08_s4, bmetb_ch17_s1
