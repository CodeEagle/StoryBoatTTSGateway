# StorayBoat TTS Gateway

一个独立的 FastAPI 网关，把 `Edge TTS` 和 `Kokoro` 统一成一套通用协议。

## 当前能力

- `Edge TTS`
  - 返回真实 `WordBoundary` 词级时间戳
  - `GET /v1/voices?provider=edge` 返回完整 Edge voice 列表
  - 额外包含 OpenAI 风格 voice alias: `alloy / echo / fable / nova / onyx / shimmer`
- `Kokoro-FastAPI`
  - 通过 `GET /v1/audio/voices` 获取声音列表
  - 通过 `POST /dev/captioned_speech` 获取音频和逐词时间戳
  - 直接复用 `Kokoro-FastAPI` 的真实时间戳结果

## 安装

```bash
cd /Users/lincoln/Develop/GitHub/StorayBoatTTSGateway
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

如果你要用 `Kokoro`，先单独启动一个 `Kokoro-FastAPI` 服务。

最简单的方式是直接跑官方镜像：

```bash
docker run -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-cpu:latest
```

然后把网关指向它：

```bash
export KOKORO_FASTAPI_BASE_URL=http://127.0.0.1:8880
```

## 一体化启动

现在仓库里已经把 `Kokoro-FastAPI` 一并集成进来了，最省事的启动方式是直接用 Docker Compose：

```bash
cp .env.example .env
docker compose up --build
```

启动后：

- 网关：`http://127.0.0.1:5051`
- Kokoro-FastAPI：`http://127.0.0.1:8880`

相关文件：

- [docker-compose.yml](/Users/lincoln/Develop/GitHub/StorayBoatTTSGateway/docker-compose.yml)
- [Dockerfile](/Users/lincoln/Develop/GitHub/StorayBoatTTSGateway/Dockerfile)
- [.env.example](/Users/lincoln/Develop/GitHub/StorayBoatTTSGateway/.env.example)

## 启动

```bash
storayboat-tts-gateway
```

默认监听：

- `http://127.0.0.1:5051`

## API

### 1. 获取 provider 列表

```bash
curl http://127.0.0.1:5051/v1/providers
```

### 2. 获取 voice 列表

```bash
curl 'http://127.0.0.1:5051/v1/voices?provider=edge'
curl 'http://127.0.0.1:5051/v1/voices?provider=kokoro'
```

`Edge` 的 voice 列表会按 app 里同样的目录解析方式输出：

- 使用同源的 Edge voice catalog 文本
- 清洗 `Neural / MultilingualNeural` 后缀
- 附带 `locale / language_name / country / alias_of`

### 2.5. 获取完整 API 目录

```bash
curl 'http://127.0.0.1:5051/v1/catalog'
```

这个接口会返回：

- providers 能力列表
- 每个 provider 的默认 model / 默认 voice / 支持的返回模式
- 每个 provider 的 voice 列表地址和可接受 alias
- 所有 API 的 method / path / summary / response_type

### 3. 合成并返回音频 + 词级时间戳

```bash
curl -X POST http://127.0.0.1:5051/v1/audio/speech_with_timestamps \
  -H 'Content-Type: application/json' \
  -d '{
    "provider": "kokoro",
    "model": "kokoro",
    "input": "Hello world!",
    "voice": "af_bella",
    "response_format": "mp3",
    "speed": 1.0
  }'
```

返回结构：

```json
{
  "format": "mp3",
  "audio_base64": "...",
  "words": [
    { "text": "Hello", "start_ms": 0, "end_ms": 350 },
    { "text": "world", "start_ms": 360, "end_ms": 720 }
  ],
  "timing_source": "word_boundary",
  "provider": "kokoro",
  "voice": "af_bella",
  "model": "kokoro",
  "estimated": false
}
```

### 4. 更省流量的 multipart 返回

如果你不想承担 `base64` 的额外体积，可以改用：

```bash
curl -X POST http://127.0.0.1:5051/v1/audio/speech_bundle \
  -H 'Content-Type: application/json' \
  -d '{
    "provider": "edge",
    "model": "tts-1",
    "input": "Hello world.",
    "voice": "alloy",
    "response_format": "mp3",
    "speed": 1.0
  }'
```

响应是 `multipart/mixed`，包含两个 part：

- `metadata.json`
- `audio.mp3` 或 `audio.wav`

## 配置项

- `KOKORO_FASTAPI_BASE_URL`
  默认 `http://127.0.0.1:8880`
- `KOKORO_FASTAPI_TIMEOUT`
  默认 `120`
- `KOKORO_FASTAPI_IMAGE`
  默认 `ghcr.io/remsky/kokoro-fastapi-cpu:v0.2.4`
- `KOKORO_FASTAPI_PORT`
  默认 `8880`
- `STORAYBOAT_PORT`
  默认 `5051`

## 说明

- `Edge` 的词级时间戳是真实边界。
- `Kokoro` 的词级时间戳来自 `Kokoro-FastAPI` 的 `/dev/captioned_speech`。
- 为了减少文本归一化导致的丢词，这个网关默认会带上 `normalization_options.normalize=false` 转发给 `Kokoro-FastAPI`。
- 参考：[`Kokoro-FastAPI` README](https://github.com/remsky/Kokoro-FastAPI)
