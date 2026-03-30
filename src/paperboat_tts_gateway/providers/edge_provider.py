from __future__ import annotations

import base64
from typing import Any

import edge_tts

from ..api_models import (
    AudioFormat,
    ProviderName,
    SpeechRequest,
    SynthesisResult,
    TimingSource,
    VoiceInfo,
    WordTiming,
)
from .base import TTSProvider

OPENAI_VOICE_ALIASES: dict[str, str] = {
    "alloy": "en-US-AvaNeural",
    "echo": "en-US-AndrewNeural",
    "fable": "en-GB-SoniaNeural",
    "nova": "en-US-AriaNeural",
    "onyx": "en-US-ChristopherNeural",
    "shimmer": "en-US-AnaNeural",
}


class EdgeProvider(TTSProvider):
    @property
    def supported_formats(self) -> tuple[AudioFormat, ...]:
        return (AudioFormat.MP3,)

    async def synthesize(self, request: SpeechRequest) -> SynthesisResult:
        if request.response_format != AudioFormat.MP3:
            raise ValueError("Edge provider currently supports mp3 only.")

        voice = self._resolve_voice(request.voice)
        rate = self._speed_to_rate(request.speed)
        communicator = edge_tts.Communicate(
            text=request.input,
            voice=voice,
            rate=rate,
            boundary="WordBoundary",
        )

        audio_chunks: list[bytes] = []
        words: list[WordTiming] = []
        async for chunk in communicator.stream():
            chunk_type = chunk.get("type")
            if chunk_type == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk_type == "WordBoundary":
                timing = self._word_timing_from_chunk(chunk)
                if timing is not None:
                    words.append(timing)

        audio_bytes = b"".join(audio_chunks)
        return SynthesisResult(
            format=AudioFormat.MP3,
            audio_base64=base64.b64encode(audio_bytes).decode("ascii"),
            words=words,
            timing_source=TimingSource.WORD_BOUNDARY,
            provider=ProviderName.EDGE,
            voice=voice,
            model=request.model,
            estimated=False,
        )

    async def list_voices(self) -> list[VoiceInfo]:
        upstream = await edge_tts.list_voices()
        catalog: list[VoiceInfo] = []

        for voice in upstream:
            tags = [voice.get("VoiceTag", {}).get("ContentCategories", [])]
            flattened = [tag for group in tags for tag in group]
            catalog.append(
                VoiceInfo(
                    id=voice["ShortName"],
                    name=voice["FriendlyName"],
                    provider=ProviderName.EDGE,
                    locale=voice.get("Locale"),
                    gender=voice.get("Gender"),
                    tags=flattened,
                )
            )

        aliases = [
            VoiceInfo(
                id=alias,
                name=f"{alias} -> {target}",
                provider=ProviderName.EDGE,
                locale=None,
                gender=None,
                tags=["openai-alias"],
            )
            for alias, target in OPENAI_VOICE_ALIASES.items()
        ]
        return aliases + sorted(catalog, key=lambda item: (item.locale or "", item.name))

    def _resolve_voice(self, requested: str | None) -> str:
        if not requested:
            return OPENAI_VOICE_ALIASES["alloy"]
        return OPENAI_VOICE_ALIASES.get(requested, requested)

    def _speed_to_rate(self, speed: float) -> str:
        delta = round((speed - 1.0) * 100)
        sign = "+" if delta >= 0 else ""
        return f"{sign}{delta}%"

    def _word_timing_from_chunk(self, chunk: dict[str, Any]) -> WordTiming | None:
        text = chunk.get("text")
        offset = chunk.get("offset")
        duration = chunk.get("duration")
        if not text or offset is None or duration is None:
            return None

        start_ms = int(offset / 10_000)
        end_ms = int((offset + duration) / 10_000)
        return WordTiming(text=text, start_ms=start_ms, end_ms=end_ms)
