"""OpenAI Realtime 전사(transcription) STT 어댑터.

Azure 어댑터(stt.py)와 동일한 계약을 구현한다:
  동기 start() / write(pcm) / stop() + 콜백 3개(on_partial/on_final/on_error).
STT_PROVIDER=openai 로 전환하며, Azure 경로는 손대지 않는다.

브리지 구조: 워커 이벤트루프 위의 태스크 + asyncio.Queue.
  - write() 는 오디오 펌프(워커 루프 스레드)에서만 불리므로 put_nowait 로 안전.
  - 전용 스레드+루프 방식은 stop 시 스레드 join 이라는 새 블로킹 표면을 만들어
    배제했다 — 세션 종료 hang 은 이 코드베이스에서 실제 장애를 냈던 부류다.

주의:
  - Realtime PCM 입력은 24kHz 전용이다. 파이프라인은 16kHz 를 주므로
    여기서 2:3 선형보간 리샘플한다 (resample_16k_to_24k).
  - Azure 전용 튜닝(true_text/profanity/endpoint_id/segmentation_max_time,
    phrase weight)은 이 프로바이더에 대응 개념이 없어 무시한다.
    침묵 분할은 server_vad 의 silence_duration_ms 로 근사한다.
  - confidence 는 logprobs 를 exp(mean) 으로 접어 유사값을 만든다 — None 으로
    두면 저신뢰 경고와 QA 계측(transcript.sttConfidence)이 조용히 죽는다.
"""

from __future__ import annotations

import array
import asyncio
import base64
import logging
import math
from typing import Any, Callable, Iterable

from .models import SttFinalResult, SttPartialResult
from .stt import SttError, classify_stt_error

logger = logging.getLogger(__name__)

SOURCE_SAMPLE_RATE = 16000
TARGET_SAMPLE_RATE = 24000

# 오디오 큐 상한: 10ms 프레임 기준 약 5초. 연결 지연 중에는 최신 오디오가
# 우선이므로 가득 차면 가장 오래된 프레임을 버린다.
DEFAULT_QUEUE_MAX_FRAMES = 500
DEFAULT_KEYWORDS_MAX = 100
# 프레임(10ms=320B)마다 웹소켓 메시지를 보내지 않도록 ~100ms 로 배칭.
SEND_BATCH_BYTES = 3200

DELTA_EVENT = "conversation.item.input_audio_transcription.delta"
COMPLETED_EVENT = "conversation.item.input_audio_transcription.completed"
FAILED_EVENT = "conversation.item.input_audio_transcription.failed"
SPEECH_STARTED_EVENT = "input_audio_buffer.speech_started"

# 말하는 중임을 알리는 표시 텍스트. OpenAI 전사는 턴(발화) 단위라 Azure 처럼
# 말하는 도중의 중간 가설이 없다 — 이 표시가 없으면 "되는지 안 되는지" 알 수 없다.
LISTENING_INDICATOR = "…"

PartialCallback = Callable[[SttPartialResult], None]
FinalCallback = Callable[[SttFinalResult], None]
ErrorCallback = Callable[[SttError], None]


# ── 순수 함수 (테스트 대상) ───────────────────────────────────────────


def to_iso639_1(language: str) -> str:
    """'ko-KR' → 'ko'. Realtime 전사는 ISO-639-1 코드를 받는다."""
    return (language or "").split("-")[0].lower() or "ko"


def resample_16k_to_24k(pcm: bytes) -> bytes:
    """16kHz/16bit/mono PCM → 24kHz 선형보간 업샘플.

    Realtime 입력이 24kHz 전용이라 필요하다. 업샘플(정보 추가 없음)이라
    품질 손실은 없고, 10ms 프레임(160샘플) 기준 순수 파이썬으로도 충분히 빠르다.
    """
    if not pcm:
        return b""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    n = len(samples)
    if n == 0:
        return b""
    out_n = n * TARGET_SAMPLE_RATE // SOURCE_SAMPLE_RATE
    out = array.array("h", bytes(out_n * 2))
    ratio = SOURCE_SAMPLE_RATE / TARGET_SAMPLE_RATE  # 2/3
    for i in range(out_n):
        pos = i * ratio
        left = int(pos)
        right = min(left + 1, n - 1)
        frac = pos - left
        out[i] = int(samples[left] * (1.0 - frac) + samples[right] * frac)
    return out.tobytes()


def select_keywords(phrases: Iterable[str], max_items: int) -> list[str]:
    """phrase list 에서 상위 용어를 중복 없이 고른다.

    입력은 이미 우선순위 정렬돼 있다(lexicon.build_phrase_list).
    """
    seen: set[str] = set()
    keywords: list[str] = []
    for phrase in phrases:
        text = " ".join(str(phrase or "").split())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(text)
        if len(keywords) >= max_items:
            break
    return keywords


# prompt 힌트의 문자 상한 — 과도하게 길면 전사 스타일에 악영향을 줄 수 있다.
PROMPT_MAX_CHARS = 1200


