"""
Channel trust and pairing primitives.

Implements a simple trust model:
- open: always trusted
- pair: explicit /pair binds the current route
- bound: only pre-existing bindings are trusted
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from neuralclaw.channels.protocol import ChannelIdentity, ChannelMessage
from neuralclaw.config import CHANNEL_BINDINGS_FILE, ChannelConfig, ensure_dirs


PAIR_COMMAND = "/pair"


@dataclass
class ChannelBinding:
    platform: str
    route_key: str
    user_id: str
    chat_id: str
    workspace_id: str = ""
    thread_id: str = ""
    is_private: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass
class TrustDecision:
    status: str
    identity: ChannelIdentity
    response: str | None = None

    @property
    def trusted(self) -> bool:
        return self.status == "trusted"


class BindingStore:
    """Lightweight JSON-backed binding store."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or CHANNEL_BINDINGS_FILE
        self._bindings: dict[str, ChannelBinding] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        ensure_dirs()
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for item in data.get("bindings", []):
                    binding = ChannelBinding(**item)
                    self._bindings[binding.route_key] = binding
            except Exception:
                self._bindings = {}
        self._loaded = True

    def _save(self) -> None:
        ensure_dirs()
        payload = {"bindings": [asdict(b) for b in self._bindings.values()]}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get(self, route_key: str) -> ChannelBinding | None:
        self._load()
        return self._bindings.get(route_key)

    def bind(self, identity: ChannelIdentity) -> ChannelBinding:
        self._load()
        binding = ChannelBinding(
            platform=identity.platform,
            route_key=identity.route_key,
            user_id=identity.user_id,
            chat_id=identity.chat_id,
            workspace_id=identity.workspace_id,
            thread_id=identity.thread_id,
            is_private=identity.is_private,
        )
        self._bindings[identity.route_key] = binding
        self._save()
        return binding

    def list_bindings(self) -> list[ChannelBinding]:
        self._load()
        return list(self._bindings.values())


def identity_from_message(msg: ChannelMessage) -> ChannelIdentity:
    """Build a normalized identity from a channel message."""
    meta = msg.metadata or {}
    platform = str(meta.get("platform") or meta.get("source") or "unknown")
    workspace_id = str(meta.get("workspace_id") or meta.get("guild_id") or meta.get("team_id") or "")
    thread_id = str(meta.get("thread_id") or meta.get("thread_ts") or "")
    is_private = bool(meta.get("is_private", False))
    is_shared = bool(meta.get("is_shared", not is_private))
    return ChannelIdentity(
        platform=platform,
        user_id=msg.author_id,
        chat_id=msg.channel_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        is_private=is_private,
        is_shared=is_shared,
    )


def default_trust_mode(identity: ChannelIdentity) -> str:
    if identity.platform in {"web", "cli", "dashboard"}:
        return "open"
    if identity.is_private:
        return "pair"
    return "bound"


class ChannelTrustController:
    """Evaluate channel trust based on config and stored bindings."""

    def __init__(self, store: BindingStore | None = None) -> None:
        self._store = store or BindingStore()

    def evaluate(self, channel_config: ChannelConfig | None, msg: ChannelMessage) -> TrustDecision:
        identity = identity_from_message(msg)
        trust_mode = (channel_config.trust_mode if channel_config and channel_config.trust_mode else "").strip().lower()
        if not trust_mode:
            trust_mode = default_trust_mode(identity)

        if trust_mode == "open":
            return TrustDecision("trusted", identity)

        binding = self._store.get(identity.route_key)
        if binding:
            return TrustDecision("trusted", identity)

        content = (msg.content or "").strip()
        if trust_mode == "pair":
            if content.lower() == PAIR_COMMAND:
                self._store.bind(identity)
                return TrustDecision(
                    "paired",
                    identity,
                    response=f"Paired this {identity.platform} route. Future messages here are trusted.",
                )
            challenge = secrets.token_hex(3)
            return TrustDecision(
                "unpaired",
                identity,
                response=(
                    f"This route is not paired yet. Send `{PAIR_COMMAND}` here to trust it."
                    if identity.is_private
                    else f"This shared route is not bound yet. Send `{PAIR_COMMAND}` here to bind it. Ref {challenge}."
                ),
            )

        if trust_mode == "bound":
            if content.lower() == PAIR_COMMAND:
                self._store.bind(identity)
                return TrustDecision(
                    "paired",
                    identity,
                    response=f"Bound this {identity.platform} route. Future messages here are trusted.",
                )
            return TrustDecision("denied", identity)

        return TrustDecision("trusted", identity)
