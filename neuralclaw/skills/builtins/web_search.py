"""
Built-in Skill: Web Search — Multi-provider web search and page extraction.

Supports Brave Search, Google Custom Search, SearXNG, and DuckDuckGo
(fallback). The highest-priority configured provider is used first, with
automatic fallback on failure.

All outbound HTTP requests are validated against the SSRF blocklist
before execution. Private networks, cloud metadata endpoints, and
non-http(s) schemes are blocked.
"""

from __future__ import annotations

import asyncio
import html
import os
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import aiohttp

from neuralclaw.config import get_api_key, load_config
from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.network import validate_url, validate_url_with_dns
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DUCKDUCKGO_API = "https://api.duckduckgo.com/"
_DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_SERPER_SEARCH_URL = "https://google.serper.dev/search"

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15)
_SEARCH_TIMEOUT = aiohttp.ClientTimeout(total=10)
_CONTENT_LIMIT = 100_000  # 100 KB
_USER_AGENT = (
    "Mozilla/5.0 (compatible; NeuralClaw/1.0; +https://github.com/neuralclaw)"
)

# ---------------------------------------------------------------------------
# HTML helpers (no BeautifulSoup dependency)
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_WS_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_SCRIPT_STYLE_RE = re.compile(
    r"<\s*(script|style|noscript)[^>]*>.*?</\s*\1\s*>", re.DOTALL | re.IGNORECASE
)
_BOILERPLATE_SECTION_RE = re.compile(
    r"<\s*(nav|header|footer|aside|form)[^>]*>.*?</\s*\1\s*>",
    re.DOTALL | re.IGNORECASE,
)
_MAIN_CONTENT_RE = re.compile(
    r"<\s*(main|article)[^>]*>(?P<content>.*?)</\s*\1\s*>",
    re.DOTALL | re.IGNORECASE,
)
_ROLE_MAIN_RE = re.compile(
    r'<(?P<tag>div|section)[^>]*role\s*=\s*["\']main["\'][^>]*>(?P<content>.*?)</(?P=tag)>',
    re.DOTALL | re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_META_DESC_RE = re.compile(
    r'<meta\s+[^>]*name\s*=\s*["\']description["\'][^>]*content\s*=\s*["\']([^"\']*)["\']',
    re.IGNORECASE,
)
_META_DESC_RE2 = re.compile(
    r'<meta\s+[^>]*content\s*=\s*["\']([^"\']*)["\'][^>]*name\s*=\s*["\']description["\']',
    re.IGNORECASE,
)
_DDG_RESULT_BLOCK_RE = re.compile(
    r'<div class="result results_links[^"]*?web-result[^"]*">(?P<block>.*?)</div>\s*</div>\s*</div>',
    re.DOTALL | re.IGNORECASE,
)
_DDG_RESULT_LINK_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_DDG_RESULT_SNIPPET_RE = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)

_RECOMMENDATION_RE = re.compile(
    r"\b(best|top|recommend|recommended|buy|buying|vs|versus|review|reviews|compare|comparison)\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b20\d{2}\b")
_LOW_VALUE_AGGREGATORS = {
    "msn.com",
    "newsbreak.com",
    "yahoo.com",
    "aol.com",
}
_EDITORIAL_REVIEW_DOMAINS = {
    "tomsguide.com",
    "pcmag.com",
    "techradar.com",
    "cnet.com",
    "theverge.com",
    "wired.com",
    "gsmarena.com",
    "consumerreports.org",
    "cnn.com",
    "stuff.tv",
}


def _api_section(name: str) -> dict[str, Any]:
    try:
        config = load_config()
        section = config.apis.get(name, {}) if isinstance(config.apis, dict) else {}
        return section if isinstance(section, dict) else {}
    except Exception:
        return {}


