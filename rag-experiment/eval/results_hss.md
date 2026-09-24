# 임베딩 모델 비교 평가 결과 (확장 지표)

- 질의 파일: `queries_hss_positive.json`, `queries_hss_hard.json` (index: `major_humanities_social_sciences`) (총 105개) / top-k = 5
- 평가 모델: kure, bge-m3, openai
- Full-Recall@5: 정답 chunk 전부가 top-5에 포함된 질의 비율

## 전체 평균 (positive 질의만)

| 모델 | R@1 | R@3 | R@5 | MRR | Full-R@5 | n |
|------|----:|----:|----:|----:|------:|---:|
| kure | 0.811 | 0.968 | 1.000 | 0.890 | 0.926 | 95 |
| bge-m3 | 0.832 | 0.937 | 0.958 | 0.882 | 0.863 | 95 |
| openai | 0.663 | 0.832 | 0.884 | 0.758 | 0.821 | 95 |

## query_type별 분리 집계

| 모델 | query_type | R@1 | R@3 | R@5 | MRR | Full-R@5 | n |
|------|-----------|----:|----:|----:|----:|------:|---:|
| kure | definition | 0.750 | 0.958 | 1.000 | 0.858 | 0.958 | 24 |
| kure | comparison | 0.857 | 0.952 | 1.000 | 0.917 | 0.905 | 21 |
| kure | principle | 0.750 | 1.000 | 1.000 | 0.867 | 0.900 | 20 |
| kure | paraphrase | 0.778 | 0.944 | 1.000 | 0.854 | 0.944 | 18 |
| kure | stt_noise | 1.000 | 1.000 | 1.000 | 1.000 | 0.917 | 12 |
| bge-m3 | definition | 0.750 | 0.958 | 1.000 | 0.844 | 0.958 | 24 |
| bge-m3 | comparison | 0.952 | 0.952 | 0.952 | 0.952 | 0.857 | 21 |
| bge-m3 | principle | 0.800 | 1.000 | 1.000 | 0.892 | 0.800 | 20 |
| bge-m3 | paraphrase | 0.778 | 0.778 | 0.833 | 0.789 | 0.833 | 18 |
| bge-m3 | stt_noise | 0.917 | 1.000 | 1.000 | 0.958 | 0.833 | 12 |
| openai | definition | 0.583 | 0.792 | 0.833 | 0.691 | 0.792 | 24 |
| openai | comparison | 0.714 | 0.810 | 0.857 | 0.771 | 0.810 | 21 |
| openai | principle | 0.800 | 0.900 | 1.000 | 0.872 | 0.850 | 20 |
| openai | paraphrase | 0.611 | 0.778 | 0.778 | 0.694 | 0.778 | 18 |
| openai | stt_noise | 0.583 | 0.917 | 1.000 | 0.771 | 0.917 | 12 |

## top-1 유사도 점수 분포 (positive vs negative)

| 모델 | positive 평균±표준편차 | negative 평균±표준편차 | 평균 차이 |
|------|--------------------:|--------------------:|--------:|
| kure | 0.5959 ± 0.0779 | 0.3899 ± 0.0429 | +0.2060 |
| bge-m3 | 0.5958 ± 0.0806 | 0.4021 ± 0.0383 | +0.1937 |
| openai | 0.4096 ± 0.1064 | 0.2172 ± 0.0448 | +0.1924 |

## 임계값별 필터링 효과

top-1 점수 < 임계값이면 'RAG OFF'로 판정한다고 가정.
셀 = negative 차단율 / positive 통과율 (둘 다 높을수록 좋음)

| 임계값 | kure | bge-m3 | openai |
|-------:|------:|------:|------:|
| 0.30 | 0% / 100% | 0% / 100% | 100% / 84% |
| 0.35 | 20% / 100% | 10% / 100% | 100% / 67% |
| 0.40 | 50% / 100% | 50% / 100% | 100% / 49% |
| 0.45 | 100% / 99% | 90% / 99% | 100% / 35% |
| 0.50 | 100% / 91% | 100% / 86% | 100% / 22% |
| 0.55 | 100% / 69% | 100% / 71% | 100% / 11% |
| 0.60 | 100% / 44% | 100% / 43% | 100% / 6% |
| 0.65 | 100% / 27% | 100% / 22% | 100% / 1% |
| 0.70 | 100% / 9% | 100% / 14% | 100% / 0% |

