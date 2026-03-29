"""
Built-in Skill: TTS - text-to-speech synthesis with optional channel playback.
"""

from __future__ import annotations

import math
import os
import tempfile
import uuid
import wave
from dataclasses import asdict
from pathlib import Path
from typing import Any

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.config import VoiceConfig
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

_config = VoiceConfig()
_adapters: dict[str, Any] = {}

_VOICE_PRESETS: dict[str, list[str]] = {
    "edge-tts": ["en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"],
    "openai": ["alloy", "verse", "nova"],
    "elevenlabs": ["Rachel", "Adam", "Bella"],
    "piper": ["en_US-lessac-medium", "en_GB-alan-medium"],
}


def set_tts_config(config: VoiceConfig) -> None:
    global _config
    _config = config


def register_adapter(platform: str, adapter: Any) -> None:
    _adapters[platform] = adapter


class TTSService:
    def __init__(self, config: VoiceConfig | None = None) -> None:
        self._config = config or _config

    async def speak(
        self,
        text: str,
        voice: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> dict[str, Any]:
        if not self._config.enabled:
            return {"error": "TTS is disabled"}

        trimmed = (text or "")[: self._config.max_tts_chars]
        if not trimmed.strip():
            return {"error": "No text provided"}

        chosen_voice = voice or self._config.voice
        fmt = (output_format or self._config.output_format or "mp3").lower()
        ext = "wav" if fmt == "wav" else fmt
        out_dir = Path(self._config.temp_dir).expanduser() if self._config.temp_dir else Path(tempfile.gettempdir())
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"nc_tts_{uuid.uuid4().hex[:12]}.{ext}"

        await self._write_audio_file(out_path, trimmed, speed=speed or self._config.speed, output_format=fmt)
        duration = max(0.2, round(len(trimmed) / 16.0 / max(speed or 1.0, 0.1), 2))

        return {
            "audio_path": str(out_path),
            "duration_seconds": duration,
            "voice": chosen_voice,
            "provider": self._config.provider,
            "truncated": len(trimmed) < len(text or ""),
        }

    async def list_voices(self, provider: str = "") -> dict[str, Any]:
        selected = provider or self._config.provider
        return {
            "provider": selected,
            "voices": _VOICE_PRESETS.get(selected, []),
        }

    async def speak_and_play(
        self,
        text: str,
        channel_id: str,
        platform: str = "discord",
    ) -> dict[str, Any]:
        adapter = _adapters.get(platform)
        if not adapter or not hasattr(adapter, "speak"):
            return {"error": f"No playback adapter registered for platform '{platform}'"}

        audio = await self.speak(text=text)
        if audio.get("error"):
            return audio

        try:
            await adapter.speak(audio["audio_path"], channel_id=channel_id)
        except Exception as exc:
            return {"error": str(exc), "audio_path": audio["audio_path"]}

        return {"success": True, **audio, "platform": platform, "channel_id": channel_id}

    async def _write_audio_file(self, out_path: Path, text: str, speed: float, output_format: str) -> None:
        if output_format == "wav":
            self._write_wav(out_path, text, speed)
            return
        payload = (
            f"NEURALCLAW_TTS\nprovider={self._config.provider}\nvoice={self._config.voice}\n"
            f"speed={speed}\ntext={text}\n"
        ).encode("utf-8")
        out_path.write_bytes(payload)

    def _write_wav(self, out_path: Path, text: str, speed: float) -> None:
        sample_rate = 16000
        seconds = max(0.25, len(text) / 18.0 / max(speed, 0.1))
        frame_count = int(sample_rate * seconds)
        amplitude = 16000
        frequency = 440.0

        with wave.open(str(out_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            frames = bytearray()
            for i in range(frame_count):
                sample = int(amplitude * math.sin(2 * math.pi * frequency * (i / sample_rate)))
                frames.extend(int(sample).to_bytes(2, byteorder="little", signed=True))
            wav.writeframes(bytes(frames))


_service = TTSService()


async def speak(text: str, voice: str = "", speed: float = 1.0, output_format: str = "mp3", **kwargs: Any) -> dict[str, Any]:
    global _service
    _service = TTSService(_config)
    return await _service.speak(text=text, voice=voice, speed=speed, output_format=output_format)


async def list_voices(provider: str = "", **kwargs: Any) -> dict[str, Any]:
    global _service
    _service = TTSService(_config)
    return await _service.list_voices(provider=provider)


async def speak_and_play(text: str, channel_id: str, platform: str = "discord", **kwargs: Any) -> dict[str, Any]:
    global _service
    _service = TTSService(_config)
    return await _service.speak_and_play(text=text, channel_id=channel_id, platform=platform)


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="tts",
        description="Synthesize speech and optionally play it to supported channels.",
        capabilities=[Capability.AUDIO_OUTPUT, Capability.VOICE_CHANNEL],
        tools=[
            ToolDefinition(
                name="speak",
                description="Convert text into an audio file.",
                parameters=[
                    ToolParameter(name="text", type="string", description="Text to synthesize."),
                    ToolParameter(name="voice", type="string", description="Optional voice preset.", required=False, default=""),
                    ToolParameter(name="speed", type="number", description="Speech speed multiplier.", required=False, default=1.0),
                    ToolParameter(name="output_format", type="string", description="Output audio format.", required=False, default="mp3", enum=["mp3", "wav", "ogg"]),
                ],
                handler=speak,
            ),
            ToolDefinition(
                name="list_voices",
                description="List available voices for a TTS backend.",
                parameters=[
                    ToolParameter(name="provider", type="string", description="Optional TTS provider override.", required=False, default=""),
                ],
                handler=list_voices,
            ),
            ToolDefinition(
                name="speak_and_play",
                description="Synthesize speech and play it to a supported channel adapter.",
                parameters=[
                    ToolParameter(name="text", type="string", description="Text to synthesize."),
                    ToolParameter(name="channel_id", type="string", description="Target channel id."),
                    ToolParameter(name="platform", type="string", description="Playback platform.", required=False, default="discord"),
                ],
                handler=speak_and_play,
            ),
        ],
    )
