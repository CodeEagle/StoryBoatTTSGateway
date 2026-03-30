# StorayBoat TTS Gateway

一个独立的 FastAPI 网关，把 `Edge TTS` 和 `Kokoro` 统一成一套适合 `PaperBoat` / `Custom API` 接入的协议。

## 当前能力

- `Edge TTS`
  - 返回真实 `WordBoundary` 词级时间戳
  - `GET /v1/voices?provider=edge` 返回完整 Edge voice 列表
  - 额外包含 OpenAI 风格 voice alias: `alloy / echo / fable / nova / onyx / shimmer`
- `Kokoro`
  - 返回可直接用于高亮的 `words`
  - 当前时间戳来源是估算值，`timing_source=estimated`
  - 支持列出 Kokoro voices

## 安装

```bash
cd /Users/lincoln/Develop/GitHub/PaperBoatTTSGateway
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

`Kokoro` 模型现在会在首次使用时自动下载，不需要手动把文件放到仓库根目录。

默认下载位置：

- `~/.cache/paperboat-tts-gateway/kokoro/kokoro-v1.0.onnx`
- `~/.cache/paperboat-tts-gateway/kokoro/voices-v1.0.bin`

如果你想改位置，可以设置：

```bash
export PAPERBOAT_TTS_KOKORO_DIR=/custom/path/to/kokoro-assets
```

如果你要让 `Kokoro` 输出 `mp3`，本机还需要 `ffmpeg`；否则用 `wav` 就可以直接工作。

## 启动

```bash
paperboat-tts-gateway
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

### 3. 合成并返回音频 + 词级时间戳

```bash
curl -X POST http://127.0.0.1:5051/v1/audio/speech_with_timestamps \
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

返回结构：

```json
{
  "format": "mp3",
  "audio_base64": "...",
  "words": [
    { "text": "Hello", "start_ms": 0, "end_ms": 350 },
    { "text": "world", "start_ms": 351, "end_ms": 720 },
    { "text": ".", "start_ms": 721, "end_ms": 760 }
  ],
  "timing_source": "word_boundary",
  "provider": "edge",
  "voice": "en-US-AvaNeural",
  "model": "tts-1",
  "estimated": false
}
```

## 给 PaperBoat 的接法

如果你走 `Custom API -> generic JSON`，这个服务已经兼容 `audio_base64 + words + format`：

- endpoint: `http://<host>:5051/v1/audio/speech_with_timestamps`
- body 里要带 `provider`
- `Edge` 推荐 `response_format=mp3`
- `Kokoro` 推荐 `response_format=wav`

## 说明

- `Edge` 的词级时间戳是真实边界。
- `Kokoro` 目前是按整段音频时长做 token 级估算，足够驱动阅读高亮，但不是强制对齐结果。
- `Kokoro` 的模型文件会在第一次列出声音或第一次合成时自动下载。
- 如果后面接入更强的对齐器，`Kokoro` 可以升级成真实词级时间戳，而不用改客户端协议。
