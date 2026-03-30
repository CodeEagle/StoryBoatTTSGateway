from __future__ import annotations

import uvicorn
from fastapi import FastAPI, HTTPException

from .api_models import ProviderInfo, ProviderName, SpeechRequest, SynthesisResult, VoiceInfo
from .providers.edge_provider import EdgeProvider
from .providers.kokoro_provider import KokoroProvider

app = FastAPI(title="PaperBoat TTS Gateway", version="0.1.0")

providers = {
    ProviderName.EDGE: EdgeProvider(),
    ProviderName.KOKORO: KokoroProvider(),
}


def get_provider(name: ProviderName):
    return providers[name]


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/providers", response_model=list[ProviderInfo])
async def list_providers() -> list[ProviderInfo]:
    return [
        ProviderInfo(
            id=ProviderName.EDGE,
            name="Edge TTS",
            supports_real_word_timing=True,
            supports_estimated_word_timing=False,
            supported_formats=list(get_provider(ProviderName.EDGE).supported_formats),
        ),
        ProviderInfo(
            id=ProviderName.KOKORO,
            name="Kokoro",
            supports_real_word_timing=False,
            supports_estimated_word_timing=True,
            supported_formats=list(get_provider(ProviderName.KOKORO).supported_formats),
        ),
    ]


@app.get("/v1/voices", response_model=list[VoiceInfo])
async def list_voices(provider: ProviderName) -> list[VoiceInfo]:
    return await get_provider(provider).list_voices()


@app.post("/v1/audio/speech_with_timestamps", response_model=SynthesisResult)
async def speech_with_timestamps(request: SpeechRequest) -> SynthesisResult:
    try:
        return await get_provider(request.provider).synthesize(request)
    except Exception as exc:  # pragma: no cover - translated for API callers
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/{provider}/audio/speech_with_timestamps", response_model=SynthesisResult)
async def provider_speech_with_timestamps(provider: ProviderName, request: SpeechRequest) -> SynthesisResult:
    merged = request.model_copy(update={"provider": provider})
    return await speech_with_timestamps(merged)


@app.post("/v1/audio/speech")
async def speech_passthrough(request: SpeechRequest) -> dict[str, str]:
    result = await speech_with_timestamps(request)
    return {"audio_base64": result.audio_base64, "format": result.format.value}


def main() -> None:
    uvicorn.run(
        "paperboat_tts_gateway.app:app",
        host="0.0.0.0",
        port=5051,
        reload=False,
    )


if __name__ == "__main__":
    main()
