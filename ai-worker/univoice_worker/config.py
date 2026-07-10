"""환경변수 로드 — Core API의 .env와 키 이름을 맞춘다 (REDIS_URL, LIVEKIT_*).

파이프라인 단계별로 필요한 키를 한 곳에 모은다:
  - STT/TTS : AZURE_SPEECH_*      (Azure Speech, 하나의 리소스로 STT+TTS 공용)
  - 번역     : TRANSLATE_PROVIDER 에 따라 OpenAI 또는 Azure OpenAI
"""

import json
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# locale → Azure Neural Voice 기본 매핑. TTS_VOICE_MAP(JSON)으로 덮어쓸 수 있다.
DEFAULT_VOICE_MAP = {
    "zh-CN": "zh-CN-XiaoxiaoNeural",
    "vi-VN": "vi-VN-HoaiMyNeural",
    "mn-MN": "mn-MN-YesuiNeural",
    "en-US": "en-US-JennyNeural",
    "ja-JP": "ja-JP-NanamiNeural",
}


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


def _load_voice_map() -> dict[str, str]:
    merged = dict(DEFAULT_VOICE_MAP)
    raw = os.environ.get("TTS_VOICE_MAP")
    if raw:
        try:
            merged.update(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"TTS_VOICE_MAP JSON 파싱 실패: {exc}")
    return merged


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
    )
