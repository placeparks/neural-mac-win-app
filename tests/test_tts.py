from __future__ import annotations

from pathlib import Path

import pytest

from neuralclaw.config import VoiceConfig
from neuralclaw.skills.builtins import tts


@pytest.mark.asyncio
async def test_speak_returns_audio_path_and_truncates(tmp_path):
    tts.set_tts_config(
        VoiceConfig(
            enabled=True,
            temp_dir=str(tmp_path),
            max_tts_chars=5,
            output_format="wav",
        )
    )

    result = await tts.speak("hello world", output_format="wav")

    assert "error" not in result
    assert result["truncated"] is True
    assert Path(result["audio_path"]).exists()
    assert result["audio_path"].endswith(".wav")


@pytest.mark.asyncio
async def test_list_voices_uses_configured_provider():
    tts.set_tts_config(VoiceConfig(enabled=True, provider="openai"))

    result = await tts.list_voices()

    assert result["provider"] == "openai"
    assert "alloy" in result["voices"]


@pytest.mark.asyncio
async def test_speak_and_play_uses_registered_adapter(tmp_path):
    tts.set_tts_config(VoiceConfig(enabled=True, temp_dir=str(tmp_path)))

    class FakeAdapter:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def speak(self, audio_path: str, channel_id: str | None = None) -> None:
            self.calls.append((audio_path, channel_id or ""))

    adapter = FakeAdapter()
    tts.register_adapter("discord", adapter)

    result = await tts.speak_and_play("hello", channel_id="123", platform="discord")

    assert result["success"] is True
    assert len(adapter.calls) == 1
    assert adapter.calls[0][1] == "123"
    assert Path(adapter.calls[0][0]).exists()
