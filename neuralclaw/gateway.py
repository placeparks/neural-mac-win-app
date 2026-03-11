"""
Gateway — Main NeuralClaw entry point and orchestration engine.

Initializes all cortices, providers, channels, and the neural bus.
Orchestrates the full message lifecycle:

    Channel → Perception → Memory → Reasoning → Action → Response

This is the brain of NeuralClaw.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.bus.telemetry import Telemetry
from neuralclaw.channels.protocol import ChannelAdapter, ChannelMessage
from neuralclaw.channels.trust import ChannelTrustController
from neuralclaw.config import (
    NeuralClawConfig,
    ProviderConfig,
    ensure_dirs,
    get_api_key,
    load_config,
)
from neuralclaw.cortex.action.audit import AuditLogger
from neuralclaw.cortex.action.capabilities import CapabilityVerifier
from neuralclaw.cortex.action.idempotency import IdempotencyStore
from neuralclaw.cortex.action.policy import PolicyEngine
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.metabolism import MemoryMetabolism
from neuralclaw.cortex.memory.procedural import ProceduralMemory
from neuralclaw.cortex.memory.retrieval import MemoryRetriever
from neuralclaw.cortex.memory.semantic import SemanticMemory
from neuralclaw.cortex.perception.classifier import IntentClassifier
from neuralclaw.cortex.perception.intake import ChannelType, PerceptionIntake, Signal
from neuralclaw.cortex.perception.threat_screen import ThreatScreener
from neuralclaw.cortex.reasoning.deliberate import DeliberativeReasoner
from neuralclaw.cortex.reasoning.fast_path import FastPathReasoner
from neuralclaw.cortex.reasoning.reflective import ReflectiveReasoner
from neuralclaw.cortex.reasoning.meta import MetaCognitive
from neuralclaw.cortex.evolution.calibrator import BehavioralCalibrator
from neuralclaw.cortex.evolution.distiller import ExperienceDistiller
from neuralclaw.cortex.evolution.synthesizer import SkillSynthesizer
from neuralclaw.providers.router import LLMProvider, ProviderRouter
from neuralclaw.skills.registry import SkillRegistry
from neuralclaw.swarm.delegation import DelegationChain, DelegationPolicy
from neuralclaw.swarm.consensus import ConsensusProtocol
from neuralclaw.swarm.mesh import AgentMesh
from neuralclaw.swarm.federation import FederationProtocol, FederationBridge
from neuralclaw.swarm.spawn import AgentSpawner


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------

class NeuralClawGateway:
    """
    Main orchestration engine — the 'brain' of NeuralClaw.

    Wires together all cortices, providers, and channels into a
    cohesive cognitive pipeline.
    """

    def __init__(self, config: NeuralClawConfig | None = None, provider_override: str | None = None) -> None:
        self._config = config or load_config()
        self._running = False
        self._provider_override = provider_override

        # Neural bus
        self._bus = NeuralBus()
        self._telemetry = Telemetry(
            log_to_stdout=self._config.telemetry_stdout,
        )
        self._bus.subscribe_all(self._telemetry.handle_event)

        # Perception cortex
        self._intake = PerceptionIntake(self._bus)
        self._classifier = IntentClassifier(self._bus)
        self._threat_screener = ThreatScreener(
            bus=self._bus,
            threat_threshold=self._config.security.threat_threshold,
            block_threshold=self._config.security.block_threshold,
        )

        # Memory cortex
        self._episodic = EpisodicMemory(self._config.memory.db_path)
        self._semantic = SemanticMemory(self._config.memory.db_path)
        self._retriever = MemoryRetriever(
            self._episodic, self._semantic, self._bus,
            max_episodes=self._config.memory.max_episodic_results,
            max_facts=self._config.memory.max_semantic_results,
        )

        # Reasoning cortex
        self._fast_path = FastPathReasoner(self._bus, self._config.name)
        self._policy = PolicyEngine(self._config.policy)
        self._idempotency = IdempotencyStore(self._config.memory.db_path)
        self._deliberate = DeliberativeReasoner(
            self._bus,
            self._config.persona,
            policy=self._policy,
            idempotency=self._idempotency,
        )
        self._reflective = ReflectiveReasoner(self._bus, self._deliberate)

        # Action cortex
        self._capability_verifier = CapabilityVerifier(
            bus=self._bus,
            allow_shell=self._config.security.allow_shell_execution,
        )
        self._audit = AuditLogger()

        # Phase 2: Procedural memory + metabolism
        feat = self._config.features
        self._procedural = ProceduralMemory(self._config.memory.db_path, self._bus) if feat.procedural_memory else None
        self._metabolism = MemoryMetabolism(
            self._episodic, self._semantic if feat.semantic_memory else None, self._bus,
        ) if feat.evolution else None

        # Phase 2: Evolution cortex
        self._calibrator = BehavioralCalibrator(bus=self._bus) if feat.evolution else None
        self._distiller = ExperienceDistiller(
            self._episodic, self._semantic, self._procedural, self._bus,
        ) if feat.evolution else None
        self._synthesizer = SkillSynthesizer(bus=self._bus) if feat.evolution else None

        # Phase 3: Meta-cognitive reasoning
        self._meta_cognitive = MetaCognitive(bus=self._bus) if feat.evolution else None

        # Phase 3: Swarm
        self._delegation = DelegationChain(bus=self._bus) if feat.swarm else None
        self._consensus = ConsensusProtocol(self._delegation, bus=self._bus) if feat.swarm else None
        self._mesh = AgentMesh(bus=self._bus) if feat.swarm else None

        # Phase 4: Spawner + Federation
        self._spawner: AgentSpawner | None = None
        self._federation: FederationProtocol | None = None
        self._federation_bridge: FederationBridge | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

        if feat.swarm and self._mesh and self._delegation:
            self._spawner = AgentSpawner(self._mesh, self._delegation, self._bus)

            fed_cfg = self._config.federation
            if fed_cfg.enabled:
                self._federation = FederationProtocol(
                    node_name=fed_cfg.node_name or self._config.name,
                    bus=self._bus,
                    port=fed_cfg.port,
                    bind_host=fed_cfg.bind_host,
                )
                self._federation_bridge = FederationBridge(
                    self._federation, self._spawner, self._bus,
                )

        # Phase 3: Dashboard (lazy import — aiohttp not loaded if disabled)
        if feat.dashboard:
            from neuralclaw.dashboard import Dashboard
            self._dashboard = Dashboard(port=self._config.dashboard_port)
        else:
            self._dashboard = None

        # Skills
        self._skills = SkillRegistry()

        # Channels
        self._channels: dict[str, ChannelAdapter] = {}
        self._trust = ChannelTrustController()

        # Conversation history (per channel_id)
        self._history: dict[str, list[dict[str, str]]] = {}

        # Provider
        self._provider: ProviderRouter | None = None

    async def initialize(self) -> None:
        """Initialize all subsystems."""
        ensure_dirs()

        # Initialize memory databases
        await self._episodic.initialize()
        await self._semantic.initialize()
        if self._procedural:
            await self._procedural.initialize()

        # Initialize idempotency store
        await self._idempotency.initialize()

        # Initialize evolution cortex
        if self._calibrator:
            await self._calibrator.initialize()

        # Load skills
        self._skills.load_builtins()

        # Configure built-in skills with policy roots (default-deny for FS)
        try:
            from neuralclaw.skills.builtins import file_ops as _file_ops

            _file_ops.set_allowed_roots(self._policy.get_allowed_roots())
        except Exception:
            pass

        # Configure github_repos skill with workspace settings
        try:
            from neuralclaw.skills.builtins import github_repos as _github_repos

            _github_repos.set_workspace_config(self._config.workspace)
        except Exception:
            pass

        # Configure repo_exec skill with workspace timeout
        try:
            from neuralclaw.skills.builtins import repo_exec as _repo_exec

            _repo_exec.set_max_exec_timeout(self._config.workspace.max_exec_timeout_seconds)
        except Exception:
            pass

        # Configure api_client skill with saved API configs
        try:
            from neuralclaw.skills.builtins import api_client as _api_client

            _api_client.set_api_configs(self._config.apis)
        except Exception:
            pass

        # Initialize LLM provider
        self._provider = self._build_provider()
        if self._provider:
            self._deliberate.set_provider(self._provider)
            if self._synthesizer:
                self._synthesizer.set_provider(self._provider)

        # Phase 3: Wire dashboard providers and actions
        if self._dashboard:
            self._dashboard.set_stats_provider(self._get_dashboard_stats)
            self._dashboard.set_agents_provider(self._get_dashboard_agents)
            self._dashboard.set_federation_provider(self._get_dashboard_federation)
            self._dashboard.set_memory_provider(self._get_dashboard_memory)
            self._dashboard.set_bus_provider(self._get_dashboard_bus)
            # Action callables
            if self._spawner:
                self._dashboard.set_spawn_action(self._dashboard_spawn)
                self._dashboard.set_despawn_action(self._dashboard_despawn)
            if self._federation:
                self._dashboard.set_join_federation_action(self._federation.join_federation)
                self._dashboard.set_message_peer_action(self._dashboard_message_peer)
            self._dashboard.set_send_message_action(self._dashboard_send_message)
            self._dashboard.set_clear_memory_action(self._dashboard_clear_memory)
            self._dashboard.set_features_provider(
                self._dashboard_get_features, self._dashboard_set_feature,
            )

        # Start neural bus
        await self._bus.start()
        # Start async telemetry flush loop (non-blocking file writes)
        self._telemetry.start_async_flush()

        # Start federation server and join seed nodes
        if self._federation:
            self._federation.set_message_handler(self._handle_federation_message)
            await self._federation.start()
            for seed in self._config.federation.seed_nodes:
                try:
                    joined = await self._federation.join_federation(seed)
                    if joined:
                        print(f"   Federation: joined peer {seed}")
                except Exception as e:
                    print(f"   Federation: failed to join {seed} ({e})")
            self._heartbeat_task = asyncio.create_task(
                self._federation_heartbeat_loop()
            )

        # Start federation bridge (sync federation nodes → mesh agents)
        if self._federation_bridge:
            await self._federation_bridge.start(
                sync_interval=self._config.federation.heartbeat_interval,
            )

    def _build_provider(self) -> ProviderRouter | None:
        """Build the provider router from config."""
        providers: list[LLMProvider] = []
        primary: LLMProvider | None = None

        cfg = self._config

        # Build all configured providers
        provider_builders = {
            "openai": self._build_openai,
            "anthropic": self._build_anthropic,
            "openrouter": self._build_openrouter,
            "local": self._build_local,
            "proxy": self._build_proxy,
            "chatgpt_app": self._build_chatgpt_app,
            "claude_app": self._build_claude_app,
            "chatgpt_token": self._build_chatgpt_token,
            "claude_token": self._build_claude_token,
        }

        if self._provider_override:
            builder = provider_builders.get(self._provider_override)
            if builder:
                p = builder(self._get_provider_config(self._provider_override))
                if p:
                    primary = p
        elif cfg.primary_provider:
            builder = provider_builders.get(cfg.primary_provider.name)
            if builder:
                p = builder(cfg.primary_provider)
                if p:
                    primary = p

        for fp in cfg.fallback_providers:
            builder = provider_builders.get(fp.name)
            if builder:
                p = builder(fp)
                if p:
                    providers.append(p)

        if not primary:
            # Try to find any available provider
            for name, builder in provider_builders.items():
                p = builder(self._get_provider_config(name))
                if p:
                    primary = p
                    break

        if not primary:
            return None

        return ProviderRouter(primary=primary, fallbacks=providers)

    def _build_openai(self, cfg: Any) -> LLMProvider | None:
        key = get_api_key("openai")
        if not key:
            return None
        from neuralclaw.providers.openai import OpenAIProvider
        return OpenAIProvider(api_key=key, model=cfg.model or "gpt-4o", base_url=cfg.base_url or "https://api.openai.com/v1")

    def _build_anthropic(self, cfg: Any) -> LLMProvider | None:
        key = get_api_key("anthropic")
        if not key:
            return None
        from neuralclaw.providers.anthropic import AnthropicProvider
        return AnthropicProvider(api_key=key, model=cfg.model or "claude-sonnet-4-20250514", base_url=cfg.base_url or "https://api.anthropic.com")

    def _build_openrouter(self, cfg: Any) -> LLMProvider | None:
        key = get_api_key("openrouter")
        if not key:
            return None
        from neuralclaw.providers.openrouter import OpenRouterProvider
        return OpenRouterProvider(
            api_key=key,
            model=cfg.model or "anthropic/claude-sonnet-4-20250514",
            base_url=cfg.base_url or "https://openrouter.ai/api/v1",
        )

    def _build_local(self, cfg: Any) -> LLMProvider | None:
        from neuralclaw.providers.local import LocalProvider
        return LocalProvider(
            model=cfg.model or "qwen3.5:2b",
            base_url=cfg.base_url or "http://localhost:11434/v1",
        )

    def _build_proxy(self, cfg: Any) -> LLMProvider | None:
        if not cfg.base_url:
            return None
        from neuralclaw.providers.proxy import ProxyProvider
        api_key = get_api_key("proxy") or ""
        return ProxyProvider(
            base_url=cfg.base_url,
            model=cfg.model or "gpt-4",
            api_key=api_key,
        )

    def _build_chatgpt_app(self, cfg: Any) -> LLMProvider | None:
        if not cfg.profile_dir:
            return None
        from neuralclaw.providers.app_session import ChatGPTAppProvider
        return ChatGPTAppProvider(
            model=cfg.model or "auto",
            profile_dir=cfg.profile_dir,
            site_url=cfg.site_url or "https://chatgpt.com/",
            headless=bool(getattr(cfg, "headless", False)),
            browser_channel=getattr(cfg, "browser_channel", ""),
        )

    def _build_claude_app(self, cfg: Any) -> LLMProvider | None:
        if not cfg.profile_dir:
            return None
        from neuralclaw.providers.app_session import ClaudeAppProvider
        return ClaudeAppProvider(
            model=cfg.model or "auto",
            profile_dir=cfg.profile_dir,
            site_url=cfg.site_url or "https://claude.ai/chats",
            headless=bool(getattr(cfg, "headless", False)),
            browser_channel=getattr(cfg, "browser_channel", ""),
        )

    def _build_chatgpt_token(self, cfg: Any) -> LLMProvider | None:
        from neuralclaw.session.auth import AuthManager
        auth = AuthManager("chatgpt")
        health = auth.health_check()
        if not health.get("has_token") or not health.get("valid"):
            return None
        from neuralclaw.providers.chatgpt_token import ChatGPTTokenProvider
        return ChatGPTTokenProvider(model=cfg.model or "auto")

    def _build_claude_token(self, cfg: Any) -> LLMProvider | None:
        from neuralclaw.session.auth import AuthManager
        auth = AuthManager("claude")
        health = auth.health_check()
        if not health.get("has_token") or not health.get("valid"):
            return None
        from neuralclaw.providers.claude_token import ClaudeTokenProvider
        return ClaudeTokenProvider(model=cfg.model or "auto")

    def _get_provider_config(self, name: str) -> ProviderConfig:
        raw = self._config._raw.get("providers", {}).get(name, {})
        return ProviderConfig(
            name=name,
            model=raw.get("model", ""),
            base_url=raw.get("base_url", ""),
            api_key=get_api_key(name),
            profile_dir=raw.get("profile_dir", ""),
            headless=bool(raw.get("headless", False)),
            browser_channel=raw.get("browser_channel", ""),
            site_url=raw.get("site_url", ""),
            auth_method=raw.get("auth_method", ""),
        )

    # -- Channel management -------------------------------------------------

    def build_channels(self, web_port: int = 8081) -> None:
        """Build and register all configured channel adapters."""
        from neuralclaw.config import ChannelConfig

        builders: dict[str, Any] = {
            "telegram": self._build_telegram_channel,
            "discord": self._build_discord_channel,
            "slack": self._build_slack_channel,
            "whatsapp": self._build_whatsapp_channel,
            "signal": self._build_signal_channel,
        }

        for ch_config in self._config.channels:
            if not ch_config.enabled or not ch_config.token:
                continue
            builder = builders.get(ch_config.name)
            if builder:
                try:
                    adapter = builder(ch_config)
                    if adapter:
                        self.add_channel(adapter)
                except Exception as e:
                    print(f"[Gateway] Failed to build channel '{ch_config.name}': {e}")

        # Web chat always available
        from neuralclaw.channels.web import WebChatAdapter
        self.add_channel(WebChatAdapter(port=web_port))

    def _build_telegram_channel(self, cfg: Any) -> ChannelAdapter | None:
        from neuralclaw.channels.telegram import TelegramAdapter
        return TelegramAdapter(cfg.token)

    def _build_discord_channel(self, cfg: Any) -> ChannelAdapter | None:
        from neuralclaw.channels.discord_adapter import DiscordAdapter
        return DiscordAdapter(cfg.token)

    def _build_slack_channel(self, cfg: Any) -> ChannelAdapter | None:
        app_token = cfg.extra.get("slack_app")
        if not app_token:
            return None
        from neuralclaw.channels.slack import SlackAdapter
        return SlackAdapter(cfg.token, app_token)

    def _build_whatsapp_channel(self, cfg: Any) -> ChannelAdapter | None:
        import logging as _log
        _logger = _log.getLogger("neuralclaw.gateway")

        def _log_qr(data: str) -> None:
            _logger.info("[WhatsApp] QR code received — pair via neuralclaw channels connect whatsapp")

        from neuralclaw.channels.whatsapp_baileys import BaileysWhatsAppAdapter
        return BaileysWhatsAppAdapter(auth_dir=cfg.token, on_qr=_log_qr)

    def _build_signal_channel(self, cfg: Any) -> ChannelAdapter | None:
        from neuralclaw.channels.signal_adapter import SignalAdapter
        return SignalAdapter(cfg.token)

    def add_channel(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter."""
        adapter.on_message(self._on_channel_message)
        self._channels[adapter.name] = adapter

    async def _start_channels(self) -> None:
        """Start all registered channel adapters."""
        for name, adapter in self._channels.items():
            try:
                await adapter.start()
                print(f"[Gateway] Channel registered: {name}")
            except Exception as e:
                print(f"[Gateway] Channel '{name}' start error: {e} (will retry in background)")

    async def _stop_channels(self) -> None:
        """Stop all channel adapters."""
        for name, adapter in self._channels.items():
            try:
                await adapter.stop()
            except Exception:
                pass

    # -- Message lifecycle --------------------------------------------------

    async def _on_channel_message(self, msg: ChannelMessage) -> None:
        """Handle an incoming message from any channel."""
        try:
            response = await self.process_message(
                content=msg.content,
                author_id=msg.author_id,
                author_name=msg.author_name,
                channel_id=msg.channel_id,
                channel_type_name=self._get_channel_type(msg),
                message_metadata=msg.metadata,
                raw_message=msg.raw,
            )

            if not response:
                return

            # Route response back to the correct adapter
            source_channel = self._get_source_adapter(msg)
            if source_channel and source_channel in self._channels:
                try:
                    await self._channels[source_channel].send(
                        msg.channel_id,
                        response,
                        **self._build_reply_kwargs(msg),
                    )
                except Exception as e:
                    print(f"[Gateway] Failed to send via {source_channel}: {e}")
            else:
                # Fallback: try all channels
                for name, adapter in self._channels.items():
                    try:
                        await adapter.send(msg.channel_id, response, **self._build_reply_kwargs(msg))
                        break
                    except Exception:
                        continue

        except Exception as e:
            print(f"[Gateway] Error processing message: {e}")

    async def process_message(
        self,
        content: str,
        author_id: str = "user",
        author_name: str = "User",
        channel_id: str = "cli",
        channel_type_name: str = "CLI",
        message_metadata: dict[str, Any] | None = None,
        raw_message: Any = None,
    ) -> str:
        """
        Process a message through the full cognitive pipeline.

        Channel → Perception → Memory → Reasoning → Action → Response
        """
        # 0. TRUST: gate inbound routes before any cognitive work
        if message_metadata is not None:
            trust_msg = ChannelMessage(
                content=content,
                author_id=author_id,
                author_name=author_name,
                channel_id=channel_id,
                raw=raw_message,
                metadata=message_metadata,
            )
            trust_cfg = self._get_channel_config(trust_msg)
            decision = self._trust.evaluate(trust_cfg, trust_msg)
            if decision.status == "denied":
                return ""
            if decision.status in {"unpaired", "paired"}:
                return decision.response or ""

        # 1. PERCEPTION: Intake
        channel_type = ChannelType[channel_type_name.upper()] if channel_type_name.upper() in ChannelType.__members__ else ChannelType.CLI
        signal = await self._intake.process(
            content=content,
            author_id=author_id,
            author_name=author_name,
            channel_type=channel_type,
            channel_id=channel_id,
        )

        # 2. PERCEPTION: Threat screening
        threat = await self._threat_screener.screen(signal)
        if threat.blocked:
            return "⚠️ I've detected a potentially harmful request and blocked it for safety. If this was a mistake, try rephrasing."

        # 3. REASONING: Try fast path before any DB/memory ops (zero-cost early exit)
        fast_result = await self._fast_path.try_fast_path(signal, memory_ctx=None)
        if fast_result:
            await self._store_interaction(content, fast_result.content, author_name)
            try:
                await self._post_process(content, fast_result.content, author_name)
            except Exception:
                pass
            return fast_result.content

        # 4. PERCEPTION: Intent classification (only for non-trivial messages)
        intent_result = await self._classifier.classify(signal)

        # 5. MEMORY: Retrieve context (skipped for fast-path messages above)
        memory_ctx = await self._retriever.retrieve(content)

        # 6. REASONING: Check for procedural memory match (if enabled)
        procedures = await self._procedural.find_matching(content) if self._procedural else []

        # 7. REASONING: Route to reflective or deliberative path
        tools = self._skills.get_all_tools() if self._skills.tool_count > 0 else None
        history = self._history.get(channel_id, [])

        # Add calibrator persona modifiers
        persona_mods = self._calibrator.preferences.to_persona_modifiers() if self._calibrator else ""

        use_reflective = (
            self._config.features.reflective_reasoning
            and self._reflective.should_reflect(signal, memory_ctx)
        )
        if use_reflective:
            envelope = await self._reflective.reflect(
                signal=signal,
                memory_ctx=memory_ctx,
                tools=tools,
                conversation_history=history[-20:],
            )
        else:
            envelope = await self._deliberate.reason(
                signal=signal,
                memory_ctx=memory_ctx,
                tools=tools,
                conversation_history=history[-20:],
            )

        # 8. RESPONSE: Store in memory and return
        await self._store_interaction(content, envelope.response, author_name)

        # Update conversation history
        if channel_id not in self._history:
            self._history[channel_id] = []
        self._history[channel_id].append({"role": "user", "content": content})
        self._history[channel_id].append({"role": "assistant", "content": envelope.response})

        # Trim history to 20 (matches what's passed to LLM — no point storing more)
        if len(self._history[channel_id]) > 20:
            self._history[channel_id] = self._history[channel_id][-20:]

        # Post-process (metabolism, distiller, calibrator) — never block response
        try:
            await self._post_process(content, envelope.response, author_name)
        except Exception as e:
            print(f"[Gateway] Post-process error (non-fatal): {e}")

        # Publish response event — never block response
        try:
            await self._bus.publish(
                EventType.RESPONSE_READY,
                {"content": envelope.response[:200], "confidence": envelope.confidence},
                source="gateway",
            )
        except Exception:
            pass

        return envelope.response

    async def _store_interaction(self, user_msg: str, agent_msg: str, author: str) -> None:
        """Store the interaction in episodic memory."""
        try:
            await self._episodic.store(
                content=f"{author}: {user_msg}",
                source="conversation",
                author=author,
                importance=0.5,
            )
            await self._episodic.store(
                content=f"NeuralClaw: {agent_msg}",
                source="conversation",
                author="NeuralClaw",
                importance=0.4,
            )
        except Exception as e:
            await self._bus.publish(
                EventType.ERROR,
                {"error": f"Memory store failed: {e}", "component": "gateway"},
                source="gateway",
            )

    def _get_channel_type(self, msg: ChannelMessage) -> str:
        """Get the channel type name from a ChannelMessage."""
        meta = msg.metadata or {}
        platform = str(meta.get("platform") or meta.get("source") or "")
        if platform:
            mapping = {
                "telegram": "TELEGRAM",
                "discord": "DISCORD",
                "slack": "SLACK",
                "whatsapp": "WHATSAPP",
                "signal": "SIGNAL",
                "web": "CLI",
            }
            return mapping.get(platform, "CLI")
        if msg.raw:
            raw_module = type(msg.raw).__module__
            if "telegram" in raw_module:
                return "TELEGRAM"
            if "discord" in raw_module:
                return "DISCORD"
            if "slack" in raw_module:
                return "SLACK"
        # Check metadata
        if "whatsapp" in str(meta.get("source", "")):
            return "WHATSAPP"
        if "signal" in str(meta.get("source", "")):
            return "SIGNAL"
        if "web" in str(meta.get("source", "")):
            return "CLI"  # Web chat uses CLI channel type
        return "CLI"

    def _get_source_adapter(self, msg: ChannelMessage) -> str | None:
        """Identify which adapter originated this message."""
        meta = msg.metadata or {}
        platform = str(meta.get("platform") or meta.get("source") or "")
        if platform:
            return platform
        if msg.raw:
            raw_module = type(msg.raw).__module__
            if "telegram" in raw_module:
                return "telegram"
            if "discord" in raw_module:
                return "discord"
            if "slack" in raw_module:
                return "slack"
        source = str(meta.get("source", ""))
        if "whatsapp" in source:
            return "whatsapp"
        if "signal" in source:
            return "signal"
        if "web" in source:
            return "web"
        return None

    def _get_channel_config(self, msg: ChannelMessage) -> Any:
        meta = msg.metadata or {}
        platform = str(meta.get("platform") or meta.get("source") or "").lower()
        if not platform:
            return None
        for ch in self._config.channels:
            if ch.name == platform:
                return ch
        return None

    def _build_reply_kwargs(self, msg: ChannelMessage) -> dict[str, Any]:
        meta = msg.metadata or {}
        kwargs: dict[str, Any] = {}
        thread_ts = meta.get("thread_id") or meta.get("thread_ts")
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        return kwargs

    async def _post_process(self, user_msg: str, agent_msg: str, author: str) -> None:
        """Post-processing: tick metabolism/distiller, run calibration."""
        if self._metabolism:
            self._metabolism.tick()
        if self._distiller:
            self._distiller.tick()

        if self._calibrator:
            await self._calibrator.process_implicit_signal(
                user_msg_length=len(user_msg),
                agent_msg_length=len(agent_msg),
            )

        # Run metabolism cycle if due
        if self._metabolism and self._metabolism.should_run:
            try:
                await self._metabolism.run_cycle()
            except Exception as e:
                await self._bus.publish(
                    EventType.ERROR,
                    {"error": f"Metabolism cycle failed: {e}", "component": "metabolism"},
                    source="gateway",
                )

        # Run distillation if due
        if self._distiller and self._distiller.should_distill:
            try:
                await self._distiller.distill()
            except Exception as e:
                await self._bus.publish(
                    EventType.ERROR,
                    {"error": f"Distillation failed: {e}", "component": "distiller"},
                    source="gateway",
                )

        # Phase 3: Meta-cognitive tick + analysis
        if self._meta_cognitive:
            self._meta_cognitive.record_interaction(
                category="conversation",
                success=True,
                confidence=0.7,
            )
            if self._meta_cognitive.should_analyze:
                try:
                    report = await self._meta_cognitive.analyze()
                    if self._dashboard:
                        self._dashboard.push_trace(
                            "reasoning",
                            f"Meta-cognitive analysis: {report.overall_success_rate:.0%} success, "
                            f"{len(report.capability_gaps)} gaps detected",
                        )
                except Exception as e:
                    await self._bus.publish(
                        EventType.ERROR,
                        {"error": f"Meta-cognitive analysis failed: {e}", "component": "meta"},
                        source="gateway",
                    )

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Start the gateway (all channels + bus)."""
        self._running = True
        await self.initialize()
        await self._start_channels()

        print(f"\n🧠 {self._config.name} Gateway is running (Phase 3: Swarm)")
        print(f"   Provider: {self._provider.name if self._provider else 'NONE'}")
        print(f"   Skills: {self._skills.count} ({self._skills.tool_count} tools)")
        print(f"   Channels: {list(self._channels.keys()) or ['none']}")
        feat = self._config.features
        print(f"   Evolution: {'enabled' if feat.evolution else 'disabled (lite)'}")
        print(f"   Swarm: {'enabled' if feat.swarm else 'disabled (lite)'}")
        print(f"   Dashboard: {'enabled' if feat.dashboard else 'disabled (lite)'}")
        if self._federation:
            fed_cfg = self._config.federation
            seeds = fed_cfg.seed_nodes or ["none"]
            print(f"   Federation: port {fed_cfg.port}, seeds: {seeds}")
        else:
            print(f"   Federation: disabled")
        if self._spawner:
            print(f"   Spawner: {self._spawner.count} agents")

        # Start dashboard in background
        if self._dashboard:
            try:
                await self._dashboard.start()
            except Exception as e:
                print(f"   Dashboard: failed to start ({e})")
        print()

    async def stop(self) -> None:
        """Gracefully stop the gateway."""
        self._running = False
        await self._stop_channels()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        if self._federation_bridge:
            await self._federation_bridge.stop()
        if self._federation:
            await self._federation.stop()
        if self._dashboard:
            await self._dashboard.stop()
        await self._telemetry.stop()
        await self._bus.stop()
        await self._episodic.close()
        await self._semantic.close()
        if self._procedural:
            await self._procedural.close()
        if self._calibrator:
            await self._calibrator.close()
        await self._idempotency.close()
        print("\n🧠 NeuralClaw Gateway stopped.")

    def _get_dashboard_stats(self) -> dict[str, Any]:
        """Provide stats for the dashboard."""
        return {
            "provider": self._provider.name if self._provider else "none",
            "interactions": sum(
                r.total for r in self._meta_cognitive._performance.values()
            ) if self._meta_cognitive else 0,
            "success_rate": self._meta_cognitive.get_performance_summary().get(
                "success_rate", 1.0
            ) if self._meta_cognitive else 1.0,
            "skills": self._skills.count,
            "channels": ", ".join(self._channels.keys()) or "none",
        }

    def _get_dashboard_agents(self) -> list[dict[str, Any]]:
        """Provide swarm agent list for the dashboard.

        Federation nodes are already synced to the mesh by FederationBridge
        as ``fed:<name>`` agents, so we don't append them a second time.
        """
        return self._mesh.get_mesh_status().get("agents", []) if self._mesh else []

    def _get_dashboard_federation(self) -> dict[str, Any]:
        """Provide federation status for the dashboard."""
        if not self._federation:
            return {"total_nodes": 0, "online_nodes": 0, "nodes": []}
        return self._federation.registry.get_status()

    async def _get_dashboard_memory(self) -> dict[str, Any]:
        """Provide memory health stats for the dashboard."""
        episodic_count = await self._episodic.count() if self._episodic else 0
        semantic_count = await self._semantic.count() if self._semantic else 0
        procedural_count = await self._procedural.count() if self._procedural else 0
        return {
            "episodic_count": episodic_count,
            "semantic_count": semantic_count,
            "procedural_count": procedural_count,
        }

    def _get_dashboard_bus(self) -> list[dict[str, Any]]:
        """Provide recent bus events for the dashboard."""
        events = self._bus.get_event_log(limit=50)
        return [
            {
                "type": e.type.name,
                "source": e.source,
                "timestamp": e.timestamp,
                "data_preview": str(e.data)[:120],
            }
            for e in events
        ]

    # -- Dashboard action helpers ---------------------------------------------

    def _dashboard_spawn(
        self, name: str, desc: str, caps: list[str], endpoint: str,
    ) -> dict[str, Any]:
        """Spawn a remote agent from a dashboard request."""
        if not self._spawner:
            return {"ok": False, "error": "Swarm not enabled"}
        try:
            agent = self._spawner.spawn_remote(
                name=name, description=desc, capabilities=caps,
                endpoint=endpoint, source="manual",
            )
            return {"ok": True, "name": agent.name}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _dashboard_despawn(self, name: str) -> bool:
        """Despawn a named agent from a dashboard request."""
        if not self._spawner:
            return False
        return self._spawner.despawn(name)

    async def _dashboard_send_message(self, content: str) -> str:
        """Send a test message through the full cognitive pipeline."""
        return await self.process_message(
            content=content, author_id="dashboard",
            author_name="Dashboard", channel_id="dashboard",
            channel_type_name="CLI",
        )

    async def _dashboard_clear_memory(self) -> dict[str, Any]:
        """Clear all memory stores. Returns deleted counts."""
        episodic_deleted = await self._episodic.clear() if self._episodic else 0
        semantic_deleted = await self._semantic.clear() if self._semantic else 0
        procedural_deleted = await self._procedural.clear() if self._procedural else 0
        self._history.clear()
        return {
            "episodic_deleted": episodic_deleted,
            "semantic_deleted": semantic_deleted,
            "procedural_deleted": procedural_deleted,
        }

    def _dashboard_get_features(self) -> dict[str, Any]:
        """Return feature toggle states with live-effect metadata."""
        feat = self._config.features
        return {
            "reflective_reasoning": {"value": feat.reflective_reasoning, "live": True, "label": "Reflective Reasoning"},
            "swarm": {"value": feat.swarm, "live": False, "label": "Swarm Agents"},
            "evolution": {"value": feat.evolution, "live": False, "label": "Evolution Cortex"},
            "procedural_memory": {"value": feat.procedural_memory, "live": False, "label": "Procedural Memory"},
            "semantic_memory": {"value": feat.semantic_memory, "live": False, "label": "Semantic Memory"},
        }

    def _dashboard_set_feature(self, feature: str, value: bool) -> bool:
        """Toggle a feature flag. Only reflective_reasoning takes live effect."""
        feat = self._config.features
        if not hasattr(feat, feature):
            return False
        setattr(feat, feature, value)
        return True

    async def _handle_federation_message(self, content: str, from_name: str) -> str:
        """Process an incoming federation message through the cognitive pipeline."""
        return await self.process_message(
            content=content,
            author_id=f"fed:{from_name}",
            author_name=f"fed:{from_name}",
            channel_id=f"federation:{from_name}",
            channel_type_name="CLI",
        )

    async def _dashboard_message_peer(self, node_name: str, content: str) -> dict[str, Any]:
        """Send a message to a federation peer and return the response."""
        if not self._federation:
            return {"ok": False, "error": "Federation not available"}
        # Find the node by name
        for node in self._federation.registry.online_nodes:
            if node.name == node_name:
                reply = await self._federation.send_message(
                    target_node_id=node.node_id,
                    content=content,
                    message_type="task",
                )
                if reply:
                    return {"ok": True, "response": reply.content}
                return {"ok": False, "error": "No response from peer"}
        return {"ok": False, "error": f"Node '{node_name}' not found or offline"}

    @property
    def spawner(self) -> AgentSpawner | None:
        """Access the agent spawner for programmatic agent management."""
        return self._spawner

    async def _federation_heartbeat_loop(self) -> None:
        """Periodically send heartbeats to federation peers."""
        interval = self._config.federation.heartbeat_interval
        while self._running and self._federation:
            try:
                await self._federation.send_heartbeats()
            except Exception:
                pass
            await asyncio.sleep(interval)

    async def run_forever(self) -> None:
        """Run the gateway until interrupted."""
        await self.start()

        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            await stop_event.wait()
        except KeyboardInterrupt:
            pass
        finally:
            await self.stop()