def _strip_html(raw: str) -> str:
    """Strip HTML tags and collapse whitespace to produce readable text."""
    text = _SCRIPT_STYLE_RE.sub("", raw)
    text = _BOILERPLATE_SECTION_RE.sub("", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _extract_readable_fragment(raw: str) -> str:
    for regex in (_MAIN_CONTENT_RE, _ROLE_MAIN_RE):
        match = regex.search(raw)
        if match:
            content = match.group("content")
            stripped = _strip_html(content)
            if len(stripped) >= 500:
                return stripped
    return _strip_html(raw)


def _extract_title(raw: str) -> str:
    """Extract <title> from raw HTML."""
    m = _TITLE_RE.search(raw[:8192])
    return html.unescape(m.group(1).strip()) if m else ""


def _extract_meta_description(raw: str) -> str:
    """Extract meta description from raw HTML."""
    head = raw[:16384]
    m = _META_DESC_RE.search(head) or _META_DESC_RE2.search(head)
    return html.unescape(m.group(1).strip()) if m else ""


def _normalize_text(text: str) -> str:
    return _strip_html(text).strip()


def _unwrap_duckduckgo_href(href: str) -> str:
    href = html.unescape(href or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("/"):
        href = urljoin(_DUCKDUCKGO_HTML_URL, href)
    parsed = urlparse(href)
    if "duckduckgo.com" in (parsed.netloc or ""):
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg", [""])[0]
        if uddg:
            return unquote(uddg)
    return href


def _result_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _recommendation_query(query: str) -> bool:
    return bool(_RECOMMENDATION_RE.search(query))


def _query_variants(query: str) -> list[str]:
    base = query.strip()
    if not base:
        return []
    variants = [base]
    if _recommendation_query(base):
        variants.append(f"{base} reviews")
        if not _YEAR_RE.search(base):
            variants.append(f"{base} 2026")
        variants.append(f"{base} buying guide")
    seen: set[str] = set()
    ordered: list[str] = []
    for item in variants:
        norm = item.casefold()
        if norm in seen:
            continue
        seen.add(norm)
        ordered.append(item)
    return ordered


def _score_result(query: str, item: dict[str, str], domain_counts: dict[str, int]) -> float:
    title = (item.get("title") or "").lower()
    snippet = (item.get("snippet") or "").lower()
    url = item.get("url") or ""
    domain = _result_domain(url)
    terms = [term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2]
    coverage = sum(1 for term in terms if term in title or term in snippet)
    score = coverage * 3.0
    if _recommendation_query(query):
        for marker, bonus in (
            ("best", 2.0),
            ("review", 1.5),
            ("reviews", 1.5),
            ("tested", 1.5),
            ("guide", 1.0),
            ("comparison", 1.0),
        ):
            if marker in title:
                score += bonus
        if domain in _EDITORIAL_REVIEW_DOMAINS:
            score += 2.0
        if domain in _LOW_VALUE_AGGREGATORS:
            score -= 3.0
    if _YEAR_RE.search(query):
        year = _YEAR_RE.search(query).group(0)
        if year and (year in title or year in snippet):
            score += 2.0
    score += min(len(snippet) / 240.0, 1.5)
    if domain:
        score -= max(domain_counts.get(domain, 1) - 1, 0) * 1.25
    return score


def _page_quality_score(page: dict[str, Any]) -> float:
    score = 0.0
    status = str(page.get("status") or "")
    content = str(page.get("content") or "")
    domain = _result_domain(str(page.get("url") or ""))
    if status == "ok":
        score += 4.0
    elif "fetch_failed" in status:
        score -= 2.0
    score += min(len(content) / 1200.0, 4.0)
    if len(content.strip()) < 250:
        score -= 2.5
    if domain in _EDITORIAL_REVIEW_DOMAINS:
        score += 1.5
    if domain in _LOW_VALUE_AGGREGATORS:
        score -= 2.0
    return score


def _rank_and_dedup_results(query: str, results: list[dict[str, str]], max_results: int) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    domain_counts: dict[str, int] = {}

    for item in results:
        url = (item.get("url") or "").strip()
        if not url or url == "[blocked]":
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append({
            "title": _normalize_text(item.get("title", "")),
            "snippet": _normalize_text(item.get("snippet", "")),
            "url": url,
        })

    scored = []
    for item in deduped:
        domain = _result_domain(item["url"])
        score = _score_result(query, item, domain_counts)
        scored.append((score, item))
        domain_counts[domain] = domain_counts.get(domain, 0) + 1

    scored.sort(key=lambda pair: pair[0], reverse=True)

    final: list[dict[str, str]] = []
    used_domains: set[str] = set()
    for _score, item in scored:
        domain = _result_domain(item["url"])
        if domain and domain in used_domains and len(final) < max_results // 2:
            continue
        final.append(item)
        if domain:
            used_domains.add(domain)
        if len(final) >= max_results:
            break

    if len(final) < max_results:
        for _score, item in scored:
            if item in final:
                continue
            final.append(item)
            if len(final) >= max_results:
                break
    return final[:max_results]


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def detect_search_provider() -> dict[str, Any]:
    """
    Check which search providers are configured and return info about them.

    Returns a dict with:
      - active: name of the highest-priority available provider
      - providers: list of dicts with name / configured / priority
    """
    providers = []

    # 1. Tavily (best for AI agents — structured results with answer synthesis)
    tavily_key = get_api_key("tavily") or os.environ.get("TAVILY_API_KEY")
    providers.append({"name": "tavily", "configured": bool(tavily_key), "priority": 1})

    # 2. Brave Search
    brave_key = get_api_key("brave") or os.environ.get("BRAVE_API_KEY")
    providers.append({"name": "brave", "configured": bool(brave_key), "priority": 2})

    # 3. Serper (Google results via API — fast, generous free tier)
    serper_key = get_api_key("serper") or os.environ.get("SERPER_API_KEY")
    providers.append({"name": "serper", "configured": bool(serper_key), "priority": 3})

    # 4. Google Custom Search
    google_cfg = _api_section("google_search")
    google_key = get_api_key("google_search") or os.environ.get("GOOGLE_SEARCH_API_KEY")
    google_cx = str(google_cfg.get("cx") or os.environ.get("GOOGLE_SEARCH_CX", "")).strip()
    providers.append({"name": "google", "configured": bool(google_key and google_cx), "priority": 4})

    # 5. SearXNG (self-hosted)
    searxng_cfg = _api_section("searxng")
    searxng_url = str(searxng_cfg.get("base_url") or os.environ.get("SEARXNG_URL", "")).strip()
    providers.append({"name": "searxng", "configured": bool(searxng_url), "priority": 5})

    # 6. DuckDuckGo HTML fallback (real results, no API key)
    providers.append({"name": "duckduckgo", "configured": True, "priority": 6})

    # 7. DuckDuckGo Instant Answer API (last resort — very limited)
    providers.append({"name": "duckduckgo_instant", "configured": True, "priority": 7})

    active = next((p["name"] for p in providers if p["configured"]), "")
    return {"active": active, "providers": providers}


# ---------------------------------------------------------------------------
# Individual search backends
# ---------------------------------------------------------------------------

async def _search_brave(
    query: str, max_results: int, session: aiohttp.ClientSession
) -> list[dict[str, str]]:
    """Search using Brave Search API."""
    api_key = get_api_key("brave") or os.environ.get("BRAVE_API_KEY", "")
    url_check = validate_url(_BRAVE_SEARCH_URL)
    if not url_check.allowed:
        raise RuntimeError(f"URL blocked: {url_check.reason}")

    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    params = {"q": query, "count": str(min(max_results, 20))}

    async with session.get(
        _BRAVE_SEARCH_URL,
        headers=headers,
        params=params,
        timeout=_SEARCH_TIMEOUT,
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Brave search returned {resp.status}")
        data = await resp.json(content_type=None)

    results: list[dict[str, str]] = []
    for item in (data.get("web", {}).get("results", []))[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "snippet": item.get("description", ""),
            "url": item.get("url", ""),
        })
    return results


async def _search_google(
    query: str, max_results: int, session: aiohttp.ClientSession
) -> list[dict[str, str]]:
    """Search using Google Custom Search JSON API."""
    api_key = (
        get_api_key("google_search")
        or os.environ.get("GOOGLE_SEARCH_API_KEY", "")
    )
    google_cfg = _api_section("google_search")
    cx = str(google_cfg.get("cx") or os.environ.get("GOOGLE_SEARCH_CX", "")).strip()
    url_check = validate_url(_GOOGLE_SEARCH_URL)
    if not url_check.allowed:
        raise RuntimeError(f"URL blocked: {url_check.reason}")

    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": str(min(max_results, 10)),
    }

    async with session.get(
        _GOOGLE_SEARCH_URL,
        params=params,
        timeout=_SEARCH_TIMEOUT,
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Google search returned {resp.status}")
        data = await resp.json(content_type=None)

    results: list[dict[str, str]] = []
    for item in data.get("items", [])[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "snippet": item.get("snippet", ""),
            "url": item.get("link", ""),
        })
    return results


async def _search_searxng(
    query: str, max_results: int, session: aiohttp.ClientSession
) -> list[dict[str, str]]:
    """Search using a self-hosted SearXNG instance."""
    searxng_cfg = _api_section("searxng")
    base_url = str(searxng_cfg.get("base_url") or os.environ.get("SEARXNG_URL", "")).strip().rstrip("/")
    search_url = f"{base_url}/search"
    url_check = validate_url(search_url)
    if not url_check.allowed:
        raise RuntimeError(f"URL blocked: {url_check.reason}")

    params = {"q": query, "format": "json", "pageno": "1"}

    async with session.get(
        search_url,
        params=params,
        timeout=_SEARCH_TIMEOUT,
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(f"SearXNG returned {resp.status}")
        data = await resp.json(content_type=None)

    results: list[dict[str, str]] = []
    for item in data.get("results", [])[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "snippet": item.get("content", ""),
            "url": item.get("url", ""),
        })
    return results


async def _search_tavily(
    query: str, max_results: int, session: aiohttp.ClientSession
) -> list[dict[str, str]]:
    """Search using Tavily AI Search API — best quality for AI agents."""
    api_key = get_api_key("tavily") or os.environ.get("TAVILY_API_KEY", "")
    url_check = validate_url(_TAVILY_SEARCH_URL)
    if not url_check.allowed:
        raise RuntimeError(f"URL blocked: {url_check.reason}")

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": min(max_results, 10),
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
    }
    async with session.post(
        _TAVILY_SEARCH_URL,
        json=payload,
        timeout=_SEARCH_TIMEOUT,
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Tavily returned {resp.status}")
        data = await resp.json(content_type=None)

    results: list[dict[str, str]] = []
    for item in data.get("results", [])[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "snippet": item.get("content", ""),
            "url": item.get("url", ""),
        })
    return results


