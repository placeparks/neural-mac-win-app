from __future__ import annotations

from types import SimpleNamespace

import pytest

from neuralclaw.config import BrowserConfig, NeuralClawConfig, ProviderConfig
from neuralclaw.cortex.action.browser import BrowserCortex
from neuralclaw.gateway import NeuralClawGateway


class FakeMouse:
    def __init__(self) -> None:
        self.clicks = []
        self.wheels = []

    async def click(self, x, y):
        self.clicks.append((x, y))

    async def wheel(self, x, y):
        self.wheels.append((x, y))


class FakeKeyboard:
    def __init__(self) -> None:
        self.typed = []

    async def type(self, text):
        self.typed.append(text)


class FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com"
        self.goto_calls = []
        self.click_calls = []
        self.fill_calls = []
        self.wait_calls = []
        self.mouse = FakeMouse()
        self.keyboard = FakeKeyboard()

    async def goto(self, url, timeout=None, wait_until=None):
        self.goto_calls.append((url, timeout, wait_until))
        self.url = url

    async def screenshot(self, type="png"):
        return b"fake-png"

    async def evaluate(self, script):
        if "document.body?.innerText" in script:
            return "Checkout page with total $10"
        if "querySelectorAll" in script:
            return [{"tag": "button", "text": "Submit", "type": ""}]
        return {"ok": True}

    async def title(self):
        return "Example"

    async def click(self, selector):
        self.click_calls.append(selector)

    async def fill(self, selector, text):
        self.fill_calls.append((selector, text))

    async def wait_for_selector(self, selector, timeout=None):
        self.wait_calls.append(("selector", selector, timeout))

    async def wait_for_load_state(self, state, timeout=None):
        self.wait_calls.append(("load", state, timeout))


class FakeVision:
    async def describe(self, screenshot_b64, context="", detail="auto"):
        return "A form with a submit button and email field."

    async def locate_element(self, screenshot_b64, description):
        return {"x": 11, "y": 22, "confidence": 0.9}


class FakeExtractProvider:
    async def complete(self, messages, tools=None, temperature=0.7, max_tokens=4096):
        return SimpleNamespace(content="Found total $10")


class FakePlannerProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, tools=None, temperature=0.7, max_tokens=4096):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(content='{"action":"click","target":"the submit button","value":"","reasoning":"open the form"}')
        if self.calls == 2:
            return SimpleNamespace(content='{"action":"type","target":"email field","value":"user@example.com","reasoning":"fill the email"}')
        return SimpleNamespace(content='{"action":"done","target":"","value":"Task completed successfully","reasoning":"goal reached"}')


@pytest.mark.asyncio
async def test_browser_navigate_blocks_disallowed_domains():
    cortex = BrowserCortex(
        config=BrowserConfig(enabled=True, allowed_domains=["example.com"]),
        page=FakePage(),
    )

    result = await cortex.navigate("https://evil.com")

    assert "error" in result
    assert "allowlisted" in result["error"]


@pytest.mark.asyncio
async def test_browser_click_uses_vision_for_natural_language_targets():
    page = FakePage()
    cortex = BrowserCortex(
        config=BrowserConfig(enabled=True),
        page=page,
        vision=FakeVision(),
    )

    result = await cortex.click("the submit button")

    assert result["success"] is True
    assert page.mouse.clicks == [(11, 22)]


@pytest.mark.asyncio
async def test_browser_extract_uses_provider_when_available():
    cortex = BrowserCortex(
        config=BrowserConfig(enabled=True),
        page=FakePage(),
        provider=FakeExtractProvider(),
    )

    result = await cortex.extract("find the total")

    assert result["success"] is True
    assert result["answer"] == "Found total $10"


@pytest.mark.asyncio
async def test_browser_act_runs_multi_step_plan():
    page = FakePage()
    cortex = BrowserCortex(
        config=BrowserConfig(enabled=True),
        page=page,
        provider=FakePlannerProvider(),
        vision=FakeVision(),
    )

    result = await cortex.act("submit the form", max_steps=5)

    assert result.success is True
    assert [action.action for action in result.actions_taken] == ["click", "type", "done"]
    assert page.mouse.clicks == [(11, 22), (11, 22)]
    assert page.keyboard.typed == ["user@example.com"]
    assert result.extracted_data["answer"] == "Task completed successfully"


@pytest.mark.asyncio
async def test_browser_act_reports_invalid_planner_output():
    class BadPlannerProvider:
        async def complete(self, messages, tools=None, temperature=0.7, max_tokens=4096):
            return SimpleNamespace(content="not json")

    cortex = BrowserCortex(
        config=BrowserConfig(enabled=True),
        page=FakePage(),
        provider=BadPlannerProvider(),
    )

    result = await cortex.act("do something", max_steps=2)

    assert result.success is False
    assert "invalid json" in result.error.lower()


@pytest.mark.asyncio
async def test_gateway_registers_browser_tools_when_enabled(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    config.features.browser = True
    config.browser.enabled = True

    async def fake_start(self):
        self._page = FakePage()

    monkeypatch.setattr("neuralclaw.cortex.action.browser.BrowserCortex.start", fake_start)

    gateway = NeuralClawGateway(config)
    await gateway.initialize()
    try:
        tool_names = [tool.name for tool in gateway._skills.get_all_tools()]
        assert "browser_navigate" in tool_names
        assert "browser_extract" in tool_names
    finally:
        await gateway.stop()
