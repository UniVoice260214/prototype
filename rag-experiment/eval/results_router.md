# RAG Router 평가

- 모델: kure / score gate 임계값: 0.5 (통합 인덱스 top-1)
- 라벨 데이터: positive 171 / negative 10 / 발화형 테스트 문장 31

## 1. 단계별 라우팅 정확도

| 단계 | positive ON (재현율) | negative OFF (차단율) |
|------|----:|----:|
| rule만 | 155/171 (90.6%) | 10/10 (100.0%) |
| rule + score gate | 155/171 (90.6%) | 10/10 (100.0%) |

### rule 미발동 positive (트리거 사각지대)

- 진공청소기 문제의 상태는 몇 가지야?
- 손실이 줄어드는 방향으로 값을 조금씩 바꿔가며 최적값을 찾는 방법이 뭐야?
- 층이 깊어질수록 앞쪽 층이 거의 학습되지 않는 문제는 왜 생겨?
- 학습할 때 뉴런 일부를 무작위로 꺼버리는 기법이 뭐지?
- 정답지를 주고 가르치는 방식과 상벌로 가르치는 방식은 뭐가 달라?
- 외부 문서를 찾아와서 그걸 근거로 답을 만들게 하는 방법이 뭐야?
- 센서로 주변을 인식하고 스스로 다음 행동을 결정하는 프로그램을 수업에서 뭐라고 했지?
- 보폭이 너무 넓으면 최저점을 지나쳐버리는데, 이때 뭘 조절해야 해?
- 테스트에서만 알 수 있어야 하는 정보가 학습 과정에 몰래 섞여 들어가서 성능이 부풀려지는 문제가 뭐야?
- 군집 개수를 늘려가며 그래프를 그려서 꺾이는 지점으로 개수를 정하는 방법이 뭐지?
- 벡터 검색 빠르게 하려고 여러 층짜리 그래프를 만들어서 위에서부터 좁혀 내려가는 색인 방식이 뭐야?
- 개념들 사이의 관계를 체계적으로 정리해서 지식을 조직화하는 걸 뭐라고 부르지?
- 회귀 평가할 때 오차 절댓값을 평균 내는 지표하고 제곱해서 루트 씌우는 지표는 뭐가 달라?
- 사실에서 출발해서 결론으로 가는 추론하고 목표에서 거꾸로 조건을 확인해가는 추론은 뭐가 달라?
- 목표까지 남은 비용을 절대 과대평가하지 않는 추정 함수가 왜 필요하다고 했지?
- 긴 문서를 검색용으로 자를 때 어떤 식으로 자르는 방법들이 있어?

### score gate가 끈 positive (과차단)

- 없음

## 2. 발화형 테스트 문장 판정