async def _search_serper(
    query: str, max_results: int, session: aiohttp.ClientSession
) -> list[dict[str, str]]:
    """Search using Serper (Google results via API — generous free tier)."""
    api_key = get_api_key("serper") or os.environ.get("SERPER_API_KEY", "")
    url_check = validate_url(_SERPER_SEARCH_URL)
    if not url_check.allowed:
        raise RuntimeError(f"URL blocked: {url_check.reason}")

    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"q": query, "num": min(max_results, 10)}
    async with session.post(
        _SERPER_SEARCH_URL,
        json=payload,
        headers=headers,
        timeout=_SEARCH_TIMEOUT,
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Serper returned {resp.status}")
        data = await resp.json(content_type=None)

    results: list[dict[str, str]] = []
    for item in data.get("organic", [])[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "snippet": item.get("snippet", ""),
            "url": item.get("link", ""),
        })
    return results


async def _search_duckduckgo(
    query: str, max_results: int, session: aiohttp.ClientSession
) -> list[dict[str, str]]:
    """Search using DuckDuckGo HTML results directly for stable fallback behavior."""
    search_url = f"{_DUCKDUCKGO_HTML_URL}?q={quote_plus(query)}"
    url_check = validate_url(search_url)
    if not url_check.allowed:
        raise RuntimeError(f"URL blocked: {url_check.reason}")

    async with session.get(
        search_url,
        timeout=_SEARCH_TIMEOUT,
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(f"DuckDuckGo HTML returned {resp.status}")
        raw_html = await resp.text(errors="replace")

    results: list[dict[str, str]] = []
    for block_match in _DDG_RESULT_BLOCK_RE.finditer(raw_html):
        block = block_match.group("block")
        link_match = _DDG_RESULT_LINK_RE.search(block)
        if not link_match:
            continue
        snippet_match = _DDG_RESULT_SNIPPET_RE.search(block)
        url = _unwrap_duckduckgo_href(link_match.group("href"))
        if not url:
            continue
        results.append({
            "title": _normalize_text(link_match.group("title")),
            "snippet": _normalize_text(snippet_match.group("snippet") if snippet_match else ""),
            "url": url,
        })
        if len(results) >= max(max_results * 2, 12):
            break
    return results


async def _search_duckduckgo_instant(
    query: str, max_results: int, session: aiohttp.ClientSession
) -> list[dict[str, str]]:
    """DuckDuckGo Instant Answer API — last resort, very limited."""
    url_check = validate_url(_DUCKDUCKGO_API)
    if not url_check.allowed:
        raise RuntimeError(f"URL blocked: {url_check.reason}")

    params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
    async with session.get(
        _DUCKDUCKGO_API,
        params=params,
        timeout=_SEARCH_TIMEOUT,
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(f"DuckDuckGo instant returned {resp.status}")
        data = await resp.json(content_type=None)

    results: list[dict[str, str]] = []
    if data.get("Abstract"):
        results.append({
            "title": data.get("Heading", ""),
            "snippet": data["Abstract"],
            "url": data.get("AbstractURL", ""),
        })
    for topic in data.get("RelatedTopics", []):
        if len(results) >= max_results:
            break
        if isinstance(topic, dict) and "Text" in topic:
            topic_url = topic.get("FirstURL", "")
            if topic_url:
                chk = validate_url(topic_url)
                if not chk.allowed:
                    topic_url = "[blocked]"
            results.append({
                "title": topic.get("Text", "")[:100],
                "snippet": topic.get("Text", ""),
                "url": topic_url,
            })
    return results[:max_results]


# Provider dispatch order (highest quality first)
_PROVIDERS: list[tuple[str, Any]] = [
    ("tavily", _search_tavily),
    ("brave", _search_brave),
    ("serper", _search_serper),
    ("google", _search_google),
    ("searxng", _search_searxng),
    ("duckduckgo", _search_duckduckgo),
    ("duckduckgo_instant", _search_duckduckgo_instant),
]


def _provider_available(name: str) -> bool:
    """Return True if the named provider has its credentials configured."""
    if name == "tavily":
        return bool(get_api_key("tavily") or os.environ.get("TAVILY_API_KEY"))
    if name == "brave":
        return bool(get_api_key("brave") or os.environ.get("BRAVE_API_KEY"))
    if name == "serper":
        return bool(get_api_key("serper") or os.environ.get("SERPER_API_KEY"))
    if name == "google":
        google_cfg = _api_section("google_search")
        key = get_api_key("google_search") or os.environ.get("GOOGLE_SEARCH_API_KEY")
        cx = str(google_cfg.get("cx") or os.environ.get("GOOGLE_SEARCH_CX", "")).strip()
        return bool(key and cx)
    if name == "searxng":
        searxng_cfg = _api_section("searxng")
        return bool(str(searxng_cfg.get("base_url") or os.environ.get("SEARXNG_URL", "")).strip())
    if name == "duckduckgo":
        return True
    if name == "duckduckgo_instant":
        return True
    return False


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

async def web_search(query: str, max_results: int = 5, **kwargs: Any) -> dict[str, Any]:
    """
    Search the web using the highest-priority configured provider.

    Falls back through Brave -> Google -> SearXNG -> DuckDuckGo on failure.
    """
    errors: list[str] = []

    async with aiohttp.ClientSession(
        headers={"User-Agent": _USER_AGENT},
    ) as session:
        collected_results: list[dict[str, str]] = []
        provider_used = None
        variants = _query_variants(query)
        for name, search_fn in _PROVIDERS:
            if not _provider_available(name):
                continue
            try:
                for variant in variants:
                    results = await search_fn(variant, max(max_results * 2, 8), session)
                    if results:
                        collected_results.extend(results)
                if collected_results:
                    ranked = _rank_and_dedup_results(query, collected_results, max_results)
                    return {
                        "query": query,
                        "variants": variants,
                        "provider": name,
                        "results": ranked,
                    }
                errors.append(f"{name}: no results")
                provider_used = name
            except Exception as exc:
                errors.append(f"{name}: {exc}")

    if errors:
        return {"error": f"All providers failed: {'; '.join(errors)}", "provider": provider_used or "", "results": []}
    return {"error": "No search providers available", "results": []}


async def fetch_url(url: str, **kwargs: Any) -> dict[str, Any]:
    """
    Fetch content from a URL with SSRF protection and HTML extraction.

    Returns structured output with title, description, content (plain text),
    and the resolved URL.
    """
    url_check = await validate_url_with_dns(url)
    if not url_check.allowed:
        return {"error": f"URL blocked by security policy: {url_check.reason}"}

    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": _USER_AGENT},
        ) as session:
            async with session.get(
                url,
                timeout=_DEFAULT_TIMEOUT,
                allow_redirects=False,  # Prevent redirect-based SSRF
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    redirect_url = str(resp.headers.get("Location", ""))
                    redirect_check = await validate_url_with_dns(redirect_url)
                    if not redirect_check.allowed:
                        return {
                            "error": f"Redirect blocked by SSRF policy: {redirect_check.reason}",
                        }
                    return {
                        "error": f"Redirect to {redirect_url} — re-fetch required",
                        "redirect": redirect_url,
                    }

                if resp.status != 200:
                    return {"error": f"Fetch failed with status {resp.status}"}

                content_type = resp.content_type or "text/plain"

                # JSON — return raw
                if "json" in content_type:
                    text = await resp.text(errors="replace")
                    return {
                        "url": url,
                        "title": "",
                        "description": "",
                        "content": text[:_CONTENT_LIMIT],
                        "content_type": content_type,
                    }

                # HTML / text — extract readable content
                if "text" in content_type or "html" in content_type:
                    raw = await resp.text(errors="replace")
                    title = _extract_title(raw)
                    description = _extract_meta_description(raw)
                    content = _extract_readable_fragment(raw)
                    return {
                        "url": url,
                        "title": title,
                        "description": description,
                        "content": content[:_CONTENT_LIMIT],
                        "content_type": content_type,
                    }

                return {"error": f"Unsupported content type: {content_type}"}

    except Exception as exc:
        return {"error": f"Fetch failed: {exc}"}


async def browse_and_extract(
    query: str,
    max_pages: int = 3,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    One-shot research: search for a query, fetch the top results, and
    extract readable content from each page.

    Returns combined results with title, description, extracted content,
    and source URL for each page.
    """
    desired_candidates = max(max_pages * 4, 10)
    search_result = await web_search(query, max_results=desired_candidates)
    if "error" in search_result and not search_result.get("results"):
        return search_result

    results_to_fetch = search_result.get("results", [])[:desired_candidates]
    if not results_to_fetch:
        return {
            "query": query,
            "message": "Search returned no results to fetch.",
            "pages": [],
        }

    # Fetch pages concurrently
    async def _fetch_one(item: dict[str, str]) -> dict[str, Any]:
        page_url = item.get("url", "")
        if not page_url or page_url == "[blocked]":
            return {
                "url": page_url,
                "title": item.get("title", ""),
                "description": item.get("snippet", ""),
                "content": item.get("snippet", ""),
                "status": "skipped",
            }
        fetched = await fetch_url(page_url)
        if "error" in fetched:
            return {
                "url": page_url,
                "title": item.get("title", ""),
                "description": item.get("snippet", ""),
                "content": item.get("snippet", ""),
                "status": f"fetch_failed: {fetched['error']}",
            }
        return {
            "url": page_url,
            "title": fetched.get("title") or item.get("title", ""),
            "description": fetched.get("description") or item.get("snippet", ""),
            "content": fetched.get("content", "")[:_CONTENT_LIMIT],
            "status": "ok",
        }

    pages = await asyncio.gather(*[_fetch_one(r) for r in results_to_fetch])

    scored_pages = sorted(
        pages,
        key=_page_quality_score,
        reverse=True,
    )
    chosen_pages: list[dict[str, Any]] = []
    used_domains: set[str] = set()
    for page in scored_pages:
        domain = _result_domain(str(page.get("url") or ""))
        if domain and domain in used_domains and len(chosen_pages) < max_pages:
            continue
        chosen_pages.append(page)
        if domain:
            used_domains.add(domain)
        if len(chosen_pages) >= max_pages:
            break
    if len(chosen_pages) < max_pages:
        for page in scored_pages:
            if page in chosen_pages:
                continue
            chosen_pages.append(page)
            if len(chosen_pages) >= max_pages:
                break

    return {
        "query": query,
        "provider": search_result.get("provider", "unknown"),
        "pages": list(chosen_pages),
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="web_search",
        description="Search the web and extract page content using multiple providers",
        capabilities=[Capability.NETWORK_HTTP],
        tools=[
            ToolDefinition(
                name="web_search",
                description=(
                    "Search the web for information. Uses the best available "
                    "provider (Brave > Google > SearXNG > DuckDuckGo) with "
                    "automatic fallback."
                ),
                parameters=[
                    ToolParameter(
                        name="query",
                        type="string",
                        description="Search query",
                    ),
                    ToolParameter(
                        name="max_results",
                        type="integer",
                        description="Maximum results to return (default 5)",
                        required=False,
                        default=5,
                    ),
                ],
                handler=web_search,
            ),
            ToolDefinition(
                name="fetch_url",
                description=(
                    "Fetch and extract readable content from a URL. Returns "
                    "structured output with title, meta description, and plain "
                    "text content. SSRF-protected."
                ),
                parameters=[
                    ToolParameter(
                        name="url",
                        type="string",
                        description="URL to fetch",
                    ),
                ],
                handler=fetch_url,
            ),
            ToolDefinition(
                name="browse_and_extract",
                description=(
                    "One-shot web research: searches for a query, fetches the "
                    "top results, and extracts readable content from each page. "
                    "Best tool for answering questions that need web data."
                ),
                parameters=[
                    ToolParameter(
                        name="query",
                        type="string",
                        description="Search query to research",
                    ),
                    ToolParameter(
                        name="max_pages",
                        type="integer",
                        description="Number of pages to fetch and extract (default 3, max 5)",
                        required=False,
                        default=3,
                    ),
                ],
                handler=browse_and_extract,
            ),
            ToolDefinition(
                name="detect_search_provider",
                description=(
                    "Check which search providers are configured and return "
                    "the active provider name and status of all providers."
                ),
                parameters=[],
                handler=_detect_search_provider_tool,
            ),
        ],
    )


async def _detect_search_provider_tool(**kwargs: Any) -> dict[str, Any]:
    """Async wrapper for detect_search_provider (tools must be async)."""
    return detect_search_provider()
