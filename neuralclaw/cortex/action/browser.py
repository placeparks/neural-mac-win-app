"""
Browser cortex - stateful Playwright browser automation.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.config import BrowserConfig
from neuralclaw.cortex.perception.vision import VisionPerception


@dataclass
class BrowserState:
    url: str
    title: str
    screenshot_b64: str
    text_content: str
    interactive_elements: list[dict[str, Any]]


@dataclass
class BrowserAction:
    action: str
    target: str
    value: str = ""
    reasoning: str = ""


@dataclass
class BrowserResult:
    success: bool
    state: BrowserState | None
    extracted_data: dict[str, Any]
    error: str = ""
    actions_taken: list[BrowserAction] = field(default_factory=list)


class BrowserCortex:
    """Reusable browser session with tool-friendly methods."""

    def __init__(
        self,
        config: BrowserConfig,
        bus: NeuralBus | None = None,
        vision: VisionPerception | None = None,
        provider: Any = None,
        browser_factory: Any = None,
        page: Any = None,
    ) -> None:
        self._config = config
        self._bus = bus
        self._vision = vision
        self._provider = provider
        self._browser_factory = browser_factory
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = page

    async def start(self) -> None:
        if not self._config.enabled or self._page is not None:
            return
        if self._browser_factory:
            built = await self._browser_factory()
            if isinstance(built, dict):
                self._playwright = built.get("playwright")
                self._browser = built.get("browser")
                self._context = built.get("context")
                self._page = built.get("page")
                return
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise RuntimeError("Playwright is not available") from exc

        self._playwright = await async_playwright().start()
        browser_launcher = getattr(self._playwright, self._config.browser_type, self._playwright.chromium)
        self._browser = await browser_launcher.launch(headless=self._config.headless)
        self._context = await self._browser.new_context(
            viewport={
                "width": self._config.viewport_width,
                "height": self._config.viewport_height,
            }
        )
        self._page = await self._context.new_page()

    async def stop(self) -> None:
        if self._context and hasattr(self._context, "close"):
            await self._context.close()
        if self._browser and hasattr(self._browser, "close"):
            await self._browser.close()
        if self._playwright and hasattr(self._playwright, "stop"):
            await self._playwright.stop()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def navigate(self, url: str) -> dict[str, Any]:
        if not await self._ensure_ready():
            return {"error": "Browser is disabled or not available"}
        blocked = self._check_domain(url)
        if blocked:
            return {"error": blocked}
        await self._page.goto(
            url,
            timeout=self._config.navigation_timeout * 1000,
            wait_until="domcontentloaded",
        )
        state = await self._capture_state()
        await self._publish("navigate", {"url": url, "title": state.title})
        return {"success": True, "url": state.url, "title": state.title}

    async def screenshot(self) -> dict[str, Any]:
        if not await self._ensure_ready():
            return {"error": "Browser is disabled or not available"}
        state = await self._capture_state()
        return {
            "url": state.url,
            "title": state.title,
            "screenshot_b64": state.screenshot_b64,
            "text_content": state.text_content,
        }

    async def click(self, selector: str) -> dict[str, Any]:
        if not await self._ensure_ready():
            return {"error": "Browser is disabled or not available"}
        action = BrowserAction(action="click", target=selector)
        if self._looks_like_selector(selector):
            await self._page.click(selector)
        else:
            coords = await self._locate_with_vision(selector)
            if not coords:
                return {"error": f"Could not locate element: {selector}"}
            await self._page.mouse.click(coords["x"], coords["y"])
            action.value = f"{coords['x']},{coords['y']}"
        state = await self._capture_state()
        await self._publish("click", {"target": selector, "url": state.url})
        return {"success": True, "state": self._state_to_dict(state), "action": action.__dict__}

    async def type_text(self, selector: str, text: str) -> dict[str, Any]:
        if not await self._ensure_ready():
            return {"error": "Browser is disabled or not available"}
        if self._looks_like_selector(selector):
            await self._page.fill(selector, text)
        else:
            coords = await self._locate_with_vision(selector)
            if not coords:
                return {"error": f"Could not locate element: {selector}"}
            await self._page.mouse.click(coords["x"], coords["y"])
            await self._page.keyboard.type(text)
        state = await self._capture_state()
        await self._publish("type", {"target": selector, "chars": len(text)})
        return {"success": True, "state": self._state_to_dict(state)}

    async def scroll(self, direction: str = "down", amount: int = 3) -> dict[str, Any]:
        if not await self._ensure_ready():
            return {"error": "Browser is disabled or not available"}
        delta = max(1, amount) * 600
        if direction.lower() == "up":
            delta *= -1
        await self._page.mouse.wheel(0, delta)
        state = await self._capture_state()
        return {"success": True, "state": self._state_to_dict(state)}

    async def extract(self, query: str) -> dict[str, Any]:
        if not await self._ensure_ready():
            return {"error": "Browser is disabled or not available"}
        state = await self._capture_state()
        if not self._provider:
            return {"success": True, "answer": state.text_content[:4000], "url": state.url}

        prompt = (
            f"Answer the extraction request using only the page content.\n"
            f"Request: {query}\n\n"
            f"Page title: {state.title}\n"
            f"Page url: {state.url}\n"
            f"Page text:\n{state.text_content[:8000]}"
        )
        response = await self._provider.complete(
            messages=[
                {"role": "system", "content": "You are a browser extraction assistant. Use only the provided page content."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        return {"success": True, "answer": (response.content or "").strip(), "url": state.url}

    async def execute_js(self, code: str) -> dict[str, Any]:
        if not await self._ensure_ready():
            return {"error": "Browser is disabled or not available"}
        if not self._config.allow_js_execution:
            return {"error": "JavaScript execution is disabled"}
        result = await self._page.evaluate(code)
        return {"success": True, "result": result}

    async def wait_for(self, condition: str, timeout: int = 10) -> dict[str, Any]:
        if not await self._ensure_ready():
            return {"error": "Browser is disabled or not available"}
        if condition.lower() in {"load", "page to stop loading", "network idle", "networkidle"}:
            await self._page.wait_for_load_state("networkidle", timeout=timeout * 1000)
        else:
            await self._page.wait_for_selector(condition, timeout=timeout * 1000)
        state = await self._capture_state()
        return {"success": True, "state": self._state_to_dict(state)}

    async def chrome_summarize(self, selector: str = "body") -> dict[str, Any]:
        if not self._config.chrome_ai_enabled:
            return {"error": "Chrome AI integration is disabled"}
        return await self.execute_js(
            f"window.ai?.summarizer ? await window.ai.summarizer('{selector}') : null"
        )

    async def chrome_translate(self, text: str, target_lang: str = "en") -> dict[str, Any]:
        if not self._config.chrome_ai_enabled:
            return {"error": "Chrome AI integration is disabled"}
        return await self.execute_js(
            f"window.translation ? await window.translation.translate({text!r}, {{targetLanguage: {target_lang!r}}}) : null"
        )

    async def chrome_prompt(self, prompt: str, context_selector: str = "") -> dict[str, Any]:
        if not self._config.chrome_ai_enabled:
            return {"error": "Chrome AI integration is disabled"}
        if context_selector:
            return await self.execute_js(
                "const node = document.querySelector(arguments[0]);"
                "const context = node ? node.innerText : '';"
                "return {prompt: arguments[1], context};"
            )
        return {"success": True, "prompt": prompt}

    async def act(self, task: str, url: str | None = None, max_steps: int = 20) -> BrowserResult:
        actions: list[BrowserAction] = []
        try:
            if url:
                nav = await self.navigate(url)
                if nav.get("error"):
                    return BrowserResult(False, None, {}, error=nav["error"], actions_taken=actions)
                actions.append(BrowserAction(action="navigate", target=url, reasoning="initial_navigation"))

            steps = min(max_steps, self._config.max_steps_per_task)
            if steps <= 0:
                return BrowserResult(False, None, {}, error="max_steps must be > 0", actions_taken=actions)

            if not self._provider:
                state = await self._capture_state()
                extracted = await self.extract(task)
                actions.append(BrowserAction(action="extract", target=task, reasoning=f"bounded_plan_steps={steps}"))
                return BrowserResult(
                    success="error" not in extracted,
                    state=state,
                    extracted_data=extracted,
                    error=extracted.get("error", ""),
                    actions_taken=actions,
                )

            extracted_data: dict[str, Any] = {}
            last_result: dict[str, Any] | None = None
            last_error = ""

            for step in range(1, steps + 1):
                state = await self._capture_state()
                plan = await self._plan_next_action(
                    task=task,
                    state=state,
                    actions_taken=actions,
                    last_result=last_result,
                    step=step,
                    max_steps=steps,
                )
                if plan.get("error"):
                    return BrowserResult(False, state, extracted_data, error=plan["error"], actions_taken=actions)

                action = self._coerce_action(plan)
                if action.action == "done":
                    if action.value:
                        extracted_data["answer"] = action.value
                    if action.reasoning:
                        extracted_data["planner_reasoning"] = action.reasoning
                    return BrowserResult(True, state, extracted_data, actions_taken=actions + [action])

                result = await self._execute_planned_action(action, task)
                actions.append(action)
                last_result = result
                if result.get("error"):
                    last_error = result["error"]
                    break
                if action.action == "extract":
                    extracted_data.update(result)

            state = await self._capture_state()
            if extracted_data:
                return BrowserResult(
                    success=not last_error,
                    state=state,
                    extracted_data=extracted_data,
                    error=last_error,
                    actions_taken=actions,
                )

            extracted = await self.extract(task)
            actions.append(BrowserAction(action="extract", target=task, reasoning=f"bounded_plan_steps={steps}"))
            return BrowserResult(
                success="error" not in extracted and not last_error,
                state=state,
                extracted_data=extracted,
                error=last_error or extracted.get("error", ""),
                actions_taken=actions,
            )
        except Exception as exc:
            state = None
            if self._config.screenshot_on_error and await self._ensure_ready():
                state = await self._capture_state()
            return BrowserResult(False, state, {}, error=str(exc), actions_taken=actions)

    async def _plan_next_action(
        self,
        *,
        task: str,
        state: BrowserState,
        actions_taken: list[BrowserAction],
        last_result: dict[str, Any] | None,
        step: int,
        max_steps: int,
    ) -> dict[str, Any]:
        visual_summary = ""
        if self._vision:
            visual_summary = await self._vision.describe(
                state.screenshot_b64,
                context=task,
            )

        prompt = self._build_planner_prompt(
            task=task,
            state=state,
            actions_taken=actions_taken,
            last_result=last_result,
            visual_summary=visual_summary,
            step=step,
            max_steps=max_steps,
        )
        response = await self._provider.complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a browser task planner. Return JSON only with keys: "
                        "action, target, value, reasoning. Allowed actions: navigate, click, "
                        "type, scroll, wait, extract, done."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        try:
            return self._extract_json_object(response.content or "")
        except Exception as exc:
            return {"error": f"Browser planner returned invalid JSON: {exc}"}

    def _build_planner_prompt(
        self,
        *,
        task: str,
        state: BrowserState,
        actions_taken: list[BrowserAction],
        last_result: dict[str, Any] | None,
        visual_summary: str,
        step: int,
        max_steps: int,
    ) -> str:
        actions_preview = [
            {
                "action": action.action,
                "target": action.target,
                "value": action.value,
                "reasoning": action.reasoning,
            }
            for action in actions_taken[-8:]
        ]
        interactive_preview = state.interactive_elements[:20]
        last_result_preview = last_result or {}
        return (
            f"Task: {task}\n"
            f"Step: {step}/{max_steps}\n"
            f"Current URL: {state.url}\n"
            f"Title: {state.title}\n"
            f"Visual summary: {visual_summary[:500]}\n"
            f"Visible interactive elements: {json.dumps(interactive_preview, ensure_ascii=False)}\n"
            f"Recent actions: {json.dumps(actions_preview, ensure_ascii=False)}\n"
            f"Last action result: {json.dumps(last_result_preview, ensure_ascii=False)}\n"
            f"Page text preview: {state.text_content[:3000]}\n\n"
            "Return the next best action as JSON.\n"
            "For `type`, put the field selector/description in `target` and text in `value`.\n"
            "For `scroll`, put `up` or `down` in `target` and an optional integer amount in `value`.\n"
            "For `wait`, put the selector or condition in `target` and optional timeout seconds in `value`.\n"
            "For `extract`, put the extraction request in `target`.\n"
            "When the task is complete, return action=`done` and put the final answer in `value`."
        )

    async def _execute_planned_action(self, action: BrowserAction, task: str) -> dict[str, Any]:
        if action.action == "navigate":
            return await self.navigate(action.target)
        if action.action == "click":
            return await self.click(action.target)
        if action.action == "type":
            return await self.type_text(action.target, action.value)
        if action.action == "scroll":
            amount = self._coerce_int(action.value, default=3)
            return await self.scroll(action.target or "down", amount=amount)
        if action.action == "wait":
            timeout = self._coerce_int(action.value, default=10)
            return await self.wait_for(action.target, timeout=timeout)
        if action.action == "extract":
            return await self.extract(action.target or task)
        if action.action == "done":
            return {"success": True, "answer": action.value}
        return {"error": f"Unsupported browser planner action: {action.action}"}

    def _coerce_action(self, data: dict[str, Any]) -> BrowserAction:
        action = str(data.get("action", "") or "").strip().lower()
        target = str(data.get("target", "") or "").strip()
        value_raw = data.get("value", "")
        value = str(value_raw if value_raw is not None else "")
        reasoning = str(data.get("reasoning", "") or "").strip()
        return BrowserAction(action=action, target=target, value=value, reasoning=reasoning)

    def _coerce_int(self, value: str, default: int) -> int:
        try:
            return int(str(value).strip())
        except Exception:
            return default

    async def _ensure_ready(self) -> bool:
        if not self._config.enabled:
            return False
        if self._page is None:
            await self.start()
        return self._page is not None

    def _check_domain(self, url: str) -> str:
        hostname = (urlparse(url).hostname or "").lower()
        if not hostname:
            return "Invalid URL"
        if hostname in {domain.lower() for domain in self._config.blocked_domains}:
            return f"Navigation blocked for domain: {hostname}"
        if self._config.allowed_domains and hostname not in {domain.lower() for domain in self._config.allowed_domains}:
            return f"Domain not allowlisted: {hostname}"
        return ""

    async def _capture_state(self) -> BrowserState:
        screenshot_bytes = await self._page.screenshot(type="png")
        text_content = await self._page.evaluate(
            "() => (document.body?.innerText || '').slice(0, 8000)"
        )
        interactive_elements = await self._page.evaluate(
            """() => Array.from(document.querySelectorAll('a,button,input,textarea,select'))
            .slice(0, 100)
            .map((el) => ({
                tag: el.tagName.toLowerCase(),
                text: (el.innerText || el.value || el.getAttribute('aria-label') || '').slice(0, 120),
                type: el.getAttribute('type') || '',
            }))"""
        )
        return BrowserState(
            url=getattr(self._page, "url", ""),
            title=await self._page.title(),
            screenshot_b64=base64.b64encode(screenshot_bytes).decode("ascii"),
            text_content=text_content or "",
            interactive_elements=interactive_elements or [],
        )

    async def _locate_with_vision(self, description: str) -> dict[str, Any] | None:
        if not self._vision:
            return None
        state = await self._capture_state()
        return await self._vision.locate_element(state.screenshot_b64, description)

    async def _publish(self, action: str, payload: dict[str, Any]) -> None:
        if not self._bus:
            return
        await self._bus.publish(
            EventType.ACTION_EXECUTING,
            {"component": "browser", "action": action, **payload},
            source="action.browser",
        )

    def _looks_like_selector(self, selector: str) -> bool:
        return any(token in selector for token in ("#", ".", "[", "//", ">", "="))

    def _state_to_dict(self, state: BrowserState) -> dict[str, Any]:
        return {
            "url": state.url,
            "title": state.title,
            "screenshot_b64": state.screenshot_b64,
            "text_content": state.text_content,
            "interactive_elements": state.interactive_elements,
        }

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if not stripped:
            raise ValueError("empty planner output")
        decoder = json.JSONDecoder()
        for idx, char in enumerate(stripped):
            if char != "{":
                continue
            try:
                obj, _end = decoder.raw_decode(stripped[idx:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
        raise ValueError("no JSON object found")
