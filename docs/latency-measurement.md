# 실시간 지연 측정

발표·성능 논의에 쓰는 지연 수치를 **재현 가능하게** 만드는 절차다.
추정이나 설정값 나열이 아니라 실제 API 를 태운 실측이다.

## 무엇을 재는가

"발화 종료 → 학생에게 전달"을 구간으로 쪼갠다.

| 구간 | 의미 |
|------|------|
| STT 확정 | 발화 종료 → STT final 수신. 침묵 대기 + 인식 + 네트워크 왕복 |
| 세그먼트 대기 | STT final → 번역 단위 확정. 문장 경계 판정 / idle flush |
| 큐 대기 | 세그먼트 큐에서 컨슈머가 꺼낼 때까지 기다린 시간 |
| 번역 슬롯 대기 | 동시 번역 상한(`TRANSLATE_MAX_CONCURRENCY`)에 걸려 기다린 시간 |
| RAG 검색 | 전공 문맥 검색 (`RAG_TIMEOUT_SEC` 에서 잘림) |
| 번역 첫 토큰 / 첫 로케일 완성 | 스트리밍 번역의 첫 토큰, 가장 먼저 완성된 로케일까지 |
| 번역 | 번역 LLM 호출 전체 (모든 로케일 완성까지) |
| 순서 대기 | 번역은 나왔지만 앞 세그먼트 발행이 끝나길 기다린 시간 |
| 자막 발행 | LiveKit data 발행 + TTS 큐 적재 (마지막 로케일 꼬리) |
| TTS 첫 청크 / 재생 대기 | 스트리밍 합성의 첫 오디오 청크까지 / 앞 문장 재생 종료 대기 |
| TTS 합성 | Azure Neural TTS 합성 전체 |
| **E2E 첫 자막 / E2E 자막** | 발화 종료 → 첫 로케일 자막 / 모든 로케일 자막 발행 |
| **E2E 첫 음성 / E2E 음성** | 발화 종료 → 첫 오디오 청크 / 음성 push 완료 |

### JSONL 필드

`kind: "caption"` (세그먼트당 1줄)

| 필드 | 구간 |
|------|------|
| `sttMs`, `segmentMs`, `queueMs` | 위 표의 STT 확정 / 세그먼트 대기 / 큐 대기 |
| `translateSlotMs` | 큐에서 꺼낸 뒤 번역 슬롯을 얻기까지 |
| `glossaryMs`, `ragMs` | 용어 탐지, RAG 검색 (RAG off 면 `ragMs` 없음) |
| `translateTtftMs` | RAG 종료 → 번역 첫 토큰. 스트리밍일 때만 기록 |
| `firstLocaleMs` | RAG 종료 → 첫 로케일 완성 |
| `localeReadyMs` | `{로케일: ms}` — RAG 종료 → 로케일별 완성 (리포트 표에는 안 나옴) |
| `translateMs` | RAG 종료 → 번역 호출 종료 |
| `orderWaitMs` | 첫 로케일 완성 → 그 자막 발행 시작 (앞 세그먼트 대기) |
| `emitMs` | 마지막 로케일 완성(또는 발행 차례가 온 시각) → 모든 발행 완료 |
| `workerMs` | STT final 수신 → 모든 로케일 발행 완료 |
| `e2eFirstCaptionMs` | 발화 종료 → 첫 로케일 자막 발행 시작 |
| `e2eCaptionMs` | 발화 종료 → 모든 로케일 자막 발행 완료 |

`kind: "audio"` (세그먼트 × 로케일당 1줄)

