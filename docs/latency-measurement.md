# 실시간 지연 측정

발표·성능 논의에 쓰는 지연 수치를 **재현 가능하게** 만드는 절차다.
추정이나 설정값 나열이 아니라 실제 API 를 태운 실측이다.

## 무엇을 재는가

"발화 종료 → 학생에게 전달"을 구간으로 쪼갠다.

| 구간 | 의미 |
|------|------|
| STT 확정 | 발화 종료 → STT final 수신. 침묵 대기 + 인식 + 네트워크 왕복 |
| 세그먼트 대기 | STT final → 번역 단위 확정. 문장 경계 판정 / idle flush |
| 큐 대기 | 세그먼트 큐에서 앞 세그먼트 처리를 기다린 시간 |
| RAG 검색 | 전공 문맥 검색 (`RAG_TIMEOUT_SEC` 에서 잘림) |
| 번역 | 번역 LLM 호출 |
| 자막 발행 | LiveKit data 발행 + TTS 큐 적재 |
| TTS 합성 | Azure Neural TTS |
| **E2E 자막 / E2E 음성** | 발화 종료 → 자막 / 음성 발행 |

### "발화 종료"를 어떻게 아는가

Azure STT 는 결과마다 오디오 타임라인 기준 `offset` 과 `duration` 을 준다.
인식기에 **첫 오디오를 밀어 넣은 시각**을 앵커로 잡아
`speech_end_at = 앵커 + (offset + duration)` 으로 되돌린다
(`stt.py` 의 `_speech_end_at`).

이 앵커가 성립하려면 오디오를 **끊김 없이 실시간 속도로** 넣어야 한다.
`offset` 은 밀어 넣은 오디오 샘플 기준이지 벽시계가 아니기 때문에, 중간에
오디오를 안 넣고 쉬면 그 시간만큼 오디오 타임라인이 멈춰
`speech_end_at` 이 과거로 밀리고 STT 확정 지연이 부풀어 오른다.
`latency_probe.py` 는 발화 사이 공백까지 무음 프레임으로 채워 이를 막고,
끝에 실제 드리프트를 출력한다. **드리프트가 500ms 를 넘으면 STT 구간 수치는
버려야 한다.**

## 실행

계측은 기본 꺼져 있다. `LATENCY_LOG_PATH` 가 있을 때만 JSONL 이 쌓인다.

### A. 프로브 (권장 — 스택 없이)

LiveKit / NestJS / Postgres 없이 워커 파이프라인만 돌린다.
실제 Azure STT·번역 API·Azure TTS 를 호출하므로 **비용이 발생한다.**

```bash
cd ai-worker
.venv/Scripts/python.exe tools/latency_probe.py \
    --wav bench_data/synthetic_ai_intro.wav \
    --locales vi-VN,zh-CN --major ai \
    --repeat 12 --tail-sec 4 --out latency.jsonl

.venv/Scripts/python.exe tools/latency_report.py --input latency.jsonl
```

- `--repeat` 로 표본을 늘린다. p95 를 인용하려면 30건 이상 권장.
- `--no-tts` 로 TTS 를 빼면 자막 경로만 더 싸게 잰다.
- 측정에서 빠지는 것은 **LiveKit 전송 홉 하나**뿐이다.

### B. 전체 스택 (LiveKit 홉 포함)

```powershell
.\start-all.ps1      # docker(postgres/redis/azurite) + 워커 + 백엔드
```

워커를 띄우기 전에 `ai-worker/.env` 에 `LATENCY_LOG_PATH=latency.jsonl` 을 넣는다.
교수 화면에서 세션을 시작한 뒤, 마이크 대신 고정 오디오를 넣으려면:

```bash
python tools/professor_audio_publisher.py \
    --url "$LIVEKIT_URL" --token "<교수 토큰>" \
    --wav bench_data/synthetic_ai_intro.wav --realtime
```

세션 종료 후 같은 방식으로 `latency_report.py` 를 돌린다.

## 해석 주의

- **학생 단말 렌더링·재생 지연은 포함하지 않는다.** 워커가 발행한 시점까지다.
  단말까지 포함한 체감 지연을 주장하려면 화면 녹화로 따로 재야 한다.
- 번역 LLM 호출은 분산이 크다. p50 과 p95 를 같이 제시할 것.
- 큐 대기는 한 STT final 이 여러 문장으로 쪼개질 때만 튄다. 세그먼트 컨슈머가
  직렬이라 뒤 문장이 앞 문장의 번역을 기다린다.
- 표본이 적은 구간을 발표에 인용하지 말 것. `latency_report.py` 는
  `--min-samples`(기본 5) 미만 구간을 표에서 뺀다.
