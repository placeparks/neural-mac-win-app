from __future__ import annotations

import base64

import pytest

from neuralclaw.config import DesktopConfig, PolicyConfig
from neuralclaw.cortex.action.desktop import DesktopCortex


class FakeCapture:
    def capture(self, monitor: int):
        return {
            "image_bytes": b"fake-png-bytes",
            "width": 640,
            "height": 480,
        }


class FakeInput:
    def __init__(self) -> None:
        self.click_calls = []
        self.write_calls = []
        self.hotkey_calls = []

    def click(self, **kwargs):
        self.click_calls.append(kwargs)

    def write(self, text, interval=0.05):
        self.write_calls.append((text, interval))

    def hotkey(self, *keys):
        self.hotkey_calls.append(keys)


class FakeClipboard:
    def __init__(self) -> None:
        self.value = ""

    def get(self):
        return self.value

    def set(self, text: str):
        self.value = text


@pytest.mark.asyncio
async def test_desktop_screenshot_returns_b64():
    cortex = DesktopCortex(
        config=DesktopConfig(enabled=True, screenshot_on_action=False),
        capture_backend=FakeCapture(),
    )

    result = await cortex.screenshot()

    assert result["width"] == 640
    assert result["height"] == 480
    assert base64.b64decode(result["screenshot_b64"]) == b"fake-png-bytes"


@pytest.mark.asyncio
async def test_desktop_actions_blocked_when_disabled():
    cortex = DesktopCortex(
        config=DesktopConfig(enabled=False),
        capture_backend=FakeCapture(),
        input_backend=FakeInput(),
        clipboard_backend=FakeClipboard(),
    )

    screenshot = await cortex.screenshot()
    click = await cortex.click(10, 10)
    clipboard = await cortex.get_clipboard()

    assert "error" in screenshot
    assert "disabled" in screenshot["error"].lower()
    assert "error" in click
    assert "disabled" in click["error"].lower()
    assert "error" in clipboard
    assert "disabled" in clipboard["error"].lower()


@pytest.mark.asyncio
async def test_desktop_click_respects_blocked_regions():
    input_backend = FakeInput()
    cortex = DesktopCortex(
        config=DesktopConfig(enabled=True, screenshot_on_action=False),
        policy=PolicyConfig(desktop_blocked_regions=["0,0,100,100"]),
        capture_backend=FakeCapture(),
        input_backend=input_backend,
    )

    result = await cortex.click(50, 50)

    assert "error" in result
    assert not input_backend.click_calls


@pytest.mark.asyncio
async def test_desktop_clipboard_roundtrip():
    clipboard = FakeClipboard()
    cortex = DesktopCortex(
        config=DesktopConfig(enabled=True, screenshot_on_action=False),
        clipboard_backend=clipboard,
    )

    set_result = await cortex.set_clipboard("hello")
    get_result = await cortex.get_clipboard()

    assert set_result["success"] is True
    assert get_result["text"] == "hello"
