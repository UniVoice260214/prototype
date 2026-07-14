# eval/ — 평가 질의 및 결과

## 파일 구성

| 파일 | 용도 |
|------|------|
| `queries_positive.json` | 확정 positive 질의 48개 (definition 12 / comparison 11 / principle 11 / lecture 14) |
| `queries_hard.json` | 하드 세트 30개 (paraphrase 10 / stt_noise 10 / negative 10) — negative는 `answer_chunk_ids: []` (RAG OFF 케이스) |
| `queries_textbook.json` | 교재(`인공지능_입문_교재.pdf`) 기반 질의 24개 (definition 8 / comparison 8 / principle 8) — 정답은 `tb_*` chunk 중심, glossary/concept에 동등한 답이 있으면 함께 라벨 |
| `queries_positive_v2.json` / `queries_hard_v2.json` | 교재 편입 후 미라벨 정답 보정판 (v1은 교재 전 결과 비교용 보존) — 근거: `_miss_analysis*.txt`, 결과: `results_*_v2.md` |
| `queries_textbook_hard.json` | 교재 질의 24개의 하드 변형 48개 (paraphrase 24 / stt_noise 24, 정답 라벨은 원본과 동일) — 결과: `results_textbook_hard.md` |
| `router_test_sentences.json` | RAG Router용 발화형(교수 평서문) 테스트 문장 31개 (positive 18 / negative 12 / 경계 either 1) — 결과: `results_router.md`, 실행: `python src/evaluate_router.py` |
| `queries_draft.json` | 초기 초안 (queries_positive.json으로 대체됨, 참고용) |
| `results.md` / `results_hard.md` | evaluate.py 실행 결과 |

## 실행

```bash
# 두 세트 병합 평가 (positive + hard)
python src/evaluate.py --queries eval/queries_positive.json eval/queries_hard.json --output eval/results.md
```

## 질의 제거 이력

### "무작위 탐색, 순차 탐색, 이진 탐색은 어떤 탐색 기법이야?" (lecture형, 2026-07-10 제거)

- 원래 정답 슬라이드였던 **I2A_Lecture03.pdf 5~7페이지는 텍스트가 50자 미만**
  (제목+그림 위주 슬라이드)이라 ingest 단계에서 코퍼스에서 제외됨.
- 대체 후보였던 `lec03_p04_04`는 해당 기법들을 지나가듯 언급만 하고,
  `glossary_search`도 질문("각 탐색 기법이 무엇인가")에 제대로 답하지 못하는 chunk임.
- **코퍼스 안에 유효한 정답 chunk가 존재하지 않아** 평가 질의로 부적합 → 제거.
- 슬라이드 청킹의 최소 글자수 규칙을 바꾸면 복원 가능하나, 그림 위주 슬라이드가
  대량 유입되는 부작용이 있어 질의 제거를 선택함.
