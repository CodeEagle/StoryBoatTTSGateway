from __future__ import annotations

import base64
import io
import os
from pathlib import Path
import shutil
import subprocess

import httpx
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

from ..api_models import (
    AudioFormat,
    ProviderName,
    SpeechRequest,
    SynthesisResult,
    TimingSource,
    VoiceInfo,
)
from ..timing import estimate_word_timings
from .base import TTSProvider


class KokoroProvider(TTSProvider):
    DEFAULT_MODEL_URL = "https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0/kokoro-v1.0.onnx"
    DEFAULT_VOICES_URL = "https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0/voices-v1.0.bin"

    def __init__(
        self,
        model_path: str | None = None,
        voices_path: str | None = None,
    ) -> None:
        base_dir = Path(
            os.environ.get(
                "PAPERBOAT_TTS_KOKORO_DIR",
                str(Path.home() / ".cache" / "paperboat-tts-gateway" / "kokoro"),
            )
        )
        self._model_path = Path(model_path) if model_path else base_dir / "kokoro-v1.0.onnx"
        self._voices_path = Path(voices_path) if voices_path else base_dir / "voices-v1.0.bin"
        self._kokoro: Kokoro | None = None

    @property
    def supported_formats(self) -> tuple[AudioFormat, ...]:
        return (AudioFormat.WAV, AudioFormat.MP3)

    async def synthesize(self, request: SpeechRequest) -> SynthesisResult:
        await self._ensure_assets()
        voice = request.voice or "af_sarah"
        lang = request.lang or "en-us"
        samples, sample_rate = self._kokoro_instance.create(
            request.input,
            voice=voice,
            speed=request.speed,
            lang=lang,
        )

        pcm = np.asarray(samples, dtype=np.float32)
        audio_bytes, output_format = self._encode_audio(
            pcm=pcm,
            sample_rate=sample_rate,
            response_format=request.response_format,
        )
        duration_ms = int(round(len(pcm) / sample_rate * 1000))
        words = estimate_word_timings(request.input, duration_ms)

        return SynthesisResult(
            format=output_format,
            audio_base64=base64.b64encode(audio_bytes).decode("ascii"),
            words=words,
            timing_source=TimingSource.ESTIMATED,
            provider=ProviderName.KOKORO,
            voice=voice,
            model=request.model,
            estimated=True,
        )

    async def list_voices(self) -> list[VoiceInfo]:
        await self._ensure_assets()
        voices = sorted(self._kokoro_instance.get_voices())
        return [
            VoiceInfo(
                id=voice,
                name=voice,
                provider=ProviderName.KOKORO,
                locale=None,
                gender=None,
                tags=["blendable"],
            )
            for voice in voices
        ]

    @property
    def _kokoro_instance(self) -> Kokoro:
        if self._kokoro is None:
            raise RuntimeError("Kokoro model is not loaded yet.")
        return self._kokoro

    async def _ensure_assets(self) -> None:
        self._model_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._model_path.exists():
            await self._download_file(self.DEFAULT_MODEL_URL, self._model_path)
        if not self._voices_path.exists():
            await self._download_file(self.DEFAULT_VOICES_URL, self._voices_path)

        if self._kokoro is None:
            self._kokoro = Kokoro(str(self._model_path), str(self._voices_path))

    async def _download_file(self, url: str, destination: Path) -> None:
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with destination.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)

    def _encode_audio(
        self,
        *,
        pcm: np.ndarray,
        sample_rate: int,
        response_format: AudioFormat,
    ) -> tuple[bytes, AudioFormat]:
        wav_buffer = io.BytesIO()
        sf.write(wav_buffer, pcm, sample_rate, format="WAV")
        wav_bytes = wav_buffer.getvalue()

        if response_format == AudioFormat.WAV:
            return wav_bytes, AudioFormat.WAV

        if shutil.which("ffmpeg") is None:
            raise ValueError("Kokoro mp3 output requires ffmpeg on PATH. Use response_format=wav.")

        process = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=wav_bytes,
            capture_output=True,
            check=False,
        )
        if process.returncode != 0 or not process.stdout:
            stderr = process.stderr.decode("utf-8", errors="ignore").strip()
            raise ValueError(f"ffmpeg failed to encode mp3: {stderr or 'unknown error'}")
        return process.stdout, AudioFormat.MP3
