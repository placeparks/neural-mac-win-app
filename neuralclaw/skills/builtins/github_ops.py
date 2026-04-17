"""
Built-in Skill: GitHub Ops - Issues, PRs, CI, and comments.

This gives the agent a practical GitHub-native workflow without requiring a
full repo clone for every operation. Authentication is resolved from either a
saved ``api_client`` config named ``github`` or a ``github_token`` secret.
"""

from __future__ import annotations

import json
from typing import Any

import aiohttp

from neuralclaw.config import _get_secret
from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

_api_configs: dict[str, dict[str, Any]] = {}


def set_api_configs(configs: dict[str, dict[str, Any]]) -> None:
    global _api_configs
    _api_configs = dict(configs or {})


def _github_base_url() -> str:
    config = _api_configs.get("github", {})
    return str(config.get("base_url") or "https://api.github.com").rstrip("/")


def _github_token() -> str:
    return (
        _get_secret("api_github_key")
        or _get_secret("github_token")
        or ""
    )


def _auth_guard() -> dict[str, Any] | None:
    token = _github_token()
    if not token:
        return {
            "error": (
                "GitHub auth required. Save an API config named 'github' with api_client "
                "or set a github_token secret."
            )
        }
    return None


async def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    guard = _auth_guard()
    if guard:
        return guard
    token = _github_token()
    url = f"{_github_base_url()}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "NeuralClaw",
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.request(method, url, params=params, json=json_body, headers=headers) as resp:
                text = await resp.text()
                try:
                    payload = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    payload = {"raw": text}
                if resp.status >= 400:
                    message = payload.get("message") if isinstance(payload, dict) else str(payload)
                    return {"error": f"GitHub API error ({resp.status}): {message}"}
                return payload if isinstance(payload, dict | list) else {"data": payload}
    except Exception as exc:
        return {"error": str(exc)}


def _normalize_repo(repo: str) -> tuple[str, str] | tuple[None, None]:
    raw = str(repo or "").strip().strip("/")
    if raw.count("/") != 1:
        return None, None
    owner, name = raw.split("/", 1)
    if not owner or not name:
        return None, None
    return owner, name


async def github_list_pull_requests(
    repo: str,
    state: str = "open",
    limit: int = 10,
    **_: Any,
) -> dict[str, Any]:
    owner, name = _normalize_repo(repo)
    if not owner:
        return {"error": "repo must be in owner/name form"}
    payload = await _request(
        "GET",
        f"/repos/{owner}/{name}/pulls",
        params={"state": state, "per_page": max(1, min(int(limit or 10), 25))},
    )
    if isinstance(payload, dict) and payload.get("error"):
        return payload
    pulls = []
    for item in payload if isinstance(payload, list) else []:
        pulls.append({
            "number": item.get("number"),
            "title": item.get("title", ""),
            "state": item.get("state", ""),
            "draft": bool(item.get("draft")),
            "author": (item.get("user") or {}).get("login", ""),
            "branch": {
                "head": ((item.get("head") or {}).get("ref", "")),
                "base": ((item.get("base") or {}).get("ref", "")),
            },
            "updated_at": item.get("updated_at"),
            "url": item.get("html_url", ""),
        })
    return {"repo": f"{owner}/{name}", "pull_requests": pulls, "count": len(pulls)}


