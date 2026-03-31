from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse

from .api_models import (
    APICatalog,
    APIEndpointInfo,
    JobCreateResponse,
    JobEventPayload,
    JobPhase,
    JobStateResponse,
    JobStatus,
    ProviderInfo,
    ProviderName,
    SpeechRequest,
    SynthesisResult,
    VoiceInfo,
)
from .providers.edge_provider import EdgeProvider, OPENAI_VOICE_ALIASES
from .providers.kokoro_provider import KokoroProvider

app = FastAPI(title="StorayBoat TTS Gateway", version="0.2.1")

providers = {
    ProviderName.EDGE: EdgeProvider(),
    ProviderName.KOKORO: KokoroProvider(),
}


@dataclass
class AudioJobRecord:
    id: str
    request: SpeechRequest
    status: JobStatus = JobStatus.QUEUED
    phase: JobPhase = JobPhase.QUEUED
    progress: float = 0.0
    error: str | None = None
    result: SynthesisResult | None = None
    bundle: bytes | None = None
    boundary: str | None = None
    next_event_id: int = 0
    event_history: list[tuple[int, str, dict[str, Any]]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[tuple[str, dict[str, Any]]]] = field(default_factory=set)

    @property
    def download_url(self) -> str | None:
        if self.status in {JobStatus.READY, JobStatus.COMPLETED} and self.bundle is not None:
            return f"/v1/audio/jobs/{self.id}/bundle"
        return None

    def to_state_response(self) -> JobStateResponse:
        return JobStateResponse(
            id=self.id,
            status=self.status,
            phase=self.phase,
            progress=self.progress,
            error=self.error,
            download_url=self.download_url,
        )

    def to_event_payload(self) -> JobEventPayload:
        return JobEventPayload(
            id=self.id,
            status=self.status,
            phase=self.phase,
            progress=self.progress,
            error=self.error,
            download_url=self.download_url,
        )


jobs: dict[str, AudioJobRecord] = {}


def get_provider(name: ProviderName):
    return providers[name]


def require_provider(request: SpeechRequest) -> ProviderName:
    if request.provider is None:
        raise HTTPException(status_code=400, detail="provider is required")
    return request.provider


def build_api_catalog() -> APICatalog:
    provider_infos = [
        ProviderInfo(
            id=ProviderName.EDGE,
            name="Edge TTS",
            default_model="tts-1",
            default_voice="alloy",
            supports_real_word_timing=True,
            supports_estimated_word_timing=False,
            supported_formats=list(get_provider(ProviderName.EDGE).supported_formats),
            supported_response_modes=["json_base64", "multipart_bundle", "job_stream"],
            voice_list_path="/v1/voices?provider=edge",
            synthesize_paths=[
                "/v1/audio/jobs",
                "/v1/audio/jobs/{id}",
                "/v1/audio/jobs/{id}/events",
                "/v1/audio/jobs/{id}/bundle",
                "/v1/audio/speech_with_timestamps",
                "/v1/{provider}/audio/speech_with_timestamps",
                "/v1/audio/speech",
                "/v1/audio/speech_bundle",
            ],
            accepted_voice_aliases=sorted(OPENAI_VOICE_ALIASES.keys()),
            notes=[
                "Voice list returns real Edge voices only.",
                "OpenAI-style aliases are accepted for synthesis input.",
            ],
        ),
        ProviderInfo(
            id=ProviderName.KOKORO,
            name="Kokoro",
            default_model="kokoro",
            default_voice="af_sarah",
            supports_real_word_timing=True,
            supports_estimated_word_timing=False,
            supported_formats=list(get_provider(ProviderName.KOKORO).supported_formats),
            supported_response_modes=["json_base64", "multipart_bundle", "job_stream"],
            voice_list_path="/v1/voices?provider=kokoro",
            synthesize_paths=[
                "/v1/audio/jobs",
                "/v1/audio/jobs/{id}",
                "/v1/audio/jobs/{id}/events",
                "/v1/audio/jobs/{id}/bundle",
                "/v1/audio/speech_with_timestamps",
                "/v1/{provider}/audio/speech_with_timestamps",
                "/v1/audio/speech",
                "/v1/audio/speech_bundle",
            ],
            notes=[
                "Requires a reachable Kokoro-FastAPI backend.",
                "Word timings come from /dev/captioned_speech.",
                "normalization_options can be overridden per request.",
            ],
        ),
    ]
    endpoints = [
        APIEndpointInfo(method="GET", path="/healthz", summary="Health check", response_type="application/json"),
        APIEndpointInfo(method="GET", path="/v1/providers", summary="List providers and capabilities", response_type="application/json"),
        APIEndpointInfo(method="GET", path="/v1/voices?provider={provider}", summary="List voices for a provider", response_type="application/json", provider_optional=False),
        APIEndpointInfo(method="GET", path="/v1/catalog", summary="List all API endpoints and provider capabilities", response_type="application/json"),
        APIEndpointInfo(method="POST", path="/v1/audio/jobs", summary="Create an async synthesis job", response_type="application/json", provider_optional=False),
        APIEndpointInfo(method="GET", path="/v1/audio/jobs/{id}", summary="Query async synthesis job state", response_type="application/json"),
        APIEndpointInfo(method="GET", path="/v1/audio/jobs/{id}/events", summary="Stream async job progress with Server-Sent Events", response_type="text/event-stream"),
        APIEndpointInfo(method="GET", path="/v1/audio/jobs/{id}/bundle", summary="Download multipart metadata.json plus binary audio for a completed job", response_type="multipart/mixed"),
        APIEndpointInfo(method="POST", path="/v1/audio/speech_with_timestamps", summary="Return JSON with audio_base64 and word timings", response_type="application/json", provider_optional=False),
        APIEndpointInfo(method="POST", path="/v1/{provider}/audio/speech_with_timestamps", summary="Provider-scoped JSON synthesis endpoint", response_type="application/json", provider_optional=True),
        APIEndpointInfo(method="POST", path="/v1/audio/speech", summary="Return compatibility JSON with audio_base64 and format", response_type="application/json", provider_optional=False),
        APIEndpointInfo(method="POST", path="/v1/audio/speech_bundle", summary="Return multipart metadata.json plus binary audio", response_type="multipart/mixed", provider_optional=False),
    ]
    return APICatalog(service=app.title, version=app.version, providers=provider_infos, endpoints=endpoints)


