"""
Built-in Skill: Web Search — Search the web via DuckDuckGo.

All outbound HTTP requests are validated against the SSRF blocklist
before execution. Private networks, cloud metadata endpoints, and
non-http(s) schemes are blocked.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.network import validate_url, validate_url_with_dns
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


# DuckDuckGo API is a known-safe endpoint
_DUCKDUCKGO_API = "https://api.duckduckgo.com/"


async def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the web using DuckDuckGo Instant Answer API."""

    # Validate the API URL (static, but defense-in-depth)
    url_check = validate_url(_DUCKDUCKGO_API)
    if not url_check.allowed:
        return {"error": f"URL blocked by SSRF policy: {url_check.reason}"}

    try:
        params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _DUCKDUCKGO_API,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return {"error": f"Search failed with status {resp.status}"}
                data = await resp.json(content_type=None)

        results = []

        # Abstract (instant answer)
        if data.get("Abstract"):
            results.append({
                "title": data.get("Heading", ""),
                "snippet": data["Abstract"],
                "url": data.get("AbstractURL", ""),
            })

        # Related topics
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and "Text" in topic:
                # Validate any URLs in results before including them
                topic_url = topic.get("FirstURL", "")
                if topic_url:
                    topic_url_check = validate_url(topic_url)
                    if not topic_url_check.allowed:
                        topic_url = "[blocked]"

                results.append({
                    "title": topic.get("Text", "")[:100],
                    "snippet": topic.get("Text", ""),
                    "url": topic_url,
                })

        if not results:
            return {"message": f"No results found for '{query}'", "results": []}

        return {"query": query, "results": results[:max_results]}

    except Exception as e:
        return {"error": f"Search failed: {str(e)}"}


async def fetch_url(url: str) -> dict[str, Any]:
    """
    Fetch content from a URL with SSRF protection.

    Validates the URL against the SSRF blocklist before making the request.
    """
    url_check = await validate_url_with_dns(url)
    if not url_check.allowed:
        return {"error": f"URL blocked by security policy: {url_check.reason}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=False,  # Prevent redirect-based SSRF
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    redirect_url = str(resp.headers.get("Location", ""))
                    redirect_check = await validate_url_with_dns(redirect_url)
                    if not redirect_check.allowed:
                        return {"error": f"Redirect blocked by SSRF policy: {redirect_check.reason}"}
                    return {"error": f"Redirect to {redirect_url} — re-fetch required", "redirect": redirect_url}

                if resp.status != 200:
                    return {"error": f"Fetch failed with status {resp.status}"}

                content_type = resp.content_type or "text/plain"
                if "text" in content_type or "json" in content_type:
                    text = await resp.text(errors="replace")
                    return {"url": url, "content": text[:50_000], "content_type": content_type}
                else:
                    return {"error": f"Unsupported content type: {content_type}"}

    except Exception as e:
        return {"error": f"Fetch failed: {str(e)}"}


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="web_search",
        description="Search the web for information",
        capabilities=[Capability.NETWORK_HTTP],
        tools=[
            ToolDefinition(
                name="web_search",
                description="Search the web for information using DuckDuckGo",
                parameters=[
                    ToolParameter(name="query", type="string", description="Search query"),
                    ToolParameter(name="max_results", type="integer", description="Max results to return", required=False, default=5),
                ],
                handler=web_search,
            ),
            ToolDefinition(
                name="fetch_url",
                description="Fetch content from a URL (with SSRF protection)",
                parameters=[
                    ToolParameter(name="url", type="string", description="URL to fetch"),
                ],
                handler=fetch_url,
            ),
        ],
    )