| 필드 | 구간 |
|------|------|
| `streaming` | 스트리밍 합성 경로였는지 (`false` 면 전체 합성 후 1회 push) |
| `ttsQueueMs` | TTS 큐 적재 → 합성 시작 (선합성이면 앞 문장 재생 중에 시작) |
| `ttsFirstChunkMs` | 합성 시작 → 첫 오디오 청크 |
| `ttsPlayWaitMs` | 첫 청크 준비 → 실제 첫 push (앞 문장 재생 종료 대기) |
| `ttsSynthMs` | 합성 시작 → 합성 종료 |
| `ttsPublishMs` | 합성 종료 → push 완료 (스트리밍이면 대부분 합성과 겹친다) |
| `e2eFirstAudioMs` | 발화 종료 → 첫 오디오 청크 push — **학생이 듣기 시작하는 시점** |
| `e2eAudioMs` | 발화 종료 → 오디오 push 완료 |

### 이전 측정값과 비교할 때 (2026-09 지연 개선 이후)

아래 네 가지 개선이 들어가면서 일부 구간의 뜻이 바뀌었다.
`latency-results.md` 나 `latency-run-2026-08-12.jsonl` 처럼 **이전에 잰 수치와
그대로 나란히 놓으면 안 되는 구간**이 있다.

| 개선 | 설정 (기본값) | 영향받는 필드 |
|------|---------------|---------------|
| 순서 보존 병렬 번역 | `TRANSLATE_MAX_CONCURRENCY=3` | `queueMs` 감소, `translateSlotMs`·`orderWaitMs` 신설 |
| 번역 스트리밍 + 로케일별 조기 발행 | `TRANSLATE_STREAMING=true` | `translateTtftMs`·`firstLocaleMs`·`e2eFirstCaptionMs` 신설 |
| 세션 시작 예열 | `WARMUP_ENABLED=true`, `WARMUP_TIMEOUT_SEC=3` | 첫 세그먼트의 `translateMs`·`ttsSynthMs` 감소 |
| TTS 스트리밍 + 선합성 | `TTS_STREAMING=true`, `TTS_PREFETCH=true` | `ttsFirstChunkMs`·`ttsPlayWaitMs`·`e2eFirstAudioMs` 신설 |

- **`emitMs` 는 정의가 바뀌었다.** 예전에는 "번역 완료 → 발행 완료"라서 직렬
  컨슈머의 앞 세그먼트 대기가 섞여 있었다. 지금은 그 대기를 `orderWaitMs` 로
  떼어 냈고, `emitMs` 는 마지막 로케일의 발행 꼬리만 잰다.
- `e2eCaptionMs`·`e2eAudioMs` 는 정의가 같다. 신·구 비교는 이 둘로 하고,
  개선 효과(체감 지연)는 `e2eFirstCaptionMs`·`e2eFirstAudioMs` 로 보여 준다.
- 개선 하나만의 효과를 보려면 해당 설정만 끄고 같은 WAV·같은 `--repeat` 로
  한 번 더 잰다. 예: `TRANSLATE_STREAMING=false` 로 돌린 결과와 기본값 결과의
  `e2eFirstCaptionMs` 차이가 번역 스트리밍의 효과다. `latency_probe.py` 도 이
  설정들을 워커와 똑같이 따른다(예열 포함).

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
- 한 STT final 이 여러 문장으로 쪼개지면 번역은 병렬로 돌지만 발행은 sequence
  순서를 지킨다. 그래서 뒤 문장의 지연은 `queueMs` 가 아니라 `orderWaitMs`
  (앞 문장 발행 대기)와 `translateSlotMs`(동시 번역 상한 대기)에 드러난다.
- 예열이 켜져 있으면 세션 첫 세그먼트가 튀지 않는다. 예전 측정의 첫 세그먼트
  값(+0.9~1초)을 "개선 전 대표값"으로 쓰지 말 것 — 콜드스타트 한 건이다.
- 스트리밍 합성(`streaming: true`)에서는 `ttsPublishMs` 가 합성과 겹쳐 작게
  나온다. 음성 체감 지연은 `e2eFirstAudioMs` 로 본다.
- 표본이 적은 구간을 발표에 인용하지 말 것. `latency_report.py` 는
  `--min-samples`(기본 5) 미만 구간을 표에서 뺀다.
