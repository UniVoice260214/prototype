# 교재 질의 하드 버전 평가 (paraphrase 24 / stt_noise 24)

- 질의 파일: `queries_textbook_hard.json` / 인덱스: major_ai (310 chunks) / top-k = 5
- 원본 `queries_textbook.json` 24개와 정답 라벨 동일, 표현만 우회·STT풍으로 변형

## 모델 × 유형 지표

| 모델 | 유형 | R@1 | R@3 | R@5 | MRR | n |
|------|------|----:|----:|----:|----:|---:|
| kure | 전체(hard) | 0.583 | 0.750 | 0.854 | 0.685 | 48 |
| kure | paraphrase | 0.542 | 0.750 | 0.875 | 0.668 | 24 |
| kure | stt_noise | 0.625 | 0.750 | 0.833 | 0.701 | 24 |
| kure | (원본 24) | 0.958 | 1.000 | 1.000 | 0.979 | 24 |
| bge-m3 | 전체(hard) | 0.562 | 0.688 | 0.792 | 0.639 | 48 |
| bge-m3 | paraphrase | 0.500 | 0.667 | 0.833 | 0.603 | 24 |
| bge-m3 | stt_noise | 0.625 | 0.708 | 0.750 | 0.675 | 24 |
| bge-m3 | (원본 24) | 0.958 | 1.000 | 1.000 | 0.979 | 24 |
| openai | 전체(hard) | 0.583 | 0.729 | 0.771 | 0.663 | 48 |
| openai | paraphrase | 0.625 | 0.750 | 0.792 | 0.698 | 24 |
| openai | stt_noise | 0.542 | 0.708 | 0.750 | 0.628 | 24 |
| openai | (원본 24) | 0.792 | 0.917 | 0.958 | 0.851 | 24 |

## R@5 미검색 질의

- **kure**: 7개
  - (paraphrase) 테스트에서만 알 수 있어야 하는 정보가 학습 과정에 몰래 섞여 들어가서 성능이 부풀려지는 문제가 뭐야? → top-5: tb_ch05_s5, concept_ch3_s2, concept_ch10_s3, tb_ch16_s1, concept_ch4_s1
  - (stt_noise) 에이치엔에스더블유 그게 뭐 하는 거라고 했죠 → top-5: concept_ch1_s4, glossary_ann, tb_ch10_intro, glossary_xai, tb_ch01_terms
  - (paraphrase) 임베딩 벡터로 찾는 검색하고 키워드 일치로 찾는 검색은 뭐가 다르고 둘을 섞으면 뭐라고 해? → top-5: tb_ch15_s1_2, tb_ch15_terms, tb_ch15_summary, tb_ch15_s2, tb_ch15_s1
  - (stt_noise) 하이어라키컬 클러스터링하고 케이민즈 뭐가 다르다 했죠 → top-5: tb_ch08_terms, tb_ch08_summary, tb_ch08_s1, concept_ch9_s3, tb_ch07_terms
  - (stt_noise) 케이민즈 그거 어떤 순서로 돌아간다 했죠 → top-5: tb_ch07_s1, tb_ch07_summary, concept_ch7_s2, tb_ch07_s3, concept_ch7_s3
  - (paraphrase) 큰 데이터로 미리 학습해둔 모델을 가져와서 내 문제에 맞게 조금만 다시 학습시키는 건 어떻게 되는 거야? → top-5: concept_ch8_s1, tb_ch11_s5, glossary_llm, tb_ch14_s5, tb_ch05_s5
  - (stt_noise) 트랜스퍼 러닝 그거 원리가 뭐라 했죠 → top-5: concept_ch7_s4, glossary_transformer, tb_ch14_intro, concept_ch8_s1, tb_ch05_s5
