"""
Built-in Skill: Context-Aware Suggestions — Desktop environment awareness.

Detects the user's currently active window/application and suggests
relevant NeuralClaw actions. Cross-platform support for Windows (ctypes),
macOS (osascript), and Linux (xdotool/wmctrl).

Optionally enhanced by an LLM provider set via ``set_llm_provider()``.
"""

from __future__ import annotations

import asyncio
import platform
import re
import subprocess
import sys
from typing import Any, Callable, Coroutine

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

# ---------------------------------------------------------------------------
# Optional LLM provider for enhanced suggestions
# ---------------------------------------------------------------------------

_llm_provider: Any | None = None


def set_llm_provider(provider: Any) -> None:
    """Set an LLM provider for enhanced context suggestions.

    The provider should be a callable (or object with an ``acomplete``
    method) that the gateway injects at startup.
    """
    global _llm_provider
    _llm_provider = provider


# ---------------------------------------------------------------------------
# App-to-action mapping
# ---------------------------------------------------------------------------

_APP_ACTION_MAP: dict[str, list[str]] = {
    # Browsers
    "chrome": ["summarize_page", "extract_links", "fetch_url"],
    "firefox": ["summarize_page", "extract_links", "fetch_url"],
    "edge": ["summarize_page", "extract_links", "fetch_url"],
    "brave": ["summarize_page", "extract_links", "fetch_url"],
    "safari": ["summarize_page", "extract_links", "fetch_url"],
    "opera": ["summarize_page", "extract_links", "fetch_url"],
    "vivaldi": ["summarize_page", "extract_links", "fetch_url"],
    # IDEs / code editors
    "code": ["explain_code", "review_code", "find_bugs"],
    "vscode": ["explain_code", "review_code", "find_bugs"],
    "sublime": ["explain_code", "review_code", "find_bugs"],
    "sublime_text": ["explain_code", "review_code", "find_bugs"],
    "notepad++": ["explain_code", "review_code", "find_bugs"],
    "intellij": ["explain_code", "review_code", "find_bugs"],
    "pycharm": ["explain_code", "review_code", "find_bugs"],
    "webstorm": ["explain_code", "review_code", "find_bugs"],
    "vim": ["explain_code", "review_code", "find_bugs"],
    "nvim": ["explain_code", "review_code", "find_bugs"],
    "neovim": ["explain_code", "review_code", "find_bugs"],
    "emacs": ["explain_code", "review_code", "find_bugs"],
    "atom": ["explain_code", "review_code", "find_bugs"],
    # Spreadsheets
    "excel": ["analyze_data", "chart_data", "db_connect"],
    "sheets": ["analyze_data", "chart_data", "db_connect"],
    "calc": ["analyze_data", "chart_data", "db_connect"],
    "numbers": ["analyze_data", "chart_data", "db_connect"],
    "libreoffice calc": ["analyze_data", "chart_data", "db_connect"],
    # Email clients
    "outlook": ["draft_reply", "summarize_thread", "digest_create"],
    "thunderbird": ["draft_reply", "summarize_thread", "digest_create"],
    "gmail": ["draft_reply", "summarize_thread", "digest_create"],
    "mail": ["draft_reply", "summarize_thread", "digest_create"],
    "mailspring": ["draft_reply", "summarize_thread", "digest_create"],
    # Terminals
    "terminal": ["execute_python", "web_search"],
    "cmd": ["execute_python", "web_search"],
    "powershell": ["execute_python", "web_search"],
    "iterm": ["execute_python", "web_search"],
    "iterm2": ["execute_python", "web_search"],
    "windows terminal": ["execute_python", "web_search"],
    "wt": ["execute_python", "web_search"],
    "alacritty": ["execute_python", "web_search"],
    "kitty": ["execute_python", "web_search"],
    "konsole": ["execute_python", "web_search"],
    "gnome-terminal": ["execute_python", "web_search"],
    # Text editors / word processors
    "word": ["format_text", "summarize_page", "draft_reply"],
    "writer": ["format_text", "summarize_page", "draft_reply"],
    "pages": ["format_text", "summarize_page", "draft_reply"],
    "notepad": ["format_text", "explain_code", "web_search"],
    "textedit": ["format_text", "explain_code", "web_search"],
    # Messaging / communication
    "slack": ["draft_reply", "summarize_thread", "web_search"],
    "discord": ["draft_reply", "summarize_thread", "web_search"],
    "teams": ["draft_reply", "summarize_thread", "web_search"],
    "telegram": ["draft_reply", "summarize_thread", "web_search"],
    "whatsapp": ["draft_reply", "summarize_thread", "web_search"],
}

_DEFAULT_ACTIONS: list[str] = ["clipboard_analyze", "web_search"]

