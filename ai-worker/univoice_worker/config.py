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

DEFAULT_SEGMENT_MAX_CHARS = 120
DEFAULT_SEGMENT_IDLE_FLUSH_MS = 2000
DEFAULT_SEGMENT_MIN_CHARS = 2
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
    segment_queue_max_size: int = DEFAULT_SEGMENT_QUEUE_MAX_SIZE
    segment_enqueue_timeout_ms: int = DEFAULT_SEGMENT_ENQUEUE_TIMEOUT_MS
    tts_timeout_sec: float = DEFAULT_TTS_TIMEOUT_SEC
    tts_max_retries: int = DEFAULT_TTS_MAX_RETRIES
    tts_retry_base_delay_ms: int = DEFAULT_TTS_RETRY_BASE_DELAY_MS
    tts_max_concurrency: int = DEFAULT_TTS_MAX_CONCURRENCY
    tts_queue_max_size: int = DEFAULT_TTS_QUEUE_MAX_SIZE
    tts_dedupe_ttl_sec: int = DEFAULT_TTS_DEDUPE_TTL_SEC
    tts_failed_dedupe_ttl_sec: int = DEFAULT_TTS_FAILED_DEDUPE_TTL_SEC
    stt_max_reconnects: int = DEFAULT_STT_MAX_RECONNECTS
    stt_reconnect_base_delay_ms: int = DEFAULT_STT_RECONNECT_BASE_DELAY_MS
    worker_status_ttl_sec: int = DEFAULT_WORKER_STATUS_TTL_SEC
    rag_enabled: bool = False
    rag_url: str = ""
    rag_default_major: str = "auto"
    rag_course_major_map: dict[str, str] = field(default_factory=dict)
    rag_timeout_sec: float = DEFAULT_RAG_TIMEOUT_SEC


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

    required = [
        "REDIS_URL",
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "AZURE_SPEECH_KEY",
        "AZURE_SPEECH_REGION",
    ]
    if provider == "openai":
        required.append("OPENAI_API_KEY")
    elif provider == "azure":
        required += ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT"]
    else:
        raise SystemExit(f"TRANSLATE_PROVIDER 는 'openai' 또는 'azure' 여야 함 (현재: {provider})")

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
        stt_max_reconnects=_load_int("STT_MAX_RECONNECTS", DEFAULT_STT_MAX_RECONNECTS, min_value=0),
        stt_reconnect_base_delay_ms=_load_int(
            "STT_RECONNECT_BASE_DELAY_MS", DEFAULT_STT_RECONNECT_BASE_DELAY_MS, min_value=0
        ),
        worker_status_ttl_sec=_load_int("WORKER_STATUS_TTL_SEC", DEFAULT_WORKER_STATUS_TTL_SEC),
        rag_enabled=_load_bool("RAG_ENABLED"),
        rag_url=os.environ.get("RAG_URL", "http://rag-service:8000"),
        rag_default_major=os.environ.get("RAG_DEFAULT_MAJOR", "auto").lower(),
        rag_course_major_map=_load_rag_course_major_map(),
        rag_timeout_sec=_load_float("RAG_TIMEOUT_SEC", DEFAULT_RAG_TIMEOUT_SEC),
    )