def compress_phrases_to_prompt(phrases: Iterable[str], max_chars: int = PROMPT_MAX_CHARS) -> str:
    """전공 용어 목록을 gpt-4o-transcribe 의 prompt 자유 텍스트로 접는다.

    Realtime 전사의 `keywords` 필드는 gpt-4o-transcribe 에서 미지원이다(실측:
    "The 'keywords' parameter is not supported for this model"). 이 모델 계열은
    prompt 로 도메인 힌트를 받는다.
    """
    terms: list[str] = []
    used = 0
    header = "한국어 대학 강의. 다음 전공 용어가 등장할 수 있다: "
    for term in phrases:
        text = " ".join(str(term or "").split())
        if not text:
            continue
        cost = len(text) + 2
        if used + cost > max_chars:
            break
        terms.append(text)
        used += cost
    if not terms:
        return ""
    return header + ", ".join(terms)


def pseudo_confidence(logprobs: Any) -> float | None:
    """토큰 logprob 평균을 exp 로 접어 0~1 유사 신뢰도로 만든다."""
    if not logprobs:
        return None
    values: list[float] = []
    for item in logprobs:
        value = getattr(item, "logprob", None)
        if value is None and isinstance(item, dict):
            value = item.get("logprob")
        if isinstance(value, (int, float)):
            values.append(float(value))
    if not values:
        return None
    return max(0.0, min(1.0, math.exp(sum(values) / len(values))))


def build_transcription_session_payload(
    *,
    model: str,
    language: str,
    prompt: str,
    silence_ms: int,
    include_logprobs: bool,
    vad_threshold: float = 0.6,
) -> dict[str, Any]:
    """session.update 로 보낼 전사 세션 설정. (스키마:
    RealtimeTranscriptionSessionCreateRequest — type/audio/include)

    noise_reduction 과 vad threshold 상향은 환청 억제용이다: 소음/무음 구간이
    발화로 감지되면 모델이 prompt 의 전공 용어를 지어내(transcript hallucination)
    유령 자막·TTS 가 나간다 — 실제 관측된 장애.
    """
    transcription: dict[str, Any] = {
        "model": model,
        "language": to_iso639_1(language),
    }
    if prompt:
        transcription["prompt"] = prompt
    payload: dict[str, Any] = {
        "type": "transcription",
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": TARGET_SAMPLE_RATE},
                "noise_reduction": {"type": "near_field"},
                "transcription": transcription,
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": min(1.0, max(0.0, vad_threshold)),
                    "silence_duration_ms": max(100, silence_ms),
                },
            }
        },
    }
    if include_logprobs:
        payload["include"] = ["item.input_audio_transcription.logprobs"]
    return payload


# ── 어댑터 ────────────────────────────────────────────────────────────


