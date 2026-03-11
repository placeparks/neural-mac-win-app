"""
Managed browser session runtime for app-backed providers.
"""

from __future__ import annotations

import asyncio
import importlib.util
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SessionHealth:
    provider: str
    ready: bool
    logged_in: bool
    state: str
    message: str
    recommendation: str = ""
    last_completion_at: float | None = None
    supports_tools: bool = False


@dataclass
class SessionRuntimeConfig:
    provider: str
    profile_dir: str
    site_url: str
    model: str = "auto"
    headless: bool = False
    browser_channel: str = ""


class ManagedBrowserSession:
    """
    Playwright-backed persistent browser runtime.

    The implementation is intentionally best-effort and keeps all browser
    specifics behind a single boundary so provider adapters stay small.
    """

    _SELECTORS: dict[str, dict[str, list[str]]] = {
        "chatgpt_app": {
            "input": [
                "textarea[data-id]",
                "textarea[placeholder*='Message']",
                "textarea",
                "div[contenteditable='true']",
            ],
            "response": [
                "[data-message-author-role='assistant']",
                "article[data-testid*='conversation-turn']",
                "article",
            ],
            "login": [
                "button[data-testid='login-button']",
                "input[type='email']",
                "form[action*='login']",
            ],
            "ready": [
                "textarea",
                "[data-testid='send-button']",
                "button[aria-label*='Send']",
            ],
        },
        "claude_app": {
            "input": [
                "textarea[placeholder*='Talk']",
                "textarea",
                "div[contenteditable='true']",
            ],
            "response": [
                "[data-testid='message-content']",
                "[data-is-streaming]",
                "div.font-claude-message",
            ],
            "login": [
                "input[type='email']",
                "button[type='submit']",
                "form[action*='login']",
            ],
            "ready": [
                "textarea",
                "button[aria-label*='Send']",
            ],
        },
    }

    def __init__(self, config: SessionRuntimeConfig) -> None:
        self._config = config
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None
        self._last_completion_at: float | None = None

    @property
    def is_supported(self) -> bool:
        return importlib.util.find_spec("playwright") is not None

    async def launch(self, *, force_page: bool = False) -> None:
        if self._browser and self._page and not self._page.is_closed():
            return
        if not self.is_supported:
            raise RuntimeError(
                "Playwright is not installed. Install with: pip install neuralclaw "
                "and then run: python -m playwright install chromium"
            )

        from playwright.async_api import async_playwright

        Path(self._config.profile_dir).mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        chromium = self._playwright.chromium
        kwargs = self._build_launch_kwargs()
        self._browser = await chromium.launch_persistent_context(
            user_data_dir=self._config.profile_dir,
            **kwargs,
        )
        await self._apply_stealth()
        self._page = self._browser.pages[0] if self._browser.pages else await self._browser.new_page()
        self._page.set_default_timeout(15000)
        if force_page or not self._page.url:
            await self._page.goto(self._config.site_url, wait_until="domcontentloaded")

    async def extract_cookies(self, domain: str) -> list[dict]:
        """Extract cookies for a specific domain from the persistent context."""
        await self.launch()
        cookies = await self._browser.cookies()
        return [c for c in cookies if domain in c.get("domain", "")]

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
        self._page = None

    async def login(self) -> None:
        await self.launch(force_page=True)

    async def repair(self) -> None:
        await self.close()
        await self.launch(force_page=True)

    async def current_state(self) -> tuple[str, bool, str, str]:
        """Inspect the current page state without forcing a navigation."""
        await self.launch()
        return await self._inspect_session_state()

    async def health(self) -> SessionHealth:
        if not self.is_supported:
            return SessionHealth(
                self._config.provider,
                False,
                False,
                "missing_runtime",
                "Playwright not installed",
                "Install neuralclaw, then run: python -m playwright install chromium",
            )
        try:
            await self.launch()
            await self._page.goto(self._config.site_url, wait_until="domcontentloaded")
            state, logged_in, message, recommendation = await self._inspect_session_state()
            if logged_in:
                await self._wait_until_ready()
            return SessionHealth(
                provider=self._config.provider,
                ready=logged_in,
                logged_in=logged_in,
                state=state,
                message=message,
                recommendation=recommendation,
                last_completion_at=self._last_completion_at,
            )
        except Exception as exc:
            return SessionHealth(
                self._config.provider,
                False,
                False,
                "session_error",
                f"session error: {exc}",
                self._fallback_recommendation(),
            )

    async def complete(self, prompt: str) -> str:
        await self.launch(force_page=True)
        state, logged_in, message, recommendation = await self._inspect_session_state()
        if not logged_in:
            suffix = f" {recommendation}" if recommendation else ""
            raise RuntimeError(f"{message}.{suffix}".strip())
        await self._wait_until_ready()
        selectors = self._SELECTORS.get(self._config.provider, {})
        input_locator = None
        for selector in selectors.get("input", []):
            locator = self._page.locator(selector).first
            if await locator.count():
                input_locator = locator
                break
        if input_locator is None:
            raise RuntimeError("Could not find message input in app session")

        await input_locator.click()
        try:
            await input_locator.fill(prompt)
        except Exception:
            await input_locator.type(prompt)
        await input_locator.press("Enter")

        response_locators = selectors.get("response", [])
        if not response_locators:
            raise RuntimeError("No response selectors configured for app session")

        latest_text = ""
        stable_rounds = 0
        deadline = time.time() + 120
        while time.time() < deadline:
            current = ""
            for selector in response_locators:
                locator = self._page.locator(selector)
                count = await locator.count()
                if count:
                    current = self._normalize_text((await locator.nth(count - 1).inner_text()).strip())
                    if current:
                        break
            if current and current == latest_text:
                stable_rounds += 1
            elif current:
                latest_text = current
                stable_rounds = 0
            if latest_text and stable_rounds >= 3:
                self._last_completion_at = time.time()
                return latest_text
            await asyncio.sleep(1)
        raise RuntimeError("Timed out waiting for app session response")

    async def _is_logged_in(self) -> bool:
        selectors = self._SELECTORS.get(self._config.provider, {})
        for selector in selectors.get("login", []):
            try:
                if await self._page.locator(selector).count():
                    return False
            except Exception:
                continue
        return True

    async def _wait_until_ready(self) -> None:
        selectors = self._SELECTORS.get(self._config.provider, {})
        for _ in range(20):
            for selector in selectors.get("ready", []) or selectors.get("input", []):
                try:
                    if await self._page.locator(selector).count():
                        return
                except Exception:
                    continue
            await asyncio.sleep(0.5)
        raise RuntimeError("App session loaded but did not become ready for input")

    def _normalize_text(self, text: str) -> str:
        return "\n".join(line.rstrip() for line in text.splitlines()).strip()

    async def _inspect_session_state(self) -> tuple[str, bool, str, str]:
        url = (self._page.url or "").lower()
        title = (await self._safe_title()).lower()
        body = (await self._safe_body_text()).lower()
        combined = f"{title}\n{body}"

        if "/api/auth/error" in url:
            return (
                "auth_rejected",
                False,
                "Upstream auth rejected the browser-controlled login flow",
                self._fallback_recommendation(),
            )

        if (
            "cloudflare" in combined
            or "just a moment" in combined
            or "verifying..." in combined
        ):
            return (
                "challenge",
                False,
                "Cloudflare verification is blocking the session",
                "Use headed Chrome, complete the challenge manually, then rerun "
                "`neuralclaw session diagnose chatgpt`.",
            )

        if not await self._is_logged_in():
            return (
                "login_required",
                False,
                "Login required",
                "Run `neuralclaw session open "
                f"{'chatgpt' if self._config.provider == 'chatgpt_app' else 'claude'}` "
                "to complete login in the managed profile.",
            )

        return ("ready", True, "session ready", "")

    async def _safe_title(self) -> str:
        try:
            return await self._page.title()
        except Exception:
            return ""

    async def _safe_body_text(self) -> str:
        try:
            return await self._page.locator("body").inner_text()
        except Exception:
            return ""

    def _build_launch_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "headless": self._config.headless,
            "ignore_default_args": ["--enable-automation"],
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--start-maximized",
            ],
            "no_viewport": True,
            "locale": "en-US",
        }
        if self._config.browser_channel:
            kwargs["channel"] = self._config.browser_channel
        return kwargs

    async def _apply_stealth(self) -> None:
        await self._browser.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined,
            });
            Object.defineProperty(navigator, 'languages', {
              get: () => ['en-US', 'en'],
            });
            Object.defineProperty(navigator, 'platform', {
              get: () => 'Win32',
            });
            Object.defineProperty(navigator, 'plugins', {
              get: () => [1, 2, 3, 4, 5],
            });
            window.chrome = window.chrome || { runtime: {} };
            Object.defineProperty(navigator, 'hardwareConcurrency', {
              get: () => 8,
            });
            Object.defineProperty(navigator, 'deviceMemory', {
              get: () => 8,
            });
            const originalQuery = window.navigator.permissions?.query;
            if (originalQuery) {
              window.navigator.permissions.query = (parameters) => (
                parameters && parameters.name === 'notifications'
                  ? Promise.resolve({ state: Notification.permission })
                  : originalQuery(parameters)
              );
            }
            """
        )

    def _fallback_recommendation(self) -> str:
        if self._config.provider == "chatgpt_app":
            return (
                "ChatGPT browser-session login is experimental; use `neuralclaw chat -p proxy` "
                "or `neuralclaw chat -p openai` for reliability."
            )
        return (
            "Try `neuralclaw session repair claude`, or fall back to `neuralclaw chat -p anthropic`."
        )
