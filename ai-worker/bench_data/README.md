# STT 벤치마크 데이터

`tools/stt_benchmark.py` 가 읽는 평가 세트 폴더. 같은 이름의 `*.wav`(16kHz mono 권장)와
`*.txt`(사람이 검수한 정답 전사)를 쌍으로 둔다.

```
bench_data/
  kugohak-w4.wav   # 강의 녹음 (직접 준비 — 저장소에는 커밋하지 않는 것을 권장)
  kugohak-w4.txt   # 정답 전사 (아래 참고)
```

실행 예:

```
python tools/stt_benchmark.py --data-dir bench_data --providers azure --drop-fillers
python tools/stt_benchmark.py --data-dir bench_data --providers azure,whisper --drop-fillers -o report.md
```

## 정답 전사 작성 규칙

- 실제로 발화한 그대로 적는다. 간투사("씁", "어", "아", "하")를 적어도 된다 —
  채점 시 `--drop-fillers` 로 양쪽에서 제거된다.
- 문장부호·띄어쓰기는 채점에 영향이 없다 (CER 는 문자만 비교).
- 오타는 그대로 오답 처리되므로 제출 전에 한 번 검수한다.

## 포함된 정답 전사

- `kugohak-w4.txt` — 국어학개론 4주차 (말소리의 체계 / 음운론 도입부).
  직접 청취하며 받아 적은 실강의 전사로, 명백한 타이핑 오타 2건(`ㄱ런`→`그런`,
  `그럿이`→`그것이`)만 교정했다. 대응하는 녹음(wav)을 같은 이름으로 두면
  바로 벤치마크에 포함된다.