async def github_get_pull_request(repo: str, number: int, **_: Any) -> dict[str, Any]:
    owner, name = _normalize_repo(repo)
    if not owner:
        return {"error": "repo must be in owner/name form"}
    pr = await _request("GET", f"/repos/{owner}/{name}/pulls/{int(number)}")
    if isinstance(pr, dict) and pr.get("error"):
        return pr
    head_sha = ((pr.get("head") or {}).get("sha", "")) if isinstance(pr, dict) else ""
    ci = await github_get_ci_status(f"{owner}/{name}", head_sha) if head_sha else {"checks": [], "state": "unknown"}
    reviews = await _request("GET", f"/repos/{owner}/{name}/pulls/{int(number)}/reviews")
    review_summary = []
    for review in reviews if isinstance(reviews, list) else []:
        review_summary.append({
            "user": (review.get("user") or {}).get("login", ""),
            "state": review.get("state", ""),
            "submitted_at": review.get("submitted_at"),
            "body": str(review.get("body") or "")[:300],
        })
    return {
        "repo": f"{owner}/{name}",
        "number": pr.get("number"),
        "title": pr.get("title", ""),
        "state": pr.get("state", ""),
        "draft": bool(pr.get("draft")),
        "mergeable": pr.get("mergeable"),
        "mergeable_state": pr.get("mergeable_state"),
        "author": (pr.get("user") or {}).get("login", ""),
        "body": pr.get("body", ""),
        "labels": [label.get("name", "") for label in pr.get("labels", [])],
        "review_summary": review_summary,
        "ci": ci,
        "url": pr.get("html_url", ""),
    }


async def github_list_issues(
    repo: str,
    state: str = "open",
    limit: int = 10,
    **_: Any,
) -> dict[str, Any]:
    owner, name = _normalize_repo(repo)
    if not owner:
        return {"error": "repo must be in owner/name form"}
    payload = await _request(
        "GET",
        f"/repos/{owner}/{name}/issues",
        params={"state": state, "per_page": max(1, min(int(limit or 10), 25))},
    )
    if isinstance(payload, dict) and payload.get("error"):
        return payload
    issues = []
    for item in payload if isinstance(payload, list) else []:
        if item.get("pull_request"):
            continue
        issues.append({
            "number": item.get("number"),
            "title": item.get("title", ""),
            "state": item.get("state", ""),
            "author": (item.get("user") or {}).get("login", ""),
            "assignees": [(assignee.get("login") or "") for assignee in item.get("assignees", [])],
            "labels": [label.get("name", "") for label in item.get("labels", [])],
            "updated_at": item.get("updated_at"),
            "url": item.get("html_url", ""),
        })
    return {"repo": f"{owner}/{name}", "issues": issues, "count": len(issues)}


async def github_get_issue(repo: str, number: int, **_: Any) -> dict[str, Any]:
    owner, name = _normalize_repo(repo)
    if not owner:
        return {"error": "repo must be in owner/name form"}
    issue = await _request("GET", f"/repos/{owner}/{name}/issues/{int(number)}")
    if isinstance(issue, dict) and issue.get("error"):
        return issue
    comments_payload = await _request(
        "GET",
        f"/repos/{owner}/{name}/issues/{int(number)}/comments",
        params={"per_page": 10},
    )
    comments = []
    for item in comments_payload if isinstance(comments_payload, list) else []:
        comments.append({
            "user": (item.get("user") or {}).get("login", ""),
            "created_at": item.get("created_at"),
            "body": str(item.get("body") or "")[:500],
        })
    return {
        "repo": f"{owner}/{name}",
        "number": issue.get("number"),
        "title": issue.get("title", ""),
        "state": issue.get("state", ""),
        "author": (issue.get("user") or {}).get("login", ""),
        "body": issue.get("body", ""),
        "labels": [label.get("name", "") for label in issue.get("labels", [])],
        "comments": comments,
        "url": issue.get("html_url", ""),
    }