def build_multipart_bundle(result: SynthesisResult) -> tuple[bytes, str]:
    boundary = f"storayboat-{uuid4().hex}"
    metadata = result.model_dump(exclude={"audio_base64"})
    metadata_bytes = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
    audio_bytes = base64.b64decode(result.audio_base64)
    audio_filename = f"audio.{result.format.value}"
    audio_content_type = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
    }.get(result.format.value, "application/octet-stream")

    parts = [
        (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            'Content-Disposition: attachment; name="metadata"; filename="metadata.json"\r\n\r\n'
        ).encode("utf-8")
        + metadata_bytes
        + b"\r\n",
        (
            f"--{boundary}\r\n"
            f"Content-Type: {audio_content_type}\r\n"
            f'Content-Disposition: attachment; name="audio"; filename="{audio_filename}"\r\n\r\n'
        ).encode("utf-8")
        + audio_bytes
        + b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(parts), boundary


async def publish_job_event(job: AudioJobRecord, event_type: str) -> None:
    payload = job.to_event_payload().model_dump(mode="json", exclude_none=True)
    job.next_event_id += 1
    event_record = (job.next_event_id, event_type, payload)
    job.event_history.append(event_record)
    for queue in list(job.subscribers):
        await queue.put((event_type, payload))


async def update_job(
    job: AudioJobRecord,
    *,
    status: JobStatus | None = None,
    phase: JobPhase | None = None,
    progress: float | None = None,
    error: str | None = None,
    event_type: str,
) -> None:
    if status is not None:
        job.status = status
    if phase is not None:
        job.phase = phase
    if progress is not None:
        job.progress = min(max(progress, 0.0), 1.0)
    if error is not None:
        job.error = error
    await publish_job_event(job, event_type)


async def run_job(job_id: str) -> None:
    job = jobs[job_id]
    try:
        provider = require_provider(job.request)
        await update_job(
            job,
            status=JobStatus.RUNNING,
            phase=JobPhase.SYNTHESIZING,
            progress=0.05,
            event_type="started",
        )
        result = await get_provider(provider).synthesize(
            job.request,
            on_progress=lambda value: update_job(
                job,
                status=JobStatus.RUNNING,
                phase=JobPhase.SYNTHESIZING,
                progress=value,
                event_type="synth_progress",
            ),
        )
        job.result = result
        await update_job(
            job,
            status=JobStatus.RUNNING,
            phase=JobPhase.PACKAGING,
            progress=max(job.progress, 0.92),
            event_type="packaging",
        )
        bundle, boundary = build_multipart_bundle(result)
        job.bundle = bundle
        job.boundary = boundary
        await update_job(
            job,
            status=JobStatus.READY,
            phase=JobPhase.PACKAGING,
            progress=0.98,
            event_type="bundle_ready",
        )
        await update_job(
            job,
            status=JobStatus.COMPLETED,
            phase=JobPhase.COMPLETED,
            progress=1.0,
            event_type="completed",
        )
    except Exception as exc:
        await update_job(
            job,
            status=JobStatus.FAILED,
            phase=JobPhase.FAILED,
            progress=1.0,
            error=str(exc),
            event_type="failed",
        )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/providers", response_model=list[ProviderInfo])
async def list_providers() -> list[ProviderInfo]:
    return build_api_catalog().providers


@app.get("/v1/catalog", response_model=APICatalog)
async def api_catalog() -> APICatalog:
    return build_api_catalog()


@app.get("/v1/voices", response_model=list[VoiceInfo])
async def list_voices(provider: ProviderName) -> list[VoiceInfo]:
    return await get_provider(provider).list_voices()


@app.post("/v1/audio/jobs", response_model=JobCreateResponse)
async def create_audio_job(request: SpeechRequest) -> JobCreateResponse:
    require_provider(request)
    job = AudioJobRecord(id=f"job_{uuid4().hex}", request=request)
    jobs[job.id] = job
    asyncio.create_task(run_job(job.id))
    return JobCreateResponse(id=job.id, status=job.status)


@app.get("/v1/audio/jobs/{job_id}", response_model=JobStateResponse)
async def get_audio_job(job_id: str) -> JobStateResponse:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_state_response()


@app.get("/v1/audio/jobs/{job_id}/events")
async def stream_audio_job_events(job_id: str) -> StreamingResponse:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
    job.subscribers.add(queue)

    async def event_stream():
        try:
            initial_event = "failed" if job.status == JobStatus.FAILED else "snapshot"
            initial_payload = job.to_event_payload().model_dump(mode="json", exclude_none=True)
            yield f"event: {initial_event}\n".encode("utf-8")
            yield f"data: {json.dumps(initial_payload, ensure_ascii=False)}\n\n".encode("utf-8")

            replay_upto = job.next_event_id
            for event_id, event_type, payload in job.event_history:
                if event_id > replay_upto:
                    break
                yield f"event: {event_type}\n".encode("utf-8")
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

            if replay_upto and job.event_history and job.event_history[-1][0] == replay_upto:
                if job.event_history[-1][1] in {"completed", "failed"}:
                    return

            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                return

            while True:
                event_type, payload = await queue.get()
                yield f"event: {event_type}\n".encode("utf-8")
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
                if event_type in {"completed", "failed"}:
                    break
        finally:
            job.subscribers.discard(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/v1/audio/jobs/{job_id}/bundle")
async def download_audio_job_bundle(job_id: str) -> Response:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.bundle is None or job.boundary is None:
        raise HTTPException(status_code=409, detail="Bundle not ready")
    return Response(
        content=job.bundle,
        media_type=f'multipart/mixed; boundary="{job.boundary}"',
        headers={
            "Content-Length": str(len(job.bundle)),
            "Accept-Ranges": "bytes",
        },
    )


@app.post("/v1/audio/speech_with_timestamps", response_model=SynthesisResult)
async def speech_with_timestamps(request: SpeechRequest) -> SynthesisResult:
    try:
        return await get_provider(require_provider(request)).synthesize(request)
    except Exception as exc:  # pragma: no cover - translated for API callers
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/{provider}/audio/speech_with_timestamps", response_model=SynthesisResult)
async def provider_speech_with_timestamps(provider: ProviderName, request: SpeechRequest) -> SynthesisResult:
    merged = request.model_copy(update={"provider": provider})
    return await speech_with_timestamps(merged)


@app.post("/v1/audio/speech")
async def speech_passthrough(request: SpeechRequest) -> dict[str, str]:
    result = await speech_with_timestamps(request)
    return {"audio_base64": result.audio_base64, "format": result.format.value}


@app.post("/v1/audio/speech_bundle")
async def speech_bundle(request: SpeechRequest) -> Response:
    result = await speech_with_timestamps(request)
    payload, boundary = build_multipart_bundle(result)
    return Response(
        content=payload,
        media_type=f'multipart/mixed; boundary="{boundary}"',
    )


def main() -> None:
    uvicorn.run(
        "storayboat_tts_gateway.app:app",
        host="0.0.0.0",
        port=5051,
        reload=False,
    )


if __name__ == "__main__":
    main()
