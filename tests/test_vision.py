from __future__ import annotations

from types import SimpleNamespace

import pytest

from neuralclaw.bus.neural_bus import NeuralBus
from neuralclaw.cortex.perception.vision import VisionPerception


class FakeVisionProvider:
    def __init__(self) -> None:
        self.calls = []

    async def complete(self, messages, tools=None, temperature=0.7, max_tokens=4096):
        self.calls.append(messages)
        prompt = messages[-1]["content"][0]["text"]
        if "return only JSON" in prompt:
            return SimpleNamespace(content='{"x": 12, "y": 34, "confidence": 0.91}')
        if "Extract all readable text" in prompt:
            return SimpleNamespace(content="TOTAL: $42")
        if "Question:" in prompt:
            return SimpleNamespace(content="The invoice total is $42.")
        return SimpleNamespace(content="A red button is visible.")


@pytest.mark.asyncio
async def test_vision_describe_uses_multimodal_message_blocks():
    provider = FakeVisionProvider()
    vision = VisionPerception(provider, NeuralBus())

    result = await vision.describe("ZmFrZQ==", context="describe the UI")

    assert result == "A red button is visible."
    image_block = provider.calls[0][-1]["content"][1]
    assert image_block["type"] == "image_url"
    assert image_block["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_vision_process_media_routes_to_ocr_for_text_queries():
    provider = FakeVisionProvider()
    vision = VisionPerception(provider, NeuralBus())

    result = await vision.process_media({"data": "ZmFrZQ==", "mime_type": "image/png"}, "please extract text")

    assert "TOTAL: $42" in result


@pytest.mark.asyncio
async def test_vision_locate_element_parses_json_response():
    provider = FakeVisionProvider()
    vision = VisionPerception(provider, NeuralBus())

    result = await vision.locate_element("ZmFrZQ==", "submit button")

    assert result == {"x": 12, "y": 34, "confidence": 0.91}