async def github_get_ci_status(repo: str, ref: str, **_: Any) -> dict[str, Any]:
    owner, name = _normalize_repo(repo)
    if not owner:
        return {"error": "repo must be in owner/name form"}
    sha = str(ref or "").strip()
    if not sha:
        return {"error": "ref is required"}
    combined = await _request("GET", f"/repos/{owner}/{name}/commits/{sha}/status")
    if isinstance(combined, dict) and combined.get("error"):
        return combined
    checks_payload = await _request(
        "GET",
        f"/repos/{owner}/{name}/commits/{sha}/check-runs",
        params={"per_page": 20},
    )
    checks = []
    for item in (checks_payload.get("check_runs", []) if isinstance(checks_payload, dict) else []):
        checks.append({
            "name": item.get("name", ""),
            "status": item.get("status", ""),
            "conclusion": item.get("conclusion"),
            "started_at": item.get("started_at"),
            "completed_at": item.get("completed_at"),
            "url": item.get("html_url", ""),
        })
    return {
        "repo": f"{owner}/{name}",
        "ref": sha,
        "state": combined.get("state", "") if isinstance(combined, dict) else "",
        "statuses": combined.get("statuses", []) if isinstance(combined, dict) else [],
        "checks": checks,
    }


async def github_comment_issue(repo: str, number: int, body: str, **_: Any) -> dict[str, Any]:
    owner, name = _normalize_repo(repo)
    if not owner:
        return {"error": "repo must be in owner/name form"}
    text = str(body or "").strip()
    if not text:
        return {"error": "body is required"}
    payload = await _request(
        "POST",
        f"/repos/{owner}/{name}/issues/{int(number)}/comments",
        json_body={"body": text},
    )
    if isinstance(payload, dict) and payload.get("error"):
        return payload
    return {
        "ok": True,
        "repo": f"{owner}/{name}",
        "number": int(number),
        "comment_url": payload.get("html_url", "") if isinstance(payload, dict) else "",
        "id": payload.get("id") if isinstance(payload, dict) else None,
    }


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="github_ops",
        description="Inspect GitHub PRs, issues, CI checks, and post review comments.",
        capabilities=[Capability.NETWORK],
        tools=[
            ToolDefinition(
                name="github_list_pull_requests",
                description="List pull requests in a repository.",
                parameters=[
                    ToolParameter(name="repo", type="string", description="Repository in owner/name form"),
                    ToolParameter(name="state", type="string", description="Pull request state", required=False, default="open", enum=["open", "closed", "all"]),
                    ToolParameter(name="limit", type="integer", description="Maximum results", required=False, default=10),
                ],
                handler=github_list_pull_requests,
            ),
            ToolDefinition(
                name="github_get_pull_request",
                description="Get pull request details and CI summary.",
                parameters=[
                    ToolParameter(name="repo", type="string", description="Repository in owner/name form"),
                    ToolParameter(name="number", type="integer", description="Pull request number"),
                ],
                handler=github_get_pull_request,
            ),
            ToolDefinition(
                name="github_list_issues",
                description="List GitHub issues in a repository.",
                parameters=[
                    ToolParameter(name="repo", type="string", description="Repository in owner/name form"),
                    ToolParameter(name="state", type="string", description="Issue state", required=False, default="open", enum=["open", "closed", "all"]),
                    ToolParameter(name="limit", type="integer", description="Maximum results", required=False, default=10),
                ],
                handler=github_list_issues,
            ),
            ToolDefinition(
                name="github_get_issue",
                description="Get issue details and recent comments.",
                parameters=[
                    ToolParameter(name="repo", type="string", description="Repository in owner/name form"),
                    ToolParameter(name="number", type="integer", description="Issue number"),
                ],
                handler=github_get_issue,
            ),
            ToolDefinition(
                name="github_get_ci_status",
                description="Get CI and checks status for a commit, ref, or branch.",
                parameters=[
                    ToolParameter(name="repo", type="string", description="Repository in owner/name form"),
                    ToolParameter(name="ref", type="string", description="Commit SHA, branch, or ref"),
                ],
                handler=github_get_ci_status,
            ),
            ToolDefinition(
                name="github_comment_issue",
                description="Post a comment on an issue or pull request thread.",
                parameters=[
                    ToolParameter(name="repo", type="string", description="Repository in owner/name form"),
                    ToolParameter(name="number", type="integer", description="Issue or PR number"),
                    ToolParameter(name="body", type="string", description="Comment body"),
                ],
                handler=github_comment_issue,
            ),
        ],
    )
