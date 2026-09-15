"""환경변수 로드 — Core API의 .env와 키 이름을 맞춘다 (REDIS_URL, LIVEKIT_*).

파이프라인 단계별로 필요한 키를 한 곳에 모은다:
  - STT/TTS : AZURE_SPEECH_*      (Azure Speech, 하나의 리소스로 STT+TTS 공용)
  - 번역     : TRANSLATE_PROVIDER 에 따라 OpenAI 또는 Azure OpenAI
"""

import json
import os
from dataclasses import dataclass, field

try:  # pragma: no cover - optional in unit-test runtimes.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv() -> None:
        return None

load_dotenv()

# locale → Azure Neural Voice 기본 매핑. TTS_VOICE_MAP(JSON)으로 덮어쓸 수 있다.
DEFAULT_VOICE_MAP = {
    "zh-CN": "zh-CN-XiaoxiaoNeural",
    "zh-TW": "zh-TW-HsiaoChenNeural",
    "vi-VN": "vi-VN-HoaiMyNeural",
    "mn-MN": "mn-MN-YesuiNeural",
    "en-US": "en-US-JennyNeural",
    "ja-JP": "ja-JP-NanamiNeural",
    "uk-UA": "uk-UA-PolinaNeural",
}

# 짧은 세그먼트가 자막 지연을 줄이고 번역 품질도 낫다.
# STT TrueText 후처리가 문장부호를 붙여 주면 대부분 문장 경계에서 먼저 끊긴다.
DEFAULT_SEGMENT_MAX_CHARS = 60
DEFAULT_SEGMENT_IDLE_FLUSH_MS = 1200
DEFAULT_SEGMENT_MIN_CHARS = 2
# TrueText 가 구두점을 못 붙인 무구두점 발화를 종결어미("~습니다" 등)에서 끊는다.
DEFAULT_SEGMENT_SPLIT_KOREAN_ENDINGS = True

# ── STT 인식 튜닝 (Azure 기본값이 아니라 한국어 강의용으로 조정한 값) ──
DEFAULT_STT_SEGMENTATION_SILENCE_MS = 800
# 쉼 없는 발화의 강제 확정 상한 (Azure 허용 20~70초, 0=off).
DEFAULT_STT_SEGMENTATION_MAX_TIME_MS = 20000
DEFAULT_STT_INITIAL_SILENCE_MS = 15000
DEFAULT_STT_END_SILENCE_MS = 1000
DEFAULT_STT_PHRASE_LIST_WEIGHT = 1.0
DEFAULT_STT_PHRASE_LIST_MAX_ITEMS = 500
DEFAULT_STT_PHRASE_LIST_MAX_CHARS = 8000
DEFAULT_STT_LOW_CONFIDENCE_WARN = 0.5
DEFAULT_TRANSLATE_TIMEOUT_SEC = 8.0
DEFAULT_RAG_TIMEOUT_SEC = 2.0
DEFAULT_RAG_ASSETS_DIR = "rag_assets"
DEFAULT_SEGMENT_QUEUE_MAX_SIZE = 100
DEFAULT_SEGMENT_ENQUEUE_TIMEOUT_MS = 250
DEFAULT_TTS_TIMEOUT_SEC = 15.0
DEFAULT_TTS_MAX_RETRIES = 2
DEFAULT_TTS_RETRY_BASE_DELAY_MS = 500
DEFAULT_TTS_MAX_CONCURRENCY = 3
DEFAULT_TTS_QUEUE_MAX_SIZE = 100
DEFAULT_TTS_DEDUPE_TTL_SEC = 3600
DEFAULT_TTS_FAILED_DEDUPE_TTL_SEC = 30
DEFAULT_STT_MAX_RECONNECTS = 3

# ── 세션 종료 타임아웃 ────────────────────────────────────────────────
# 종료 체인 어디도 무제한 대기하면 안 된다 — 종료 hang 이 pubsub 처리까지
# 연쇄로 막아 "다음 수업이 활성화되지 않는" 장애를 만든다.
# 정상 경로 합(pipeline 5 + tts 3 + 정리)이 세션 전체 상한(15) 안에 들어온다.
DEFAULT_SESSION_STOP_TIMEOUT_SEC = 15.0
DEFAULT_PIPELINE_FLUSH_TIMEOUT_SEC = 5.0
DEFAULT_TTS_FLUSH_TIMEOUT_SEC = 3.0