class OpenAiRealtimeStt:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        language: str,
        phrases: Iterable[str],
        on_partial: PartialCallback,
        on_final: FinalCallback,
        on_error: ErrorCallback | None = None,
        silence_ms: int = 800,
        include_logprobs: bool = True,
        keywords_max: int = DEFAULT_KEYWORDS_MAX,
        queue_max_frames: int = DEFAULT_QUEUE_MAX_FRAMES,
        vad_threshold: float = 0.6,
        min_confidence: float = 0.5,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._language = language
        self._keywords = select_keywords(phrases, keywords_max)
        self._prompt = compress_phrases_to_prompt(self._keywords)
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_error = on_error
        self._silence_ms = silence_ms
        self._include_logprobs = include_logprobs
        self._vad_threshold = vad_threshold
        # 환청 가드: 이 값 미만의 유사 신뢰도 전사는 폐기한다 (0 이면 끔).
        # 실측: 정상 발화는 0.99~1.00, 환청은 대체로 그보다 낮다.
        self._min_confidence = max(0.0, min_confidence)

        # 루프는 start() 시점(워커 이벤트루프 안)에서 잡는다 — 생성자는
        # 루프 밖(테스트 등)에서도 불릴 수 있다.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._audio_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=max(10, queue_max_frames))
        self._task: asyncio.Task[None] | None = None
        self._stopped = False
        self._dropped_frames = 0
        # item_id별 델타 누적 — Azure partial 은 "현재 발화의 전체 텍스트" 의미라
        # 델타를 이어 붙여 동일한 의미로 전달한다.
        self._partials: dict[str, str] = {}
        self.keyword_count = len(self._keywords)

    # ── 계약 메서드 (stt.py 의 AzureStreamingStt 와 동일) ────────────

    def start(self) -> None:
        if self._task is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._task = self._loop.create_task(self._run())
        logger.info(
            "OpenAI Realtime STT 시작 (model=%s language=%s keywords=%d)",
            self._model,
            to_iso639_1(self._language),
            len(self._keywords),
        )

    def write(self, pcm: bytes) -> None:
        if self._stopped or not pcm:
            return
        try:
            self._audio_q.put_nowait(pcm)
        except asyncio.QueueFull:
            # 최신 오디오 우선 — 가장 오래된 프레임을 버린다.
            try:
                self._audio_q.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - 경합 방어
                pass
            try:
                self._audio_q.put_nowait(pcm)
            except asyncio.QueueFull:  # pragma: no cover - 경합 방어
                pass
            self._dropped_frames += 1
            if self._dropped_frames % 100 == 1:
                logger.warning(
                    "OpenAI Realtime 오디오 큐 포화 — 누적 %d프레임 드롭",
                    self._dropped_frames,
                )

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        task = self._task
        if task is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(task.cancel)

    # ── 내부 ─────────────────────────────────────────────────────────

    async def _run(self) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError:  # pragma: no cover - 런타임 의존성
            self._emit_error("openai package is not installed")
            return

        try:
            client = AsyncOpenAI(api_key=self._api_key)
            # 주의: 전사 모델(gpt-4o-transcribe)을 웹소켓 connect 의 model 로 넘기면
            # invalid_model 로 거부된다(실측). 연결은 intent=transcription 으로만 열고,
            # 전사 모델은 아래 session.update 의 audio.input.transcription.model 에 넣는다.
            async with client.realtime.connect(
                extra_query={"intent": "transcription"},
            ) as connection:
                await connection.send(
                    {
                        "type": "session.update",
                        "session": build_transcription_session_payload(
                            model=self._model,
                            language=self._language,
                            prompt=self._prompt,
                            silence_ms=self._silence_ms,
                            include_logprobs=self._include_logprobs,
                            vad_threshold=self._vad_threshold,
                        ),
                    }
                )
                sender = asyncio.create_task(self._send_loop(connection))
                try:
                    async for event in connection:
                        self.handle_event(event)
                finally:
                    sender.cancel()
                    try:
                        await sender
                    except asyncio.CancelledError:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._stopped:
                self._emit_error(str(exc))

    async def _send_loop(self, connection: Any) -> None:
        buffer = bytearray()
        while True:
            pcm = await self._audio_q.get()
            buffer.extend(pcm)
            # 큐에 쌓인 프레임을 한 번에 비워 배칭한다.
            while not self._audio_q.empty() and len(buffer) < SEND_BATCH_BYTES * 4:
                try:
                    buffer.extend(self._audio_q.get_nowait())
                except asyncio.QueueEmpty:  # pragma: no cover
                    break
            if len(buffer) < SEND_BATCH_BYTES:
                continue
            chunk = bytes(buffer)
            buffer.clear()
            await connection.send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(resample_16k_to_24k(chunk)).decode("ascii"),
                }
            )

    def handle_event(self, event: Any) -> None:
        """수신 이벤트 → 콜백 매핑. (테스트에서 직접 호출 가능하게 public)"""
        event_type = getattr(event, "type", "")
        if event_type == DELTA_EVENT:
            item_id = getattr(event, "item_id", "") or ""
            accumulated = self._partials.get(item_id, "") + (getattr(event, "delta", "") or "")
            self._partials[item_id] = accumulated
            if accumulated.strip():
                self._on_partial(SttPartialResult(text=accumulated))
        elif event_type == SPEECH_STARTED_EVENT:
            # 발화 감지 즉시 표시 — 전사는 발화가 끝나야 시작되므로(턴 방식),
            # 이 표시가 없으면 말하는 동안 화면이 침묵해 고장처럼 보인다.
            self._on_partial(SttPartialResult(text=LISTENING_INDICATOR))
        elif event_type == COMPLETED_EVENT:
            item_id = getattr(event, "item_id", "") or ""
            self._partials.pop(item_id, None)
            text = (getattr(event, "transcript", "") or "").strip()
            confidence = pseudo_confidence(getattr(event, "logprobs", None))
            if not text:
                # 빈 전사 — "인식 중" 표시만 지운다.
                self._on_partial(SttPartialResult(text=""))
                return
            if (
                self._min_confidence > 0
                and confidence is not None
                and confidence < self._min_confidence
            ):
                # 환청 의심: 소음/무음 턴에서 모델이 prompt 의 전공 용어를
                # 지어내는 사례가 실측됨. 자막·TTS 로 내보내지 않는다.
                logger.warning(
                    "저신뢰(%.2f) 전사 폐기 (환청 의심): %r", confidence, text
                )
                self._on_partial(SttPartialResult(text=""))
                return
            self._on_final(
                SttFinalResult(
                    text=text,
                    confidence=confidence,
                    offset_ms=None,
                    duration_ms=None,
                )
            )
        elif event_type == FAILED_EVENT:
            error = getattr(event, "error", None)
            message = getattr(error, "message", None) or str(error or "transcription failed")
            self._emit_error(message)
        elif event_type == "error":
            error = getattr(event, "error", None)
            message = getattr(error, "message", None) or str(error or "realtime error")
            self._emit_error(message)

    def _emit_error(self, message: str) -> None:
        logger.warning("OpenAI Realtime STT error: %s", message)
        if self._on_error is not None:
            self._on_error(classify_stt_error("openai-realtime", message))