## R@5 미검색 질의 (모델별)

- **kure**: 없음
- **bge-m3**: 4개
  - (comparison) 재현율과 정밀도는 어떻게 다르지? → top-5: hsstb_ch03_s1, hsstb_ch04_summary, hsstb_ch03_summary, hsstb_ch04_s2, hsstb_ch03_terms
  - (paraphrase) 내가 어떤 처지로 태어날지 모른 채 사회 규칙을 고르라는 그 가정 → top-5: hsstb_ch10_s1, hsstb_ch10_intro, hsstb_ch10_s4, hsstb_ch15_s1, hsstb_ch08_s3
  - (paraphrase) 슬롯머신이 언제 터질지 모르니까 계속 하게 되는 그 원리 → top-5: hsstb_ch05_s3, hsstb_ch05_s4, hsstb_ch04_s4, hsstb_ch11_s1, hsstb_ch12_s4
  - (paraphrase) 찾아낸 것 중 맞는 비율이랑 있는 것 중 찾아낸 비율이 서로 상충한다는 그거 → top-5: hsstb_ch03_s1, hsstb_ch03_intro, hsstb_ch05_s4, hsstb_ch03_summary, hsstb_ch03_s2
- **openai**: 11개
  - (definition) 문화자본이 뭐지? → top-5: hsstb_ch15_s1, hsstb_ch15_terms, hsstb_ch15_summary, hsstb_ch15_intro, hsstb_ch15_s2
  - (definition) 정언명령이 뭐야? → top-5: hsstb_ch14_s3, hsstb_ch14_intro, hsstb_ch14_terms, hsstb_ch18_terms, hsstb_ch14_s1
  - (definition) 무지의 베일이 무슨 뜻이야? → top-5: hsstb_ch19_s4_2, hsstb_ch19_terms, hsstb_ch04_terms, hsstb_ch14_s4, hsstb_ch18_terms
  - (definition) 조작적 정의가 뭐야? → top-5: hsstb_ch02_terms, hsstb_ch07_s3, hsstb_ch08_terms, hsstb_ch07_terms, hsstb_ch14_terms
  - (comparison) 에믹과 에틱 관점은 뭐가 달라? → top-5: hsstb_ch11_s3, hsstb_ch07_terms, hsstb_ch11_terms, hsstb_ch15_s2, hsstb_ch07_s1
  - (comparison) 의미론과 화용론은 어떻게 구분되나? → top-5: hsstb_ch05_s4, hsstb_ch05_s1, hsstb_ch06_s1, hsstb_ch05_terms, hsstb_ch05_summary
  - (comparison) 재현율과 정밀도는 어떻게 다르지? → top-5: hsstb_ch03_s1, hsstb_ch02_s4, hsstb_ch02_s3, hsstb_ch06_s1, hsstb_ch05_s4
  - (paraphrase) 다섯 명 살리려고 한 명 희생시키는 게 맞냐고 묻는 그 사고실험 → top-5: hsstb_ch08_s3, hsstb_ch06_terms, hsstb_ch07_s1, hsstb_ch06_s3, hsstb_ch08_s4
  - (paraphrase) 내가 어떤 처지로 태어날지 모른 채 사회 규칙을 고르라는 그 가정 → top-5: hsstb_ch10_intro, hsstb_ch10_s1, hsstb_ch09_s1, hsstb_ch10_terms, hsstb_ch10_s4
  - (paraphrase) 개를 영어로는 dog라 부르는 게 필연이 아니라 약속이라는 얘기 → top-5: hsstb_ch18_s4_2, hsstb_ch18_terms, hsstb_ch06_s3, hsstb_ch18_s4, hsstb_ch18_intro
  - (paraphrase) 찾아낸 것 중 맞는 비율이랑 있는 것 중 찾아낸 비율이 서로 상충한다는 그거 → top-5: hsstb_ch04_s4, hsstb_ch04_s3, hsstb_ch03_terms, hsstb_ch03_s1, hsstb_ch04_s2
