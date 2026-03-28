"""SkillScout — discovery layer that finds the best open-source option and
hands it to SkillForge automatically.

Usage:
    scout = SkillScout(forge=forge, provider=provider)
    result = await scout.scout("verify patient insurance eligibility")
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("neuralclaw.scout")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class SourceRegistry(str, Enum):
    PYPI = "pypi"
    GITHUB = "github"
    NPM = "npm"
    RAPIDAPI = "rapidapi"
    MCP_REGISTRY = "mcp_registry"
    CLAW_CLUB = "claw_club"


@dataclass
class ScoutCandidate:
    """A single discovery result before ranking."""
    name: str
    source: str  # URL or package name — passable to forge.steal()
    registry: SourceRegistry
    description: str = ""
    stars: int = 0
    last_updated: str = ""
    license: str = ""
    relevance_note: str = ""


@dataclass
class ScoutResult:
    """Outcome of a full scout → forge cycle."""
    success: bool = False
    query: str = ""
    candidates: list[ScoutCandidate] = field(default_factory=list)
    chosen: ScoutCandidate | None = None
    forge_result: Any = None  # ForgeResult from SkillForge
    skill_name: str = ""
    tools: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error: str = ""


# ---------------------------------------------------------------------------
# SkillScout
# ---------------------------------------------------------------------------

class SkillScout:
    """Searches PyPI, GitHub, npm, RapidAPI, MCP registries, and Claw Club
    for the best match, then pipes it into ``SkillForge.steal()``.
    """

    def __init__(
        self,
        forge: Any,  # SkillForge
        provider: Any = None,  # LLM provider for ranking
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self._forge = forge
        self._provider = provider
        # Allow injecting a custom HTTP getter for testing
        self._http_get = http_get or self._default_http_get

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scout(
        self,
        query: str,
        activate: bool = True,
        skills_dir: str | None = None,
        registry_source: str = "user",
    ) -> ScoutResult:
        """End-to-end: search → rank → forge → return live skill."""
        start = time.monotonic()
        result = ScoutResult(query=query)

        try:
            # 1. Search all registries in parallel
            candidates = await self._search_all(query)
            result.candidates = candidates

            if not candidates:
                result.error = f"No candidates found for: {query}"
                result.elapsed_seconds = round(time.monotonic() - start, 2)
                return result

            # 2. Rank with LLM (or heuristic fallback)
            chosen = await self._rank_candidates(candidates, query)
            result.chosen = chosen

            # 3. Forge the winner
            logger.info(
                "SCOUT_FORGING: source=%s, registry=%s, query=%r",
                chosen.source, chosen.registry, query,
            )
            forge_result = await self._forge.steal(
                chosen.source,
                use_case=query,
                activate=activate,
                skills_dir=skills_dir,
                registry_source=registry_source,
            )
            result.forge_result = forge_result
            result.success = forge_result.success
            result.skill_name = forge_result.skill_name
            result.tools = (
                [t.name for t in forge_result.manifest.tools]
                if forge_result.manifest else []
            )
            if not forge_result.success:
                result.error = forge_result.error or "Forge failed"

        except Exception as exc:
            logger.exception("Scout failed for query=%r", query)
            result.error = str(exc)
        finally:
            result.elapsed_seconds = round(time.monotonic() - start, 2)

        return result

    # ------------------------------------------------------------------
    # Registry searches (all return list[ScoutCandidate])
    # ------------------------------------------------------------------

    async def _search_all(self, query: str) -> list[ScoutCandidate]:
        """Fan out to every registry concurrently."""
        tasks = [
            self._search_pypi(query),
            self._search_github(query),
            self._search_npm(query),
            self._search_rapidapi(query),
            self._search_mcp_registry(query),
        ]
        batches = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: list[ScoutCandidate] = []
        for batch in batches:
            if isinstance(batch, list):
                candidates.extend(batch)
            elif isinstance(batch, Exception):
                logger.warning("Registry search failed: %s", batch)
        return candidates

    async def _search_pypi(self, query: str) -> list[ScoutCandidate]:
        """Search PyPI by extracting keywords and trying exact package names."""
        # Extract 1-2 core keywords for package name guessing
        keywords = _extract_keywords(query)
        results: list[ScoutCandidate] = []

        for kw in keywords[:3]:
            try:
                data = await self._http_get(
                    f"https://pypi.org/pypi/{_quote(kw)}/json",
                    timeout=10,
                )
                if data and isinstance(data, dict) and "info" in data:
                    info = data["info"]
                    results.append(ScoutCandidate(
                        name=info.get("name", kw),
                        source=info.get("name", kw),
                        registry=SourceRegistry.PYPI,
                        description=info.get("summary", ""),
                        license=info.get("license", ""),
                        last_updated=info.get("version", ""),
                    ))
            except Exception as exc:
                logger.debug("PyPI lookup for '%s' failed: %s", kw, exc)

        return results

    async def _search_github(self, query: str) -> list[ScoutCandidate]:
        """Search GitHub repos via the public search API."""
        try:
            data = await self._http_get(
                f"https://api.github.com/search/repositories"
                f"?q={_quote(query)}+language:python&sort=stars&per_page=5",
                timeout=15,
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if not data or "items" not in data:
                return []
            results = []
            for item in data["items"][:5]:
                results.append(ScoutCandidate(
                    name=item.get("full_name", ""),
                    source=item.get("html_url", ""),
                    registry=SourceRegistry.GITHUB,
                    description=item.get("description", "") or "",
                    stars=item.get("stargazers_count", 0),
                    last_updated=item.get("updated_at", ""),
                    license=(item.get("license") or {}).get("spdx_id", ""),
                ))
            return results
        except Exception as exc:
            logger.debug("GitHub search failed: %s", exc)
            return []

    async def _search_npm(self, query: str) -> list[ScoutCandidate]:
        """Search npm registry for Node packages (MCP bridge candidates)."""
        try:
            data = await self._http_get(
                f"https://registry.npmjs.org/-/v1/search?text={_quote(query)}&size=5",
                timeout=10,
            )
            if not data or "objects" not in data:
                return []
            results = []
            for obj in data["objects"][:5]:
                pkg = obj.get("package", {})
                results.append(ScoutCandidate(
                    name=pkg.get("name", ""),
                    source=f"npm:{pkg.get('name', '')}",
                    registry=SourceRegistry.NPM,
                    description=pkg.get("description", "") or "",
                    last_updated=pkg.get("date", ""),
                    license=(pkg.get("links") or {}).get("repository", ""),
                ))
            return results
        except Exception as exc:
            logger.debug("npm search failed: %s", exc)
            return []

    async def _search_rapidapi(self, query: str) -> list[ScoutCandidate]:
        """Search RapidAPI / public API directories.

        RapidAPI doesn't have a free search API, so we use a curated
        approach via web search fallback.
        """
        # For now, return empty — can be expanded with API key
        return []

    async def _search_mcp_registry(self, query: str) -> list[ScoutCandidate]:
        """Search known MCP server registries."""
        try:
            data = await self._http_get(
                f"https://registry.modelcontextprotocol.io/search?q={_quote(query)}",
                timeout=10,
            )
            if not data or not isinstance(data, list):
                return []
            results = []
            for item in data[:5]:
                results.append(ScoutCandidate(
                    name=item.get("name", ""),
                    source=item.get("url", "") or item.get("source", ""),
                    registry=SourceRegistry.MCP_REGISTRY,
                    description=item.get("description", "") or "",
                ))
            return results
        except Exception as exc:
            logger.debug("MCP registry search failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    async def _rank_candidates(
        self, candidates: list[ScoutCandidate], query: str,
    ) -> ScoutCandidate:
        """Use LLM to pick the best candidate, with heuristic fallback."""
        if len(candidates) == 1:
            return candidates[0]

        # Try LLM ranking
        if self._provider:
            try:
                return await self._llm_rank(candidates, query)
            except Exception as exc:
                logger.warning("LLM ranking failed, using heuristic: %s", exc)

        # Heuristic fallback: prefer GitHub by stars, then PyPI, then others
        return self._heuristic_rank(candidates)

    async def _llm_rank(
        self, candidates: list[ScoutCandidate], query: str,
    ) -> ScoutCandidate:
        """Ask the LLM to pick the best match."""
        candidate_descriptions = "\n".join(
            f"{i+1}. [{c.registry.value}] {c.name} — {c.description} "
            f"(stars={c.stars}, license={c.license})"
            for i, c in enumerate(candidates)
        )
        prompt = (
            f"The user needs: {query}\n\n"
            f"Here are the candidates:\n{candidate_descriptions}\n\n"
            f"Pick the ONE best candidate for the user's use case. "
            f"Consider: relevance, maintenance, stars, license compatibility. "
            f"Reply with ONLY the number (e.g. '2')."
        )

        response = await self._provider.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.0,
        )
        text = response.content or ""
        # Extract number
        match = re.search(r"(\d+)", text.strip())
        if match:
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(candidates):
                candidates[idx].relevance_note = "LLM-selected best match"
                return candidates[idx]

        return self._heuristic_rank(candidates)

    def _heuristic_rank(self, candidates: list[ScoutCandidate]) -> ScoutCandidate:
        """Score candidates by stars, registry priority, and recency."""
        registry_weight = {
            SourceRegistry.GITHUB: 3,
            SourceRegistry.PYPI: 2,
            SourceRegistry.MCP_REGISTRY: 2,
            SourceRegistry.NPM: 1,
            SourceRegistry.RAPIDAPI: 1,
            SourceRegistry.CLAW_CLUB: 4,  # prefer our own marketplace
        }

        def score(c: ScoutCandidate) -> float:
            s = registry_weight.get(c.registry, 0) * 100
            s += min(c.stars, 10000) / 10  # cap star influence
            if c.license and c.license.lower() in ("mit", "apache-2.0", "bsd-3-clause"):
                s += 50  # prefer permissive licenses
            return s

        ranked = sorted(candidates, key=score, reverse=True)
        ranked[0].relevance_note = "Heuristic best match"
        return ranked[0]

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    @staticmethod
    async def _default_http_get(
        url: str,
        timeout: int = 15,
        headers: dict[str, str] | None = None,
        raw: bool = False,
    ) -> Any:
        """Minimal async HTTP GET using httpx or urllib."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, headers=headers or {})
                if resp.status_code != 200:
                    return None
                if raw:
                    return resp.text
                return resp.json()
        except ImportError:
            pass

        # Fallback to urllib (sync, run in executor)
        import urllib.request
        loop = asyncio.get_running_loop()

        def _fetch() -> Any:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read().decode()
                if raw:
                    return data
                return json.loads(data)

        return await loop.run_in_executor(None, _fetch)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quote(text: str) -> str:
    """URL-encode a query string."""
    import urllib.parse
    return urllib.parse.quote_plus(text)


# Stop words to strip when extracting keywords for package name guessing
_STOP_WORDS = frozenset({
    "a", "an", "the", "to", "for", "of", "in", "on", "and", "or", "is",
    "it", "that", "this", "with", "from", "by", "as", "at", "be", "my",
    "i", "me", "we", "need", "want", "find", "get", "best", "good",
    "library", "package", "tool", "module", "something", "python",
    "like", "such", "using", "use", "can", "do", "make", "create",
})


def _extract_keywords(query: str) -> list[str]:
    """Extract meaningful keywords from a natural-language query.

    Returns individual words and hyphenated bigrams suitable for
    PyPI package name guessing.
    """
    words = re.sub(r"[^a-zA-Z0-9\s-]", "", query.lower()).split()
    keywords = [w for w in words if w not in _STOP_WORDS and len(w) > 2]

    # Build candidate package names: single words + adjacent pairs
    candidates: list[str] = []
    for w in keywords:
        candidates.append(w)
    for i in range(len(keywords) - 1):
        candidates.append(f"{keywords[i]}-{keywords[i+1]}")

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result