| 판정 | 기대 | 실제 | score | reason | 문장 |
|:--:|:--:|:--:|----:|------|------|
| ✅ | true | true | 0.666 | GLOSSARY_TERM,LECTURE_CONCEPT | 자 그래서 컨볼루션이 이미지에서 특징을 뽑아낸다고 했죠 |
| ✅ | true | true | 0.705 | GLOSSARY_TERM | 오늘은 경사하강법이 손실을 어떻게 줄이는지 볼 겁니다 |
| ✅ | true | true | 0.728 | GLOSSARY_TERM,LECTURE_CONCEPT | 케이민즈는 중심점을 반복해서 갱신하면서 군집을 나눕니다 |
| ✅ | true | true | 0.631 | GLOSSARY_TERM | 여기서 과적합이 발생하면 검증 성능이 뚝 떨어져요 |
| ✅ | true | true | 0.664 | GLOSSARY_TERM | 트랜스포머는 순환 구조 없이 어텐션만으로 문맥을 봅니다 |
| ✅ | true | true | 0.719 | GLOSSARY_TERM | 래그는 검색된 문서를 프롬프트에 넣어서 환각을 줄이는 거예요 |
| ✅ | true | true | 0.686 | GLOSSARY_TERM,LECTURE_CONCEPT | 엘에스티엠은 게이트 세 개로 정보 흐름을 조절합니다 |
| ✅ | true | true | 0.802 | GLOSSARY_TERM | 시그모이드는 출력을 0과 1 사이로 눌러주는 함수예요 |
| ✅ | true | true | 0.722 | GLOSSARY_TERM | 휴리스틱이 실제 비용을 넘지 않으면 에이스타가 최적해를 보장합니다 |
| ✅ | true | true | 0.639 | GLOSSARY_TERM | 정밀도하고 재현율은 서로 트레이드오프 관계입니다 |
| ✅ | true | true | 0.630 | GLOSSARY_TERM,LECTURE_CONCEPT | 임베딩끼리는 코사인 유사도로 비교한다고 했죠 |
| ✅ | true | true | 0.781 | GLOSSARY_TERM,LECTURE_CONCEPT | 지도학습은 정답 레이블이 붙은 데이터로 배우는 방식이에요 |
| ✅ | true | true | 0.743 | GLOSSARY_TERM | 드롭아웃을 걸면 학습할 때 뉴런 일부를 랜덤하게 꺼버립니다 |
| ✅ | true | true | 0.672 | GLOSSARY_TERM | 빔 서치는 후보 문장을 여러 개 들고 가면서 생성해요 |
| ✅ | true | true | 0.781 | LECTURE_CONCEPT | 차원의 저주 때문에 특징이 많아지면 데이터가 모자라게 됩니다 |
| ✅ | true | true | 0.604 | GLOSSARY_TERM,LECTURE_CONCEPT | 트랜스퍼 러닝으로 사전학습된 모델을 가져다 쓰면 됩니다 |
| ✅ | true | true | 0.765 | GLOSSARY_TERM | 배치 정규화는 각 층에 들어가는 입력 분포를 안정화시켜 줍니다 |
| ✅ | true | true | 0.732 | GLOSSARY_TERM | 퍼셉트론이 신경망을 이루는 가장 작은 단위입니다 |
| ✅ | false | false | - | NO_TRIGGER | 자 출석 부르겠습니다 이름 들리면 대답해 주세요 |
| ✅ | false | false | - | NO_TRIGGER | 다음 주 수요일까지 과제 올려 주세요 |
| ✅ | false | false | - | NO_TRIGGER | 중간고사는 4월 셋째 주에 봅니다 |
| ✅ | false | false | - | NO_TRIGGER | 뒤에까지 잘 들리나요 마이크 좀 확인할게요 |
| ✅ | false | false | - | NO_TRIGGER | 오늘 좀 더우니까 에어컨 켜고 하겠습니다 |
| ✅ | false | false | - | NO_TRIGGER | 조별 발표는 다음 시간부터 시작할게요 |
| ✅ | false | false | - | NO_TRIGGER | 교재는 학교 앞 서점에서 구할 수 있어요 |
| ✅ | false | false | - | NO_TRIGGER | 수강 정정 기간이 이번 주 금요일까지예요 |
| ✅ | false | false | - | NO_TRIGGER | 10분만 쉬었다가 다시 하겠습니다 |
| ✅ | false | false | - | NO_TRIGGER | 질문 있으면 이메일로 보내 주세요 |
| ✅ | false | false | 0.390 | LECTURE_CONCEPT,SCORE_LOW | 우리 학교의 특징은 캠퍼스가 넓다는 겁니다 |
| ❌ | false | true | 0.564 | GLOSSARY_TERM | 인공지능 수업은 다음 주에 휴강입니다 |
| — | either | true | 0.561 | GLOSSARY_TERM | 시험 범위는 5장 머신러닝부터 딥러닝까지입니다 |

발화 정확도: **29/30** (96.7%, 'either' 제외)

## 3. 라우터 정규화의 검색 개선폭 (queries_textbook_hard 48개, major_ai)

| 질의 | R@1 | R@5 |
|------|----:|----:|
| 원문 질의 | 0.583 | 0.854 |
| 라우터 정규화 질의 | 0.708 | 0.938 |
