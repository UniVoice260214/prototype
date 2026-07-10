"""Segmenter — STT final 텍스트를 번역 단위(완성 문장)로 정리.

아키텍처 가이드의 파이프라인 순서상 STT 다음 단계.
Azure STT 의 `recognized`(final)는 보통 한 발화 단위지만,
한 번에 여러 문장이 확정되거나 문장이 잘려 올 수 있으므로:
  - 문장 종결부호(. ! ? 。 ！ ？ …)에서 끊어 완성 문장만 방출
  - 종결되지 않은 꼬리는 버퍼에 남겼다가 다음 final 과 이어붙인다

번역/TTS 는 비싸므로 "완성 문장"에서만 트리거한다는 원칙(가이드)을 지킨다.
"""

import re

# 종결부호(뒤따르는 닫는 따옴표/괄호까지 흡수)
_SENTENCE_END = re.compile(r'[.!?。！？…]+["\'”’)\]】」』]*\s*')


class Segmenter:
    def __init__(self) -> None:
        self._buffer = ""

    def push(self, final_text: str) -> list[str]:
        """final 텍스트를 받아 완성된 문장 리스트를 반환 (없으면 빈 리스트)."""
        text = (self._buffer + " " + final_text).strip() if self._buffer else final_text.strip()
        if not text:
            return []

        sentences: list[str] = []
        last_end = 0
        for m in _SENTENCE_END.finditer(text):
            sentence = text[last_end : m.end()].strip()
            if sentence:
                sentences.append(sentence)
            last_end = m.end()

        # 종결부호 뒤 남은 조각은 다음 final 과 이어붙이도록 버퍼에 보관
        self._buffer = text[last_end:].strip()
        return sentences

    def flush(self) -> list[str]:
        """세션 종료 등에서 버퍼에 남은 미완성 문장을 강제로 방출."""
        remaining = self._buffer.strip()
        self._buffer = ""
        return [remaining] if remaining else []