- **bge-m3**: 10개
  - (paraphrase) 테스트에서만 알 수 있어야 하는 정보가 학습 과정에 몰래 섞여 들어가서 성능이 부풀려지는 문제가 뭐야? → top-5: tb_ch05_s5, concept_ch10_s3, concept_ch3_s2, concept_ch4_s1, glossary_overfitting
  - (stt_noise) 에이치엔에스더블유 그게 뭐 하는 거라고 했죠 → top-5: tb_ch02_s1, concept_ch1_s4, tb_ch10_intro, tb_ch01_terms, glossary_ann
  - (paraphrase) 임베딩 벡터로 찾는 검색하고 키워드 일치로 찾는 검색은 뭐가 다르고 둘을 섞으면 뭐라고 해? → top-5: tb_ch15_s1_2, tb_ch15_summary, tb_ch15_terms, tb_ch15_s1, tb_ch15_s2
  - (stt_noise) 하이어라키컬 클러스터링하고 케이민즈 뭐가 다르다 했죠 → top-5: concept_ch6_s2, concept_ch9_s3, tb_ch08_s1, tb_ch08_terms, tb_ch08_summary
  - (stt_noise) 케이민즈 그거 어떤 순서로 돌아간다 했죠 → top-5: tb_ch07_s1, tb_ch07_summary, concept_ch7_s2, concept_ch13_s2, tb_ch07_s3
  - (paraphrase) 질문이 들어오면 관련 문서를 찾아서 프롬프트에 붙여 답을 만들게 하는 시스템은 단계가 어떻게 돼? → top-5: glossary_prompt, tb_ch16_s5, tb_ch16_terms, tb_ch16_summary, tb_ch16_terms_2
  - (paraphrase) 큰 데이터로 미리 학습해둔 모델을 가져와서 내 문제에 맞게 조금만 다시 학습시키는 건 어떻게 되는 거야? → top-5: concept_ch8_s1, tb_ch11_s5, concept_ch8_s2, glossary_llm, tb_ch05_s5
  - (stt_noise) 트랜스퍼 러닝 그거 원리가 뭐라 했죠 → top-5: concept_ch7_s4, tb_ch05_s5, tb_ch05_intro, tb_ch05_s1, glossary_transformer
  - (stt_noise) 러닝레이트 스케줄링인가 그거 왜 쓴다고 했죠 → top-5: tb_ch05_s1, tb_ch05_s3, concept_ch1_s2, tb_ch05_s5, concept_ch7_s2
  - (stt_noise) 데이터 어그멘테이션 그게 왜 효과 있다고 했죠 → top-5: tb_ch16_s1, tb_ch05_s5, concept_ch7_s3, concept_ch3_s2, tb_ch13_summary
- **openai**: 11개
  - (stt_noise) 알오씨 커브랑 에이유씨 그거 뭐였죠 → top-5: glossary_intelligent_agent, glossary_agent_program, glossary_xai, tb_ch01_s6, tb_ch01_s1
  - (stt_noise) 데이터 리키지인가 리케이지인가 그게 무슨 문제라고 했어요 → top-5: concept_ch8_s5, glossary_vector_database, tb_ch07_s1, concept_ch9_s4, tb_ch06_s6
  - (stt_noise) 에이치엔에스더블유 그게 뭐 하는 거라고 했죠 → top-5: glossary_ensemble, glossary_self_attention, glossary_softmax, glossary_xai, glossary_a_star
  - (paraphrase) 임베딩 벡터로 찾는 검색하고 키워드 일치로 찾는 검색은 뭐가 다르고 둘을 섞으면 뭐라고 해? → top-5: tb_ch15_terms, tb_ch15_summary, tb_ch15_s1_2, tb_ch15_s3, tb_ch15_s1
  - (stt_noise) 엠에이이랑 알엠에스이 차이가 뭐라 했죠 → top-5: concept_ch0_s1, concept_ch1_s4, tb_ch01_terms, concept_ch1_s1, tb_ch01_s1
  - (stt_noise) 케이민즈 그거 어떤 순서로 돌아간다 했죠 → top-5: tb_ch13_s5, concept_ch13_s2, tb_ch13_s1, tb_ch13_terms, tb_ch13_summary
  - (paraphrase) 쿼리랑 키를 내적하고 차원 수의 제곱근으로 나눠서 소프트맥스 하는 그 계산은 뭘 구하는 거야? → top-5: glossary_softmax, tb_ch15_terms_2, tb_ch08_s2, tb_ch08_s4, tb_ch08_s1
  - (paraphrase) 질문이 들어오면 관련 문서를 찾아서 프롬프트에 붙여 답을 만들게 하는 시스템은 단계가 어떻게 돼? → top-5: tb_ch16_s5, tb_ch16_s2_2, tb_ch16_terms, tb_ch14_s6, tb_ch16_terms_2
  - (paraphrase) 목표까지 남은 비용을 절대 과대평가하지 않는 추정 함수가 왜 필요하다고 했지? → top-5: tb_ch09_intro, tb_ch09_summary, glossary_heuristic, tb_ch05_s4, tb_ch09_s5
  - (paraphrase) 큰 데이터로 미리 학습해둔 모델을 가져와서 내 문제에 맞게 조금만 다시 학습시키는 건 어떻게 되는 거야? → top-5: concept_ch8_s2, glossary_pretraining, glossary_finetuning, tb_ch11_s5, tb_ch14_s5
  - (stt_noise) 트랜스퍼 러닝 그거 원리가 뭐라 했죠 → top-5: concept_ch7_s4, glossary_transformer, tb_ch13_s5, tb_ch14_terms, tb_ch14_intro
