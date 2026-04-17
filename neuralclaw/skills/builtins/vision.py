"""
Built-in Skill: Vision — Image understanding via vision-capable LLMs.

Supports:
  - Analyzing images from file path or URL
  - Extracting text (OCR-style) from images
  - Comparing multiple images
  - Describing screenshots

Routes through the gateway's active provider if it supports vision,
otherwise falls back to a direct Anthropic or OpenAI vision call.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
from pathlib import Path
from typing import Any

import aiohttp

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.network import validate_url
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

# ---------------------------------------------------------------------------
# Module-level state (injected by gateway)
# ---------------------------------------------------------------------------

_gateway_ref: Any = None          # NeuralClawGateway instance
_vision_provider: str = "auto"    # "auto" | "anthropic" | "openai" | "local"


def set_gateway(gw: Any) -> None:
    global _gateway_ref
    _gateway_ref = gw


def set_vision_provider(provider: str) -> None:
    global _vision_provider
    _vision_provider = provider


# ---------------------------------------------------------------------------
# Image loading helpers
# ---------------------------------------------------------------------------

async def _load_image_as_base64(source: str) -> tuple[str, str]:
    """
    Load an image from a file path or URL and return (base64_data, media_type).
    Raises ValueError if the source is invalid or blocked.
    """
    # URL
    if source.startswith("http://") or source.startswith("https://"):
        check = validate_url(source)
        if not check.allowed:
            raise ValueError(f"URL blocked by SSRF policy: {check.reason}")
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession() as session:
            async with session.get(source, timeout=timeout) as resp:
                if resp.status != 200:
                    raise ValueError(f"Failed to fetch image: HTTP {resp.status}")
                content_type = resp.content_type or "image/jpeg"
                media_type = content_type.split(";")[0].strip()
                raw = await resp.read()
        return base64.b64encode(raw).decode(), media_type

    # File path
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"File not found: {source}")
    if not path.is_file():
        raise ValueError(f"Not a file: {source}")

    mime, _ = mimetypes.guess_type(str(path))
    media_type = mime or "image/jpeg"
    raw = path.read_bytes()
    return base64.b64encode(raw).decode(), media_type


def _build_anthropic_image_block(b64: str, media_type: str) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": b64,
        },
    }


def _build_openai_image_block(b64: str, media_type: str) -> dict[str, Any]:
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{media_type};base64,{b64}",
            "detail": "high",
        },
    }


# ---------------------------------------------------------------------------
# Vision API calls
# ---------------------------------------------------------------------------

async def _call_anthropic_vision(prompt: str, images: list[tuple[str, str]]) -> str:
    """Call Anthropic Claude with vision."""
    from neuralclaw.config import get_api_key
    api_key = get_api_key("anthropic") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("No Anthropic API key configured")

    # Build content blocks
    content: list[dict[str, Any]] = []
    for b64, mt in images:
        content.append(_build_anthropic_image_block(b64, mt))
    content.append({"type": "text", "text": prompt})

    payload = {
        "model": "claude-opus-4-6",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers=headers,
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Anthropic vision error {resp.status}: {text[:300]}")
            data = await resp.json(content_type=None)

    return data["content"][0]["text"]


async def _call_openai_vision(prompt: str, images: list[tuple[str, str]], model: str = "gpt-4o") -> str:
    """Call OpenAI GPT-4o (or compatible) with vision."""
    from neuralclaw.config import get_api_key
    api_key = get_api_key("openai") or os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    if not api_key:
        raise RuntimeError("No OpenAI API key configured")

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for b64, mt in images:
        content.append(_build_openai_image_block(b64, mt))

    payload = {
        "model": model,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"OpenAI vision error {resp.status}: {text[:300]}")
            data = await resp.json(content_type=None)

    return data["choices"][0]["message"]["content"]


async def _call_local_vision(prompt: str, images: list[tuple[str, str]]) -> str:
    """Call local Ollama/LM Studio vision model (llava, minicpm-v, etc.)."""
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("VISION_MODEL", "llava")

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for b64, mt in images:
        content.append(_build_openai_image_block(b64, mt))

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "stream": False,
    }
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            json=payload,
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Local vision error {resp.status}: {text[:300]}")
            data = await resp.json(content_type=None)

    return data["choices"][0]["message"]["content"]


async def _vision_call(prompt: str, images: list[tuple[str, str]]) -> str:
    """Route vision call to the best available provider."""
    provider = _vision_provider

    # Auto-detect based on configured keys
    if provider == "auto":
        from neuralclaw.config import get_api_key
        if get_api_key("anthropic") or os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif get_api_key("openai") or os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
        else:
            provider = "local"

    if provider == "anthropic":
        return await _call_anthropic_vision(prompt, images)
    if provider == "openai":
        return await _call_openai_vision(prompt, images)
    if provider == "local":
        return await _call_local_vision(prompt, images)

    raise RuntimeError(f"Unknown vision provider: {provider}")


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

async def analyze_image(
    source: str,
    prompt: str = "Describe this image in detail.",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Analyze an image from a file path or URL using a vision-capable model.

    Args:
        source: File path or HTTP/HTTPS URL to the image.
        prompt: What to ask about the image (default: describe it).
    """
    try:
        b64, mt = await _load_image_as_base64(source)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    try:
        result = await _vision_call(prompt, [(b64, mt)])
        return {"ok": True, "source": source, "analysis": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def extract_text_from_image(
    source: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Extract all readable text from an image (OCR-style).

    Args:
        source: File path or HTTP/HTTPS URL to the image.
    """
    prompt = (
        "Extract ALL text visible in this image exactly as it appears. "
        "Preserve formatting, line breaks, and structure. "
        "Return only the extracted text, no commentary."
    )
    try:
        b64, mt = await _load_image_as_base64(source)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    try:
        text = await _vision_call(prompt, [(b64, mt)])
        return {"ok": True, "source": source, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def describe_screenshot(
    source: str,
    focus: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Describe a screenshot, optionally focused on a specific area or element.

    Args:
        source: File path or HTTP/HTTPS URL to the screenshot.
        focus:  Optional focus area, e.g. "the error message", "the chart".
    """
    if focus:
        prompt = f"Describe this screenshot, focusing on: {focus}. Include any text, UI elements, errors, or data visible."
    else:
        prompt = (
            "Describe this screenshot in detail. Include: "
            "what application/page is shown, key UI elements, any text, errors, "
            "charts, or data visible. Be specific and structured."
        )
    try:
        b64, mt = await _load_image_as_base64(source)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    try:
        result = await _vision_call(prompt, [(b64, mt)])
        return {"ok": True, "source": source, "description": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def compare_images(
    source_a: str,
    source_b: str,
    prompt: str = "Compare these two images and describe the differences.",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Compare two images side by side using a vision model.

    Args:
        source_a: First image (file path or URL).
        source_b: Second image (file path or URL).
        prompt:   Comparison instruction.
    """
    try:
        b64_a, mt_a = await _load_image_as_base64(source_a)
        b64_b, mt_b = await _load_image_as_base64(source_b)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    try:
        result = await _vision_call(prompt, [(b64_a, mt_a), (b64_b, mt_b)])
        return {
            "ok": True,
            "source_a": source_a,
            "source_b": source_b,
            "comparison": result,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def detect_vision_capability(**kwargs: Any) -> dict[str, Any]:
    """Check which vision providers are available."""
    from neuralclaw.config import get_api_key
    return {
        "anthropic": bool(get_api_key("anthropic") or os.environ.get("ANTHROPIC_API_KEY")),
        "openai": bool(get_api_key("openai") or os.environ.get("OPENAI_API_KEY")),
        "local": bool(os.environ.get("VISION_MODEL")),
        "active_provider": _vision_provider,
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="vision",
        description="Analyze images, extract text, and describe screenshots using vision-capable LLMs",
        capabilities=[Capability.NETWORK_HTTP],
        tools=[
            ToolDefinition(
                name="analyze_image",
                description=(
                    "Analyze an image from a file path or URL. Ask any question about it — "
                    "what's in it, what it means, read text, identify objects, etc."
                ),
                parameters=[
                    ToolParameter(name="source", type="string", description="File path or HTTP/HTTPS URL to the image"),
                    ToolParameter(name="prompt", type="string", description='What to ask about the image (default: "Describe this image in detail.")', required=False, default="Describe this image in detail."),
                ],
                handler=analyze_image,
            ),
            ToolDefinition(
                name="extract_text_from_image",
                description="Extract all readable text from an image (OCR-style). Returns exact text as it appears.",
                parameters=[
                    ToolParameter(name="source", type="string", description="File path or HTTP/HTTPS URL to the image"),
                ],
                handler=extract_text_from_image,
            ),
            ToolDefinition(
                name="describe_screenshot",
                description="Describe a screenshot in detail — UI elements, errors, data, charts, text visible on screen.",
                parameters=[
                    ToolParameter(name="source", type="string", description="File path or HTTP/HTTPS URL to the screenshot"),
                    ToolParameter(name="focus", type="string", description='Optional focus area, e.g. "the error message" or "the chart"', required=False, default=""),
                ],
                handler=describe_screenshot,
            ),
            ToolDefinition(
                name="compare_images",
                description="Compare two images and describe differences, changes, or similarities.",
                parameters=[
                    ToolParameter(name="source_a", type="string", description="First image (file path or URL)"),
                    ToolParameter(name="source_b", type="string", description="Second image (file path or URL)"),
                    ToolParameter(name="prompt", type="string", description="Comparison instruction", required=False, default="Compare these two images and describe the differences."),
                ],
                handler=compare_images,
            ),
            ToolDefinition(
                name="detect_vision_capability",
                description="Check which vision providers (Anthropic, OpenAI, local) are available.",
                parameters=[],
                handler=detect_vision_capability,
            ),
        ],
    )