# ── STT 프로바이더 ────────────────────────────────────────────────────
# azure(기본) | openai. 기존 Azure 경로는 그대로 두고 설정으로만 전환한다.
STT_PROVIDERS = ("azure", "openai")
DEFAULT_STT_OPENAI_MODEL = "gpt-4o-transcribe"
# OpenAI 전사는 턴 방식(발화가 끝나야 전사 시작)이라 침묵 기준을 Azure(800)보다
# 낮춰 절 단위로 빨리 확정되게 한다 — 중간 가설이 없는 것을 응답성으로 보상.
DEFAULT_STT_OPENAI_SILENCE_MS = 500
DEFAULT_STT_OPENAI_KEYWORDS_MAX = 100
# VAD 감도(0~1, 높을수록 둔감)와 환청 가드 임계 — 소음 턴에서 prompt 용어를
# 지어내는 hallucination 억제 (실측 장애). min_confidence 0 이면 가드 끔.
DEFAULT_STT_OPENAI_VAD_THRESHOLD = 0.6
DEFAULT_STT_OPENAI_MIN_CONFIDENCE = 0.5
DEFAULT_STT_RECONNECT_BASE_DELAY_MS = 500
DEFAULT_WORKER_STATUS_TTL_SEC = 3600
# RAG는 번역 크리티컬 패스에 동기로 걸린다 — fail-open으로 None을 반환하므로
# 타임아웃을 짧게 유지해야 RAG 지연이 자막/TTS 전체를 밀어내지 않는다.
DEFAULT_RAG_TIMEOUT_SEC = 0.4


@dataclass(frozen=True)
class WorkerConfig:
    redis_url: str
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # Azure Speech (STT + TTS 공용)
    azure_speech_key: str
    azure_speech_region: str
    stt_language: str

    # 번역
    translate_provider: str          # "openai" | "azure"
    openai_api_key: str
    openai_model: str
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    azure_openai_api_version: str

    voice_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_VOICE_MAP))
    segment_max_chars: int = DEFAULT_SEGMENT_MAX_CHARS
    segment_idle_flush_ms: int = DEFAULT_SEGMENT_IDLE_FLUSH_MS
    segment_min_chars: int = DEFAULT_SEGMENT_MIN_CHARS
    segment_split_korean_endings: bool = DEFAULT_SEGMENT_SPLIT_KOREAN_ENDINGS
    segment_queue_max_size: int = DEFAULT_SEGMENT_QUEUE_MAX_SIZE
    segment_enqueue_timeout_ms: int = DEFAULT_SEGMENT_ENQUEUE_TIMEOUT_MS
    tts_timeout_sec: float = DEFAULT_TTS_TIMEOUT_SEC
    tts_max_retries: int = DEFAULT_TTS_MAX_RETRIES
    tts_retry_base_delay_ms: int = DEFAULT_TTS_RETRY_BASE_DELAY_MS
    tts_max_concurrency: int = DEFAULT_TTS_MAX_CONCURRENCY
    tts_queue_max_size: int = DEFAULT_TTS_QUEUE_MAX_SIZE
    tts_dedupe_ttl_sec: int = DEFAULT_TTS_DEDUPE_TTL_SEC
    tts_failed_dedupe_ttl_sec: int = DEFAULT_TTS_FAILED_DEDUPE_TTL_SEC
    session_stop_timeout_sec: float = DEFAULT_SESSION_STOP_TIMEOUT_SEC
    pipeline_flush_timeout_sec: float = DEFAULT_PIPELINE_FLUSH_TIMEOUT_SEC
    tts_flush_timeout_sec: float = DEFAULT_TTS_FLUSH_TIMEOUT_SEC
    # STT 프로바이더 스위치 (기본 azure — 기존 경로 무변경 보장)
    stt_provider: str = "azure"
    stt_openai_model: str = DEFAULT_STT_OPENAI_MODEL
    stt_openai_silence_ms: int = DEFAULT_STT_OPENAI_SILENCE_MS
    stt_openai_logprobs: bool = True
    stt_openai_keywords_max: int = DEFAULT_STT_OPENAI_KEYWORDS_MAX
    stt_openai_vad_threshold: float = DEFAULT_STT_OPENAI_VAD_THRESHOLD
    stt_openai_min_confidence: float = DEFAULT_STT_OPENAI_MIN_CONFIDENCE
    stt_max_reconnects: int = DEFAULT_STT_MAX_RECONNECTS
    stt_reconnect_base_delay_ms: int = DEFAULT_STT_RECONNECT_BASE_DELAY_MS
    worker_status_ttl_sec: int = DEFAULT_WORKER_STATUS_TTL_SEC
    # STT 인식 튜닝
    stt_segmentation_silence_ms: int = DEFAULT_STT_SEGMENTATION_SILENCE_MS
    stt_segmentation_max_time_ms: int = DEFAULT_STT_SEGMENTATION_MAX_TIME_MS
    stt_initial_silence_ms: int = DEFAULT_STT_INITIAL_SILENCE_MS
    stt_end_silence_ms: int = DEFAULT_STT_END_SILENCE_MS
    stt_true_text: bool = True
    stt_profanity_raw: bool = True
    stt_endpoint_id: str = ""        # Azure Custom Speech. 빈 값이면 미사용.
    stt_phrase_list_weight: float = DEFAULT_STT_PHRASE_LIST_WEIGHT
    stt_phrase_list_max_items: int = DEFAULT_STT_PHRASE_LIST_MAX_ITEMS
    stt_phrase_list_max_chars: int = DEFAULT_STT_PHRASE_LIST_MAX_CHARS
    stt_low_confidence_warn: float = DEFAULT_STT_LOW_CONFIDENCE_WARN
    translate_timeout_sec: float = DEFAULT_TRANSLATE_TIMEOUT_SEC
    rag_enabled: bool = False
    rag_url: str = ""
    rag_default_major: str = "auto"
    rag_course_major_map: dict[str, str] = field(default_factory=dict)
    rag_timeout_sec: float = DEFAULT_RAG_TIMEOUT_SEC
    # lexicon_*.json 이 있는 디렉터리 (STT 전공 용어 교정 자산)
    rag_assets_dir: str = DEFAULT_RAG_ASSETS_DIR


