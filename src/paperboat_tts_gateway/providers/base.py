from __future__ import annotations

from abc import ABC, abstractmethod

from ..api_models import AudioFormat, SpeechRequest, SynthesisResult, VoiceInfo


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, request: SpeechRequest) -> SynthesisResult:
        raise NotImplementedError

    @abstractmethod
    async def list_voices(self) -> list[VoiceInfo]:
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_formats(self) -> tuple[AudioFormat, ...]:
        raise NotImplementedError
