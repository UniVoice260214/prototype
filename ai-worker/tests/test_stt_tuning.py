from __future__ import annotations

from univoice_worker.stt import (
    SttTuning,
    _configure_speech,
    clamp_segmentation_max_time,
)


class FakeSpeechConfig:
    """set_property 호출을 기록하는 SpeechConfig 대역."""

    def __init__(self) -> None:
        self.properties: dict[object, str] = {}
        self.speech_recognition_language = ""
        self.output_format = None

    def set_property(self, property_id: object, value: str) -> None:
        self.properties[property_id] = value

    def set_profanity(self, option: object) -> None:
        self.profanity = option


def _property_values(config: FakeSpeechConfig) -> dict[str, str]:
    return {str(k): v for k, v in config.properties.items()}


def test_clamp_segmentation_max_time_range() -> None:
    assert clamp_segmentation_max_time(0) == 0
    assert clamp_segmentation_max_time(-5) == 0
    assert clamp_segmentation_max_time(10_000) == 20_000   # 하한 보정
    assert clamp_segmentation_max_time(20_000) == 20_000
    assert clamp_segmentation_max_time(45_000) == 45_000
    assert clamp_segmentation_max_time(90_000) == 70_000   # 상한 보정


def test_configure_speech_sets_time_strategy_and_max_time() -> None:
    config = FakeSpeechConfig()

    _configure_speech(config, "ko-KR", SttTuning(segmentation_max_time_ms=30_000))

    values = _property_values(config)
    strategy = [v for k, v in values.items() if "SegmentationStrategy" in k]
    max_time = [v for k, v in values.items() if "SegmentationMaximumTimeMs" in k]
    assert strategy == ["Time"]
    assert max_time == ["30000"]


def test_configure_speech_skips_time_strategy_when_disabled() -> None:
    config = FakeSpeechConfig()

    _configure_speech(config, "ko-KR", SttTuning(segmentation_max_time_ms=0))

    values = _property_values(config)
    assert not any("SegmentationStrategy" in k for k in values)
    assert not any("SegmentationMaximumTimeMs" in k for k in values)
    # 기존 침묵 기반 튜닝은 그대로 적용되어야 한다.
    assert any("SegmentationSilenceTimeoutMs" in k for k in values)