# ---------------------------------------------------------------------------
# Quick action definitions
# ---------------------------------------------------------------------------

_QUICK_ACTION_PROMPTS: dict[str, str] = {
    "summarize_page": (
        "Summarize the content currently visible in the browser. "
        "Provide a concise overview of the key points."
    ),
    "explain_code": (
        "Explain the code currently visible in the editor. "
        "Describe what it does, its structure, and any notable patterns."
    ),
    "analyze_data": (
        "Analyze the data currently visible in the spreadsheet. "
        "Identify trends, outliers, and provide a statistical summary."
    ),
    "draft_reply": (
        "Draft a professional reply to the email or message currently "
        "visible. Match the tone and formality of the original."
    ),
    "format_text": (
        "Improve the formatting and clarity of the text currently visible "
        "in the editor. Fix grammar, punctuation, and structure."
    ),
}

_QUICK_ACTION_LABELS: dict[str, str] = {
    "summarize_page": "Summarize Page (Browser)",
    "explain_code": "Explain Code (IDE)",
    "analyze_data": "Analyze Data (Spreadsheet)",
    "draft_reply": "Draft Reply (Email/Message)",
    "format_text": "Format Text (Editor)",
}


# ---------------------------------------------------------------------------
# Platform-specific window detection
# ---------------------------------------------------------------------------

def _detect_active_window_windows() -> dict[str, str]:
    """Detect the active window on Windows using ctypes."""
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.GetForegroundWindow()

    # Get window title
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    window_title = buf.value

    # Get process name from PID
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    app_name = ""
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value,
        )
        if handle:
            try:
                buf_size = ctypes.wintypes.DWORD(512)
                exe_buf = ctypes.create_unicode_buffer(512)
                kernel32.QueryFullProcessImageNameW(
                    handle, 0, exe_buf, ctypes.byref(buf_size),
                )
                exe_path = exe_buf.value
                if exe_path:
                    # Extract filename without extension
                    import os
                    app_name = os.path.splitext(os.path.basename(exe_path))[0]
            finally:
                kernel32.CloseHandle(handle)
    except Exception:
        pass

    if not app_name:
        app_name = _infer_app_from_title(window_title)

    return {"app_name": app_name, "window_title": window_title}


def _detect_active_window_macos() -> dict[str, str]:
    """Detect the active window on macOS using osascript."""
    app_name = ""
    window_title = ""

    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'tell application "System Events" to get name of first '
                'process whose frontmost is true',
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            app_name = result.stdout.strip()
    except Exception:
        pass

    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'tell application "System Events"\n'
                '  set frontApp to first process whose frontmost is true\n'
                '  tell frontApp\n'
                '    if (count of windows) > 0 then\n'
                '      get name of front window\n'
                '    else\n'
                '      return ""\n'
                '    end if\n'
                '  end tell\n'
                'end tell',
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            window_title = result.stdout.strip()
    except Exception:
        pass

    return {"app_name": app_name, "window_title": window_title}


