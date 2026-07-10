# eval/ — 평가 질의 및 결과

## 파일 구성

| 파일 | 용도 |
|------|------|
| `queries_positive.json` | 확정 positive 질의 48개 (definition 12 / comparison 11 / principle 11 / lecture 14) |
| `queries_hard.json` | 하드 세트 30개 (paraphrase 10 / stt_noise 10 / negative 10) — negative는 `answer_chunk_ids: []` (RAG OFF 케이스) |
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