def _load_voice_map() -> dict[str, str]:
    merged = dict(DEFAULT_VOICE_MAP)
    raw = os.environ.get("TTS_VOICE_MAP")
    if raw:
        try:
            merged.update(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"TTS_VOICE_MAP JSON 파싱 실패: {exc}")
    return merged


def _load_int(name: str, default: int, *, min_value: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer: {raw!r}") from exc
    if value < min_value:
        raise SystemExit(f"{name} must be >= {min_value} (current: {value})")
    return value


def _load_float(name: str, default: float, *, min_value: float = 0.001) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a number: {raw!r}") from exc
    if value < min_value:
        raise SystemExit(f"{name} must be >= {min_value} (current: {value})")
    return value


def _load_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SystemExit(f"{name} must be a boolean (current: {raw!r})")


def _load_rag_course_major_map() -> dict[str, str]:
    raw = os.environ.get("RAG_COURSE_MAJOR_MAP", "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"RAG_COURSE_MAJOR_MAP JSON 파싱 실패: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit("RAG_COURSE_MAJOR_MAP must be a JSON object")
    allowed = {"auto", "ai", "hss", "bme"}
    invalid = {str(key): major for key, major in value.items() if major not in allowed}
    if invalid:
        raise SystemExit(f"RAG_COURSE_MAJOR_MAP has invalid majors: {invalid}")
    return {str(key): str(major) for key, major in value.items()}

def load_config() -> WorkerConfig:
    provider = os.environ.get("TRANSLATE_PROVIDER", "openai").lower()
    stt_provider = os.environ.get("STT_PROVIDER", "azure").lower()
    if stt_provider not in STT_PROVIDERS:
        raise SystemExit(
            f"STT_PROVIDER 는 {' | '.join(STT_PROVIDERS)} 중 하나여야 함 (현재: {stt_provider})"
        )

    required = [
        "REDIS_URL",
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        # Azure Speech 는 STT 프로바이더와 무관하게 TTS 가 항상 쓴다.
        "AZURE_SPEECH_KEY",
        "AZURE_SPEECH_REGION",
    ]
    if provider == "openai":
        required.append("OPENAI_API_KEY")
    elif provider == "azure":
        required += ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT"]
    else:
        raise SystemExit(f"TRANSLATE_PROVIDER 는 'openai' 또는 'azure' 여야 함 (현재: {provider})")
    if stt_provider == "openai" and "OPENAI_API_KEY" not in required:
        required.append("OPENAI_API_KEY")

    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"필수 환경변수 누락: {', '.join(missing)} (.env.example 참조)")

    return WorkerConfig(
        redis_url=os.environ["REDIS_URL"],
        livekit_url=os.environ["LIVEKIT_URL"],
        livekit_api_key=os.environ["LIVEKIT_API_KEY"],
        livekit_api_secret=os.environ["LIVEKIT_API_SECRET"],
        azure_speech_key=os.environ["AZURE_SPEECH_KEY"],
        azure_speech_region=os.environ["AZURE_SPEECH_REGION"],
        stt_language=os.environ.get("STT_LANGUAGE", "ko-KR"),
        translate_provider=provider,
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        azure_openai_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        azure_openai_api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
        azure_openai_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
        azure_openai_api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        voice_map=_load_voice_map(),
        segment_max_chars=_load_int("SEGMENT_MAX_CHARS", DEFAULT_SEGMENT_MAX_CHARS),
        segment_idle_flush_ms=_load_int("SEGMENT_IDLE_FLUSH_MS", DEFAULT_SEGMENT_IDLE_FLUSH_MS),
        segment_min_chars=_load_int("SEGMENT_MIN_CHARS", DEFAULT_SEGMENT_MIN_CHARS),
        segment_split_korean_endings=_load_bool(
            "SEGMENT_SPLIT_KOREAN_ENDINGS", DEFAULT_SEGMENT_SPLIT_KOREAN_ENDINGS
        ),
        segment_queue_max_size=_load_int("SEGMENT_QUEUE_MAX_SIZE", DEFAULT_SEGMENT_QUEUE_MAX_SIZE),
        segment_enqueue_timeout_ms=_load_int(
            "SEGMENT_ENQUEUE_TIMEOUT_MS", DEFAULT_SEGMENT_ENQUEUE_TIMEOUT_MS
        ),
        tts_timeout_sec=_load_float("TTS_TIMEOUT_SEC", DEFAULT_TTS_TIMEOUT_SEC),
        tts_max_retries=_load_int("TTS_MAX_RETRIES", DEFAULT_TTS_MAX_RETRIES, min_value=0),
        tts_retry_base_delay_ms=_load_int(
            "TTS_RETRY_BASE_DELAY_MS", DEFAULT_TTS_RETRY_BASE_DELAY_MS, min_value=0
        ),
        tts_max_concurrency=_load_int("TTS_MAX_CONCURRENCY", DEFAULT_TTS_MAX_CONCURRENCY),
        tts_queue_max_size=_load_int("TTS_QUEUE_MAX_SIZE", DEFAULT_TTS_QUEUE_MAX_SIZE),
        tts_dedupe_ttl_sec=_load_int("TTS_DEDUPE_TTL_SEC", DEFAULT_TTS_DEDUPE_TTL_SEC),
        tts_failed_dedupe_ttl_sec=_load_int(
            "TTS_FAILED_DEDUPE_TTL_SEC", DEFAULT_TTS_FAILED_DEDUPE_TTL_SEC, min_value=0
        ),
        session_stop_timeout_sec=_load_float(
            "SESSION_STOP_TIMEOUT_SEC", DEFAULT_SESSION_STOP_TIMEOUT_SEC
        ),
        pipeline_flush_timeout_sec=_load_float(
            "PIPELINE_FLUSH_TIMEOUT_SEC", DEFAULT_PIPELINE_FLUSH_TIMEOUT_SEC
        ),
        tts_flush_timeout_sec=_load_float(
            "TTS_FLUSH_TIMEOUT_SEC", DEFAULT_TTS_FLUSH_TIMEOUT_SEC
        ),
        stt_max_reconnects=_load_int("STT_MAX_RECONNECTS", DEFAULT_STT_MAX_RECONNECTS, min_value=0),
        stt_reconnect_base_delay_ms=_load_int(
            "STT_RECONNECT_BASE_DELAY_MS", DEFAULT_STT_RECONNECT_BASE_DELAY_MS, min_value=0
        ),
        worker_status_ttl_sec=_load_int("WORKER_STATUS_TTL_SEC", DEFAULT_WORKER_STATUS_TTL_SEC),
        stt_segmentation_silence_ms=_load_int(
            "STT_SEGMENTATION_SILENCE_MS", DEFAULT_STT_SEGMENTATION_SILENCE_MS
        ),
        stt_segmentation_max_time_ms=_load_int(
            "STT_SEGMENTATION_MAX_TIME_MS",
            DEFAULT_STT_SEGMENTATION_MAX_TIME_MS,
            min_value=0,
        ),
        stt_initial_silence_ms=_load_int(
            "STT_INITIAL_SILENCE_MS", DEFAULT_STT_INITIAL_SILENCE_MS
        ),
        stt_end_silence_ms=_load_int("STT_END_SILENCE_MS", DEFAULT_STT_END_SILENCE_MS),
        stt_true_text=_load_bool("STT_TRUE_TEXT", True),
        stt_profanity_raw=_load_bool("STT_PROFANITY_RAW", True),
        stt_endpoint_id=os.environ.get("STT_ENDPOINT_ID", "").strip(),
        stt_phrase_list_weight=_load_float(
            "STT_PHRASE_LIST_WEIGHT", DEFAULT_STT_PHRASE_LIST_WEIGHT
        ),
        stt_phrase_list_max_items=_load_int(
            "STT_PHRASE_LIST_MAX_ITEMS", DEFAULT_STT_PHRASE_LIST_MAX_ITEMS
        ),
        stt_phrase_list_max_chars=_load_int(
            "STT_PHRASE_LIST_MAX_CHARS", DEFAULT_STT_PHRASE_LIST_MAX_CHARS
        ),
        stt_low_confidence_warn=_load_float(
            "STT_LOW_CONFIDENCE_WARN", DEFAULT_STT_LOW_CONFIDENCE_WARN, min_value=0.0
        ),
        translate_timeout_sec=_load_float(
            "TRANSLATE_TIMEOUT_SEC", DEFAULT_TRANSLATE_TIMEOUT_SEC
        ),
        rag_enabled=_load_bool("RAG_ENABLED"),
        rag_url=os.environ.get("RAG_URL", "http://rag-service:8000"),
        rag_default_major=os.environ.get("RAG_DEFAULT_MAJOR", "auto").lower(),
        rag_course_major_map=_load_rag_course_major_map(),
        rag_timeout_sec=_load_float("RAG_TIMEOUT_SEC", DEFAULT_RAG_TIMEOUT_SEC),
        rag_assets_dir=os.environ.get("RAG_ASSETS_DIR", DEFAULT_RAG_ASSETS_DIR),
        stt_provider=stt_provider,
        stt_openai_model=os.environ.get("STT_OPENAI_MODEL", DEFAULT_STT_OPENAI_MODEL),
        stt_openai_silence_ms=_load_int(
            "STT_OPENAI_SILENCE_MS", DEFAULT_STT_OPENAI_SILENCE_MS
        ),
        stt_openai_logprobs=_load_bool("STT_OPENAI_LOGPROBS", True),
        stt_openai_keywords_max=_load_int(
            "STT_OPENAI_KEYWORDS_MAX", DEFAULT_STT_OPENAI_KEYWORDS_MAX
        ),
        stt_openai_vad_threshold=_load_float(
            "STT_OPENAI_VAD_THRESHOLD", DEFAULT_STT_OPENAI_VAD_THRESHOLD, min_value=0.0
        ),
        stt_openai_min_confidence=_load_float(
            "STT_OPENAI_MIN_CONFIDENCE", DEFAULT_STT_OPENAI_MIN_CONFIDENCE, min_value=0.0
        ),
    )