def _detect_active_window_linux() -> dict[str, str]:
    """Detect the active window on Linux using xdotool."""
    window_title = ""
    app_name = ""

    # Try xdotool first
    try:
        result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            window_title = result.stdout.strip()
    except FileNotFoundError:
        # xdotool not installed, try wmctrl
        try:
            result = subprocess.run(
                ["wmctrl", "-l"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # wmctrl -l lists all windows; grab the last active one
                lines = result.stdout.strip().splitlines()
                if lines:
                    # Format: 0x... desktop_num hostname window_title
                    parts = lines[-1].split(None, 3)
                    if len(parts) >= 4:
                        window_title = parts[3]
        except Exception:
            pass
    except Exception:
        pass

    # Try to get the process name via xdotool PID
    try:
        pid_result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowpid"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if pid_result.returncode == 0:
            pid = pid_result.stdout.strip()
            comm_result = subprocess.run(
                ["ps", "-p", pid, "-o", "comm="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if comm_result.returncode == 0:
                app_name = comm_result.stdout.strip()
    except Exception:
        pass

    if not app_name:
        app_name = _infer_app_from_title(window_title)

    return {"app_name": app_name, "window_title": window_title}


def _infer_app_from_title(title: str) -> str:
    """Best-effort app name inference from a window title string."""
    title_lower = title.lower()

    # Common patterns: "filename - AppName", "AppName - description"
    known = [
        "chrome", "firefox", "edge", "brave", "safari", "opera", "vivaldi",
        "code", "visual studio code", "sublime text", "notepad++",
        "intellij", "pycharm", "webstorm",
        "excel", "word", "outlook", "powerpoint", "onenote",
        "thunderbird", "slack", "discord", "teams", "telegram",
        "terminal", "powershell", "cmd",
        "iterm", "alacritty", "kitty", "konsole",
    ]
    for name in known:
        if name in title_lower:
            return name.replace(" ", "_")

    # Fallback: take last segment after " - "
    if " - " in title:
        candidate = title.rsplit(" - ", 1)[-1].strip()
        if candidate:
            return candidate.lower().replace(" ", "_")

    return "unknown"


# ---------------------------------------------------------------------------
# Action lookup helpers
# ---------------------------------------------------------------------------

def _match_app(app_name: str) -> list[str]:
    """Return suggested actions for a given app name."""
    name = app_name.lower().strip()

    # Direct match
    if name in _APP_ACTION_MAP:
        return _APP_ACTION_MAP[name]

    # Substring match against known keys
    for key, actions in _APP_ACTION_MAP.items():
        if key in name or name in key:
            return actions

    return list(_DEFAULT_ACTIONS)


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

async def context_detect(**kwargs: Any) -> dict[str, Any]:
    """Detect the currently active window/application.

    Returns the app name, window title, and a list of suggested NeuralClaw
    actions relevant to the detected context.
    """
    os_name = platform.system()

    try:
        if os_name == "Windows":
            info = await asyncio.get_event_loop().run_in_executor(
                None, _detect_active_window_windows,
            )
        elif os_name == "Darwin":
            info = await asyncio.get_event_loop().run_in_executor(
                None, _detect_active_window_macos,
            )
        elif os_name == "Linux":
            info = await asyncio.get_event_loop().run_in_executor(
                None, _detect_active_window_linux,
            )
        else:
            return {
                "error": f"Unsupported platform: {os_name}",
                "app_name": "unknown",
                "window_title": "",
                "suggested_actions": list(_DEFAULT_ACTIONS),
            }
    except Exception as exc:
        return {
            "error": f"Detection failed: {exc}",
            "app_name": "unknown",
            "window_title": "",
            "suggested_actions": list(_DEFAULT_ACTIONS),
        }

    app_name = info.get("app_name", "unknown")
    window_title = info.get("window_title", "")
    suggested = _match_app(app_name)

    return {
        "app_name": app_name,
        "window_title": window_title,
        "platform": os_name,
        "suggested_actions": suggested,
    }


async def context_suggest(
    app_name: str,
    window_title: str = "",
    clipboard_content: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Suggest relevant NeuralClaw actions given an app context.

    Uses the rule-based app-to-action mapping and optionally enhances
    suggestions with the configured LLM provider.
    """
    rule_based = _match_app(app_name)

    result: dict[str, Any] = {
        "app_name": app_name,
        "window_title": window_title,
        "rule_based_suggestions": rule_based,
    }

    # If clipboard content is provided, add clipboard-specific hints
    if clipboard_content:
        clip_lower = clipboard_content.strip().lower()
        clip_extras: list[str] = []
        if clip_lower.startswith(("http://", "https://")):
            clip_extras.append("fetch_url")
            clip_extras.append("summarize_page")
        elif re.search(r"(def |class |import |function |const |var |let )", clipboard_content):
            clip_extras.append("explain_code")
            clip_extras.append("find_bugs")
        elif re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", clipboard_content):
            clip_extras.append("draft_reply")
        elif len(clipboard_content) > 200:
            clip_extras.append("format_text")
            clip_extras.append("clipboard_analyze")

        if clip_extras:
            # Merge without duplicates, preserving order
            seen = set(rule_based)
            for action in clip_extras:
                if action not in seen:
                    rule_based.append(action)
                    seen.add(action)
            result["rule_based_suggestions"] = rule_based
            result["clipboard_hint"] = clip_extras

    # LLM-enhanced suggestions (optional)
    if _llm_provider is not None:
        try:
            prompt = (
                f"Given the user is working in '{app_name}' "
                f"(window: '{window_title}'), "
            )
            if clipboard_content:
                # Truncate clipboard for the prompt
                clip_preview = clipboard_content[:500]
                prompt += f"with clipboard containing: '{clip_preview}', "
            prompt += (
                "suggest 3-5 helpful NeuralClaw actions. "
                "Return a JSON list of action name strings only."
            )

            if hasattr(_llm_provider, "acomplete"):
                llm_response = await _llm_provider.acomplete(prompt)
            elif callable(_llm_provider):
                llm_response = await _llm_provider(prompt)
            else:
                llm_response = None

            if llm_response:
                response_text = str(llm_response)
                # Try to parse JSON list from response
                match = re.search(r"\[.*?\]", response_text, re.DOTALL)
                if match:
                    import json
                    llm_suggestions = json.loads(match.group())
                    if isinstance(llm_suggestions, list):
                        result["llm_suggestions"] = [
                            str(s) for s in llm_suggestions
                        ]
        except Exception as exc:
            result["llm_error"] = f"LLM enhancement failed: {exc}"

    return result


async def context_quick_action(
    action_name: str,
    context_text: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute a pre-defined contextual quick action by name.

    Supported actions:
      - ``summarize_page`` -- Summarize browser page content
      - ``explain_code`` -- Explain code from an IDE
      - ``analyze_data`` -- Analyze spreadsheet data
      - ``draft_reply`` -- Draft a reply to an email or message
      - ``format_text`` -- Improve text formatting and clarity

    If an LLM provider is configured, the action prompt is sent to it with
    the provided *context_text*. Otherwise, returns the prompt template for
    the caller to handle.
    """
    if action_name not in _QUICK_ACTION_PROMPTS:
        available = list(_QUICK_ACTION_PROMPTS.keys())
        return {
            "error": f"Unknown quick action: {action_name}",
            "available_actions": available,
        }

    prompt_template = _QUICK_ACTION_PROMPTS[action_name]
    label = _QUICK_ACTION_LABELS.get(action_name, action_name)

    full_prompt = prompt_template
    if context_text:
        full_prompt = (
            f"{prompt_template}\n\n"
            f"--- Context ---\n{context_text[:10000]}\n--- End Context ---"
        )

    # If we have an LLM provider, generate the result directly
    if _llm_provider is not None and context_text:
        try:
            if hasattr(_llm_provider, "acomplete"):
                llm_response = await _llm_provider.acomplete(full_prompt)
            elif callable(_llm_provider):
                llm_response = await _llm_provider(full_prompt)
            else:
                llm_response = None

            if llm_response:
                return {
                    "action": action_name,
                    "label": label,
                    "result": str(llm_response),
                    "source": "llm",
                }
        except Exception as exc:
            return {
                "action": action_name,
                "label": label,
                "error": f"LLM execution failed: {exc}",
                "prompt": full_prompt,
                "source": "error",
            }

    # No LLM or no context -- return the prompt for the caller
    return {
        "action": action_name,
        "label": label,
        "prompt": full_prompt,
        "source": "prompt_only",
        "note": (
            "No LLM provider configured or no context_text supplied. "
            "Pass the prompt to your LLM to execute this action."
        ),
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="context_aware",
        description=(
            "Context-aware suggestions based on the user's active desktop "
            "environment. Detects the foreground application and recommends "
            "relevant NeuralClaw actions."
        ),
        capabilities=[Capability.DESKTOP_CONTROL],
        tools=[
            ToolDefinition(
                name="context_detect",
                description=(
                    "Detect the currently active window/application on the "
                    "user's desktop. Returns the app name, window title, and "
                    "a list of suggested NeuralClaw actions relevant to the "
                    "detected context. Cross-platform: Windows, macOS, Linux."
                ),
                parameters=[],
                handler=context_detect,
            ),
            ToolDefinition(
                name="context_suggest",
                description=(
                    "Given an application context (app name, window title, "
                    "and optional clipboard content), suggest relevant "
                    "NeuralClaw actions. Uses a rule-based mapping with "
                    "optional LLM enhancement for richer suggestions."
                ),
                parameters=[
                    ToolParameter(
                        name="app_name",
                        type="string",
                        description=(
                            "Name of the active application "
                            "(e.g. 'chrome', 'vscode', 'excel')"
                        ),
                    ),
                    ToolParameter(
                        name="window_title",
                        type="string",
                        description="Title of the active window",
                        required=False,
                        default="",
                    ),
                    ToolParameter(
                        name="clipboard_content",
                        type="string",
                        description=(
                            "Current clipboard text content for additional "
                            "context-aware suggestions"
                        ),
                        required=False,
                        default="",
                    ),
                ],
                handler=context_suggest,
            ),
            ToolDefinition(
                name="context_quick_action",
                description=(
                    "Execute a pre-defined contextual quick action by name. "
                    "Available actions: summarize_page (browser), "
                    "explain_code (IDE), analyze_data (spreadsheet), "
                    "draft_reply (email/message), format_text (editor). "
                    "If an LLM provider is configured, returns the generated "
                    "result; otherwise returns the prompt template."
                ),
                parameters=[
                    ToolParameter(
                        name="action_name",
                        type="string",
                        description="Name of the quick action to execute",
                        enum=[
                            "summarize_page",
                            "explain_code",
                            "analyze_data",
                            "draft_reply",
                            "format_text",
                        ],
                    ),
                    ToolParameter(
                        name="context_text",
                        type="string",
                        description=(
                            "Text content to process (e.g. page content, "
                            "code snippet, email body). Required for LLM "
                            "execution; optional if you only need the prompt."
                        ),
                        required=False,
                        default="",
                    ),
                ],
                handler=context_quick_action,
            ),
        ],
    )
