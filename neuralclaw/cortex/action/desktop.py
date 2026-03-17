"""Local desktop control cortex."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import subprocess
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.config import DesktopConfig, PolicyConfig


class DesktopCortex:
    """High-risk desktop control primitives behind explicit config gates."""

    def __init__(
        self,
        config: DesktopConfig | None = None,
        policy: PolicyConfig | None = None,
        bus: NeuralBus | None = None,
        capture_backend: Any | None = None,
        input_backend: Any | None = None,
        clipboard_backend: Any | None = None,
    ) -> None:
        self._config = config or DesktopConfig()
        self._policy = policy or PolicyConfig()
        self._bus = bus
        self._capture_backend = capture_backend
        self._input_backend = input_backend
        self._clipboard_backend = clipboard_backend

    async def screenshot(self, monitor: int = 0) -> dict[str, Any]:
        """Capture a monitor screenshot and return PNG bytes as base64."""
        if not self._config.enabled:
            return {"error": "Desktop control is disabled in config."}

        try:
            image_bytes, width, height = await asyncio.to_thread(
                self._capture_screen_sync,
                monitor,
            )
        except Exception as exc:
            await self._publish_error(f"Desktop screenshot failed: {exc}")
            return {"error": str(exc)}

        return {
            "screenshot_b64": base64.b64encode(image_bytes).decode("ascii"),
            "width": width,
            "height": height,
            "monitor": monitor,
        }

    async def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
    ) -> dict[str, Any]:
        """Click on the local desktop if the point is not in a blocked region."""
        if not self._config.enabled:
            return {"error": "Desktop control is disabled in config."}
        if self._is_blocked_point(x, y):
            return {"error": f"Desktop interaction blocked at ({x}, {y})."}

        backend = self._resolve_input_backend()
        if isinstance(backend, dict) and backend.get("error"):
            return backend

        evidence_before = await self._capture_action_evidence("before") if self._config.screenshot_on_action else {}
        await asyncio.sleep(max(self._config.action_delay_ms, 0) / 1000.0)
        try:
            await asyncio.to_thread(backend.click, x=x, y=y, button=button, clicks=clicks)
        except Exception as exc:
            await self._publish_error(f"Desktop click failed: {exc}")
            return {"error": str(exc)}
        evidence_after = await self._capture_action_evidence("after") if self._config.screenshot_on_action else {}

        return {
            "success": True,
            "x": x,
            "y": y,
            "button": button,
            "clicks": clicks,
            **evidence_before,
            **evidence_after,
        }

    async def type_text(self, text: str, interval: float = 0.05) -> dict[str, Any]:
        """Type text via the keyboard backend."""
        if not self._config.enabled:
            return {"error": "Desktop control is disabled in config."}

        backend = self._resolve_input_backend()
        if isinstance(backend, dict) and backend.get("error"):
            return backend

        evidence_before = await self._capture_action_evidence("before") if self._config.screenshot_on_action else {}
        await asyncio.sleep(max(self._config.action_delay_ms, 0) / 1000.0)
        try:
            await asyncio.to_thread(backend.write, text, interval=interval)
        except Exception as exc:
            await self._publish_error(f"Desktop typing failed: {exc}")
            return {"error": str(exc)}
        evidence_after = await self._capture_action_evidence("after") if self._config.screenshot_on_action else {}

        return {
            "success": True,
            "chars": len(text),
            "interval": interval,
            **evidence_before,
            **evidence_after,
        }

    async def hotkey(self, *keys: str) -> dict[str, Any]:
        """Press a hotkey chord."""
        if not self._config.enabled:
            return {"error": "Desktop control is disabled in config."}
        if not keys:
            return {"error": "At least one hotkey is required."}

        backend = self._resolve_input_backend()
        if isinstance(backend, dict) and backend.get("error"):
            return backend

        evidence_before = await self._capture_action_evidence("before") if self._config.screenshot_on_action else {}
        await asyncio.sleep(max(self._config.action_delay_ms, 0) / 1000.0)
        try:
            await asyncio.to_thread(backend.hotkey, *keys)
        except Exception as exc:
            await self._publish_error(f"Desktop hotkey failed: {exc}")
            return {"error": str(exc)}
        evidence_after = await self._capture_action_evidence("after") if self._config.screenshot_on_action else {}

        return {
            "success": True,
            "keys": list(keys),
            **evidence_before,
            **evidence_after,
        }

    async def get_clipboard(self) -> dict[str, Any]:
        """Read clipboard text."""
        if not self._config.enabled:
            return {"error": "Desktop control is disabled in config."}
        try:
            text = await asyncio.to_thread(self._get_clipboard_sync)
        except Exception as exc:
            await self._publish_error(f"Clipboard read failed: {exc}")
            return {"error": str(exc)}
        return {"text": text}

    async def set_clipboard(self, text: str) -> dict[str, Any]:
        """Write clipboard text."""
        if not self._config.enabled:
            return {"error": "Desktop control is disabled in config."}
        try:
            await asyncio.to_thread(self._set_clipboard_sync, text)
        except Exception as exc:
            await self._publish_error(f"Clipboard write failed: {exc}")
            return {"error": str(exc)}
        return {"success": True, "chars": len(text)}

    async def run_app(self, app: str, args: list[str] | None = None) -> dict[str, Any]:
        """Launch an allowlisted local application."""
        if not self._config.enabled:
            return {"error": "Desktop control is disabled in config."}

        # Check allowlist — match case-insensitively and with/without .exe
        app_lower = app.lower().strip()
        allowed_lower = {a.lower() for a in self._policy.desktop_allowed_apps}
        if app_lower not in allowed_lower and app_lower.replace(".exe", "") not in allowed_lower:
            return {"error": f"Desktop app '{app}' is not allowlisted."}

        import sys
        argv = [app, *(args or [])]
        try:
            process = await asyncio.to_thread(
                subprocess.Popen,
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=(sys.platform == "win32"),  # shell=True on Windows for PATH resolution
            )
        except Exception as exc:
            await self._publish_error(f"Desktop run_app failed: {exc}")
            return {"error": str(exc)}

        return {
            "success": True,
            "app": app,
            "args": args or [],
            "pid": process.pid,
        }

    def _capture_screen_sync(self, monitor: int) -> tuple[bytes, int, int]:
        if self._capture_backend is not None:
            frame = self._capture_backend.capture(monitor) if hasattr(self._capture_backend, "capture") else self._capture_backend(monitor)
            return self._normalize_frame(frame)

        try:
            from mss import mss
            from PIL import Image
        except Exception as exc:
            raise RuntimeError(
                "Desktop screenshot dependencies are unavailable. Install neuralclaw[desktop]."
            ) from exc

        with mss() as sct:
            monitors = sct.monitors
            selected_index = monitor + 1 if monitor + 1 < len(monitors) else min(max(monitor, 0), len(monitors) - 1)
            shot = sct.grab(monitors[selected_index])
            image = Image.frombytes("RGB", shot.size, shot.rgb)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue(), shot.size[0], shot.size[1]

    def _normalize_frame(self, frame: Any) -> tuple[bytes, int, int]:
        if isinstance(frame, tuple) and len(frame) == 3:
            data, width, height = frame
            return bytes(data), int(width), int(height)
        if isinstance(frame, dict):
            data = frame.get("image_bytes") or frame.get("png_bytes") or b""
            width = int(frame.get("width", 0))
            height = int(frame.get("height", 0))
            return bytes(data), width, height
        raise RuntimeError("Unsupported desktop capture backend frame format.")

    def _resolve_input_backend(self) -> Any:
        if self._input_backend is not None:
            return self._input_backend
        try:
            import pyautogui
        except Exception as exc:
            return {
                "error": (
                    "Desktop input dependencies are unavailable. "
                    "Install neuralclaw[desktop]."
                ),
                "details": str(exc),
            }
        pyautogui.FAILSAFE = True
        return pyautogui

    async def _capture_action_evidence(self, prefix: str) -> dict[str, Any]:
        try:
            image_bytes, width, height = await asyncio.to_thread(self._capture_screen_sync, 0)
        except Exception as exc:
            await self._publish_error(f"Desktop evidence capture failed: {exc}")
            return {}
        digest = hashlib.sha256(image_bytes).hexdigest()
        preview = base64.b64encode(image_bytes[:96]).decode("ascii")
        return {
            f"{prefix}_evidence_width": width,
            f"{prefix}_evidence_height": height,
            f"{prefix}_evidence_sha256": digest,
            f"{prefix}_evidence_b64_preview": preview,
        }

    def _is_blocked_point(self, x: int, y: int) -> bool:
        for region in self._policy.desktop_blocked_regions:
            try:
                x1, y1, x2, y2 = [int(part.strip()) for part in region.split(",")]
            except ValueError:
                continue
            if x1 <= x <= x2 and y1 <= y <= y2:
                return True
        return False

    def _get_clipboard_sync(self) -> str:
        if self._clipboard_backend is not None:
            if hasattr(self._clipboard_backend, "get"):
                return str(self._clipboard_backend.get())
            return str(self._clipboard_backend())

        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        try:
            return root.clipboard_get()
        finally:
            root.destroy()

    def _set_clipboard_sync(self, text: str) -> None:
        if self._clipboard_backend is not None:
            if hasattr(self._clipboard_backend, "set"):
                self._clipboard_backend.set(text)
                return
            self._clipboard_backend(text)
            return

        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        try:
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
        finally:
            root.destroy()

    async def _publish_error(self, message: str) -> None:
        if not self._bus:
            return
        await self._bus.publish(
            EventType.ERROR,
            {"error": message, "component": "desktop"},
            source="action.desktop",
        )
