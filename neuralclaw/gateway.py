"""
Gateway — Main NeuralClaw entry point and orchestration engine.

Initializes all cortices, providers, channels, and the neural bus.
Orchestrates the full message lifecycle:

    Channel → Perception → Memory → Reasoning → Action → Response

This is the brain of NeuralClaw.
"""

from __future__ import annotations

import asyncio
import base64
import gc
import hashlib
import io
import inspect
import json
import logging
import os
import re
import secrets
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import aiohttp

from neuralclaw import __version__
from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.bus.telemetry import Telemetry
from neuralclaw.channels.protocol import ChannelAdapter, ChannelMessage
from neuralclaw.channels.rate_limiter import (
    RateLimitConfig,
    SlidingWindowUserLimiter,
    TokenBucketRateLimiter,
)
from neuralclaw.channels.trust import ChannelTrustController
from neuralclaw.config import (
    NeuralClawConfig,
    ProviderConfig,
    _get_secret,
    _set_secret,
    clear_secret,
    delete_dashboard_auth_token,
    ensure_dirs,
    get_dashboard_auth_token,
    get_api_key,
    load_config,
    set_dashboard_auth_token,
    set_api_key,
    update_config,
)
from neuralclaw.cortex.action.audit import AuditLogger
from neuralclaw.cortex.action.capabilities import CapabilityVerifier
from neuralclaw.cortex.action.idempotency import IdempotencyStore
from neuralclaw.cortex.action.policy import PolicyEngine
from neuralclaw.cortex.adaptive import AdaptiveControlPlane
from neuralclaw.cortex.reasoning.checkpoint import CheckpointStore
from neuralclaw.cortex.memory.db import DBPool
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.identity import UserIdentityStore
from neuralclaw.cortex.memory.retrieval import MemoryRetriever
from neuralclaw.cortex.memory.semantic import SemanticMemory
from neuralclaw.cortex.memory.vector import VectorMemory
from neuralclaw.cortex.perception.classifier import IntentClassifier
from neuralclaw.cortex.perception.intake import ChannelType, PerceptionIntake, Signal
from neuralclaw.cortex.perception.output_filter import OutputThreatFilter
from neuralclaw.cortex.perception.threat_screen import ThreatScreener
from neuralclaw.cortex.perception.vision import VisionPerception
from neuralclaw.cortex.reasoning.deliberate import ConfidenceEnvelope, DeliberativeReasoner
from neuralclaw.cortex.reasoning.fast_path import FastPathReasoner
from neuralclaw.errors import ChannelError, ConfigurationError, ProviderError, SecurityError
from neuralclaw.health import HealthChecker, ReadinessProbe, ReadinessState
from neuralclaw.providers.circuit_breaker import CircuitBreakerConfig
from neuralclaw.providers.router import LLMProvider, ProviderRouter
from neuralclaw.skills.registry import SkillRegistry
from neuralclaw.skills.paths import resolve_user_skills_dir
# Heavy optional subsystems (evolution, swarm, etc.) are imported lazily
# inside __init__ guarded by feature flags — see _init_evolution() and
# _init_swarm() calls below. This keeps cold-start fast when those
# features are disabled.


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------

class NeuralClawGateway:
    """
    Main orchestration engine — the 'brain' of NeuralClaw.

    Wires together all cortices, providers, and channels into a
    cohesive cognitive pipeline.
    """

    def __init__(
        self,
        config: NeuralClawConfig | None = None,
        provider_override: str | None = None,
        dev_mode: bool | None = None,
        config_path: str | None = None,
    ) -> None:
        self._config = config or load_config()
        self._running = False
        self._provider_override = provider_override
        self._config_path = config_path
        self._dev_mode = self._config.dev_mode if dev_mode is None else dev_mode
        self._logger = logging.getLogger("neuralclaw.gateway")
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=getattr(logging, str(self._config.log_level).upper(), logging.INFO),
                format="%(asctime)s %(levelname)s %(name)s %(message)s",
            )
        self._shutdown_task: asyncio.Task[None] | None = None
        self._gc_task: asyncio.Task[None] | None = None
        self._config_watch_task: asyncio.Task[None] | None = None
        self._kb_auto_index_task: asyncio.Task[None] | None = None
        self._channel_pairing_adapters: dict[str, ChannelAdapter] = {}
        self._oauth_states: dict[str, dict[str, Any]] = {}
        self._rate_limit_config = RateLimitConfig(
            user_requests_per_minute=self._config.policy.user_requests_per_minute,
            user_requests_per_hour=self._config.policy.user_requests_per_hour,
            channel_sends_per_second=self._config.policy.channel_sends_per_second,
            channel_sends_per_minute=self._config.policy.channel_sends_per_minute,
            max_concurrent_requests=self._config.policy.max_concurrent_requests,
            security_block_cooldown_seconds=self._config.policy.security_block_cooldown_seconds,
        )
        self._rate_limiter = SlidingWindowUserLimiter(self._rate_limit_config)
        self._send_limiters: dict[str, TokenBucketRateLimiter] = {}
        self._request_semaphore = asyncio.Semaphore(
            self._rate_limit_config.max_concurrent_requests
        )
        self._security_cooldowns: dict[str, float] = {}
        self._health = HealthChecker(self._config)
        self._startup_readiness = ReadinessState.STARTING
        self._ready_at: float | None = None

        if self._dev_mode:
            self._config.dev_mode = True
            self._config.security.threat_threshold = 0.95
            self._config.policy.security_block_cooldown_seconds = 0

        # Neural bus
        self._bus = NeuralBus()
        self._telemetry = Telemetry(
            log_to_file=bool(self._config.log_file),
            log_to_stdout=bool(self._config.log_stdout),
            log_file=self._config.log_file,
            log_level=self._config.log_level,
            log_max_bytes=self._config.log_max_bytes,
            log_backups=self._config.log_backups,
            dev_mode=self._dev_mode,
        )
        self._bus.subscribe_all(self._telemetry.handle_event)
        feat = self._config.features

        # Perception cortex
        self._intake = PerceptionIntake(
            self._bus,
            max_content_chars=self._config.security.max_content_chars,
        )
        self._classifier = IntentClassifier(self._bus)
        self._threat_screener = ThreatScreener(
            bus=self._bus,
            threat_threshold=self._config.security.threat_threshold,
            block_threshold=self._config.security.block_threshold,
        )
        self._output_filter = OutputThreatFilter(
            self._bus,
            self._config.security,
        ) if self._config.security.output_filtering else None
        self._canary_token = (
            f"CANARY_{secrets.token_hex(6)}"
            if self._config.security.canary_tokens and self._config.security.output_filtering
            else ""
        )
        if self._canary_token:
            self._threat_screener.set_canary_token(self._canary_token)
        if self._output_filter:
            self._output_filter.set_system_fragments(self._default_system_prompt_fragments())
            if self._canary_token:
                self._output_filter.set_canary_token(self._canary_token)
        self._vision: VisionPerception | None = None

        # Memory cortex
        self._memory_db_pool = DBPool(self._config.memory.db_path)
        self._trace_db_pool = DBPool(self._config.traceline.db_path)
        # Resolve embed model and base URL.
        # Priority: model_roles (when enabled) > memory config > primary provider URL.
        _embed_model = self._config.memory.embedding_model
        # Always pass a base URL so vector.py never falls back to localhost.
        _embed_base_url = self._config.model_roles.base_url
        if self._config.model_roles.enabled:
            # Use the role-router's embed model if configured (may be empty for
            # auto-detect — role_router.validate_models() will fill it in).
            if self._config.model_roles.embed:
                _embed_model = self._config.model_roles.embed
            _embed_base_url = self._config.model_roles.base_url
        self._vector_memory = VectorMemory(
            self._config.memory.db_path,
            embedding_provider=self._config.memory.embedding_provider,
            embedding_model=_embed_model,
            dimension=self._config.memory.embedding_dimension,
            bus=self._bus,
            ollama_base_url=_embed_base_url,
        ) if feat.vector_memory and self._config.memory.vector_memory else None
        self._episodic = EpisodicMemory(
            self._config.memory.db_path,
            vector_memory=self._vector_memory,
            bus=self._bus,
            db_pool=self._memory_db_pool,
        )
        self._semantic = SemanticMemory(
            self._config.memory.db_path,
            db_pool=self._memory_db_pool,
        )
        self._identity = UserIdentityStore(
            self._config.memory.db_path,
            bus=self._bus,
            episodic=self._episodic,
            semantic=self._semantic,
            db_pool=self._memory_db_pool,
        ) if feat.identity and self._config.identity.enabled else None

        # Knowledge Base (RAG)
        self._knowledge_base = None
        if feat.rag and self._config.rag.enabled:
            from neuralclaw.cortex.memory.knowledge_base import KnowledgeBase
            self._knowledge_base = KnowledgeBase(
                db_path=self._config.rag.db_path,
                vector_memory=self._vector_memory,
                bus=self._bus,
                chunk_size=self._config.rag.chunk_size,
                overlap=self._config.rag.overlap,
                retrieval_top_k=self._config.rag.retrieval_top_k,
                max_doc_size_mb=self._config.rag.max_doc_size_mb,
            )

        self._retriever = MemoryRetriever(
            self._episodic, self._semantic, self._bus,
            vector_memory=self._vector_memory,
            knowledge_base=self._knowledge_base,
            max_episodes=self._config.memory.max_episodic_results,
            max_facts=self._config.memory.max_semantic_results,
            vector_top_k=self._config.memory.vector_similarity_top_k,
        )

        # Reasoning cortex
        self._fast_path = FastPathReasoner(self._bus, self._config.name)
        self._policy = PolicyEngine(self._config.policy)
        self._idempotency = IdempotencyStore(self._config.memory.db_path)
        self._checkpoint = CheckpointStore(self._config.memory.db_path)
        self._audit = AuditLogger(config=self._config.audit, bus=self._bus)
        self._deliberate = DeliberativeReasoner(
            self._bus,
            self._config.persona,
            policy=self._policy,
            idempotency=self._idempotency,
            audit=self._audit,
            checkpoint=self._checkpoint,
        )
        if feat.structured_output:
            from neuralclaw.cortex.reasoning.structured import StructuredReasoner
            self._structured = StructuredReasoner(self._deliberate, self._bus)
        else:
            self._structured = None
        if feat.reflective_reasoning if hasattr(feat, "reflective_reasoning") else True:
            from neuralclaw.cortex.reasoning.reflective import ReflectiveReasoner
            self._reflective = ReflectiveReasoner(self._bus, self._deliberate, structured=self._structured)
        else:
            self._reflective = None

        # Action cortex
        self._capability_verifier = CapabilityVerifier(
            bus=self._bus,
            allow_shell=self._config.security.allow_shell_execution,
        )
        self._skills = SkillRegistry()
        self._desktop = None
        self._browser = None
        self._forge = None
        self._scout = None
        self._hot_loader = None
        if feat.desktop and self._config.desktop.enabled:
            from neuralclaw.cortex.action.desktop import DesktopCortex

            self._desktop = DesktopCortex(
                config=self._config.desktop,
                policy=self._config.policy,
                bus=self._bus,
            )

        # Phase 2: Procedural memory + metabolism (lazy imports)
        if feat.procedural_memory:
            from neuralclaw.cortex.memory.procedural import ProceduralMemory
            self._procedural = ProceduralMemory(
                self._config.memory.db_path,
                self._bus,
                db_pool=self._memory_db_pool,
            )
        else:
            self._procedural = None

        if feat.evolution:
            from neuralclaw.cortex.memory.metabolism import MemoryMetabolism
            self._metabolism = MemoryMetabolism(
                self._episodic, self._semantic if feat.semantic_memory else None, self._bus,
                vector_memory=self._vector_memory,
            )
        else:
            self._metabolism = None

        # Phase 2: Evolution cortex (lazy imports)
        self._calibrator = None
        self._distiller = None
        self._synthesizer = None
        self._evolution_orchestrator = None
        if feat.evolution:
            from neuralclaw.cortex.evolution.calibrator import BehavioralCalibrator
            from neuralclaw.cortex.evolution.distiller import ExperienceDistiller
            from neuralclaw.cortex.evolution.synthesizer import SkillSynthesizer
            self._calibrator = BehavioralCalibrator(bus=self._bus)
            self._distiller = ExperienceDistiller(
                self._episodic, self._semantic, self._procedural, self._bus,
                structured=self._structured,
            )
            self._synthesizer = SkillSynthesizer(bus=self._bus, structured=self._structured)

        # Phase 3: Meta-cognitive reasoning + traceline (lazy imports)
        self._meta_cognitive = None
        if feat.evolution:
            from neuralclaw.cortex.reasoning.meta import MetaCognitive
            self._meta_cognitive = MetaCognitive(bus=self._bus)

        self._traceline = None
        if feat.traceline and self._config.traceline.enabled:
            from neuralclaw.cortex.observability.traceline import Traceline
            self._traceline = Traceline(
                self._config.traceline.db_path,
                self._bus,
                config=self._config.traceline,
                db_pool=self._trace_db_pool,
            )

        if self._identity and self._calibrator:
            self._identity.set_calibrator(self._calibrator)

        # Phase 3: Swarm (lazy imports)
        self._delegation = None
        self._consensus = None
        self._mesh = None
        if feat.swarm:
            from neuralclaw.swarm.delegation import DelegationChain, DelegationPolicy
            from neuralclaw.swarm.consensus import ConsensusProtocol
            from neuralclaw.swarm.mesh import AgentMesh
            self._delegation = DelegationChain(bus=self._bus)
            self._consensus = ConsensusProtocol(self._delegation, bus=self._bus)
            self._mesh = AgentMesh(bus=self._bus)

        # Phase 4: Spawner + Federation (lazy imports)
        self._spawner = None
        self._federation = None
        self._federation_bridge = None
        self._heartbeat_task: asyncio.Task[None] | None = None

        # Agent persistence + shared memory
        self._agent_store = None
        self._task_store = None
        self._shared_bridge = None
        self._workspace_coordinator = None
        self._local_model_registry_cache: dict[str, Any] = {"models": [], "resolved_base_url": "", "badges": []}
        self._local_model_registry_at: float = 0.0
        self._memory_retention_last_run: float = 0.0
        adaptive_db = self._config.memory.db_path.replace(".db", "-adaptive.db")
        self._adaptive = AdaptiveControlPlane(adaptive_db, workspace_root=Path.cwd())

        # -- v1.5 subsystem references (lazy-loaded when adaptive plane is ready) --
        self._teaching_processor: Any = None
        self._sharing_manager: Any = None
        self._multimodal_router: Any = None
        self._skill_graph: Any = None
        # -- wave-2 subsystem references --
        self._compensating_registry: Any = None
        self._intent_predictor: Any = None
        self._routine_scheduler: Any = None
        self._style_adapter: Any = None
        self._skill_federation: Any = None
        self._multimodal_processor: Any = None
        try:
            from neuralclaw.cortex.adaptive import TeachingProcessor, MultimodalRouter
            from neuralclaw.cortex.adaptive.sharing import DistilledSharingManager as SharingManager
            from neuralclaw.skills.graph import SkillGraph
            from neuralclaw.cortex.adaptive.scheduler import RoutineScheduler
            from neuralclaw.cortex.adaptive.style import StyleAdapter
            from neuralclaw.cortex.adaptive.intent import IntentPredictor
            from neuralclaw.cortex.adaptive.compensating import CompensatingRollbackRegistry

            teaching_db = self._config.memory.db_path.replace(".db", "-teaching.db")
            sharing_db = self._config.memory.db_path.replace(".db", "-sharing.db")
            multimodal_db = self._config.memory.db_path.replace(".db", "-multimodal.db")
            style_db = self._config.memory.db_path.replace(".db", "-style.db")
            intent_db = self._config.memory.db_path.replace(".db", "-intent.db")
            compensating_db = self._config.memory.db_path.replace(".db", "-compensating.db")
            
            self._teaching_processor = TeachingProcessor(teaching_db)
            self._sharing_manager = SharingManager(sharing_db)
            self._multimodal_router = MultimodalRouter(multimodal_db)
            self._skill_graph = SkillGraph()
            self._compensating_registry = CompensatingRollbackRegistry(compensating_db)
            self._style_adapter = StyleAdapter(style_db)
            self._intent_predictor = IntentPredictor(intent_db)
            self._routine_scheduler = RoutineScheduler(
                control_plane=self._adaptive,
                task_sender=self._dashboard_auto_route_task,
                bus=self._bus
            )
        except Exception as e:
            self._logger.warning("Adaptive subsystems unavailable: %s", e)
            import traceback
            traceback.print_exc()
            pass  # subsystems unavailable until cortex.adaptive ships them

        if feat.swarm and self._mesh and self._delegation:
            from neuralclaw.swarm.spawn import AgentSpawner
            from neuralclaw.swarm.agent_store import AgentStore
            from neuralclaw.swarm.task_store import TaskRecord, TaskStore
            from neuralclaw.cortex.memory.shared import SharedMemoryBridge
            self._spawner = AgentSpawner(self._mesh, self._delegation, self._bus)
            # Agent store for persistent definitions
            agent_db = self._config.memory.db_path.replace(".db", "-agents.db")
            self._agent_store = AgentStore(agent_db)
            task_db = self._config.memory.db_path.replace(".db", "-tasks.db")
            self._task_store = TaskStore(task_db)
            # Shared memory bridge for cross-agent collaboration
            shared_db = self._config.memory.db_path.replace(".db", "-shared.db")
            self._shared_bridge = SharedMemoryBridge(shared_db)

            fed_cfg = self._config.federation
            if fed_cfg.enabled:
                from neuralclaw.swarm.federation import FederationProtocol, FederationBridge
                self._federation = FederationProtocol(
                    node_name=fed_cfg.node_name or self._config.name,
                    bus=self._bus,
                    port=fed_cfg.port,
                    bind_host=fed_cfg.bind_host,
                    description=self._config.persona,
                    skills_provider=self._get_a2a_skills,
                    a2a_enabled=bool(self._config.features.a2a_federation and fed_cfg.a2a_enabled),
                    a2a_auth_required=fed_cfg.a2a_auth_required,
                    a2a_token=_get_secret("a2a_token") or "",
                )
                self._federation_bridge = FederationBridge(
                    self._federation, self._spawner, self._bus,
                )

        # Phase 3: Dashboard (lazy import — aiohttp not loaded if disabled)
        if feat.dashboard:
            from neuralclaw.dashboard import Dashboard
            self._dashboard = Dashboard(
                host=self._config.dashboard_host,
                port=self._config.dashboard_port,
                auth_token=self._config.dashboard_auth_token or "",
            )
        else:
            self._dashboard = None

        # Workflow Engine
        self._workflow_engine = None
        if feat.workflow_engine and self._config.workflow.enabled:
            from neuralclaw.cortex.reasoning.workflow import WorkflowEngine
            self._workflow_engine = WorkflowEngine(
                db_path=self._config.workflow.db_path,
                bus=self._bus,
                skill_registry=self._skills,
                max_concurrent=self._config.workflow.max_concurrent_workflows,
                max_steps=self._config.workflow.max_steps_per_workflow,
                step_timeout=self._config.workflow.step_timeout_seconds,
            )

        # MCP Server
        self._mcp_server = None
        if feat.mcp_server and self._config.mcp_server.enabled:
            from neuralclaw.mcp_server import MCPServer
            self._mcp_server = MCPServer(
                port=self._config.mcp_server.port,
                bind_host=self._config.mcp_server.bind_host,
                auth_token=self._config.mcp_server.auth_token or "",
                expose_tools=self._config.mcp_server.expose_tools,
                expose_resources=self._config.mcp_server.expose_resources,
                expose_prompts=self._config.mcp_server.expose_prompts,
            )

        # Channels
        self._channels: dict[str, ChannelAdapter] = {}
        self._trust = ChannelTrustController()

        # Conversation history (per channel_id)
        self._history: dict[str, list[dict[str, str]]] = {}

        # Provider
        self._provider: ProviderRouter | None = None
        self._role_router: "RoleRouter | None" = None  # Role-based model routing
        self._health.register_probe(
            ReadinessProbe(
                name="memory_db",
                required=True,
                check=self._ping_memory_db,
            )
        )
        self._health.register_probe(
            ReadinessProbe(
                name="primary_provider",
                required=False,
                check=self._ping_primary_provider,
            )
        )
        self._health.register_probe(
            ReadinessProbe(
                name="vector_memory",
                required=False,
                check=self._ping_vector_memory,
            )
        )
        self._health.register_probe(
            ReadinessProbe(
                name="federation",
                required=False,
                check=self._ping_federation,
            )
        )
        self._health.register_probe(
            ReadinessProbe(
                name="knowledge_base",
                required=False,
                check=self._ping_knowledge_base,
            )
        )
        self._health.register_probe(
            ReadinessProbe(
                name="workflow_engine",
                required=False,
                check=self._ping_workflow_engine,
            )
        )

    async def initialize(self) -> None:
        """Initialize all subsystems."""
        ensure_dirs()
        await self._memory_db_pool.initialize()
        if self._traceline:
            await self._trace_db_pool.initialize()

        # Initialize memory databases
        if self._vector_memory:
            await self._vector_memory.initialize()
        await self._episodic.initialize()
        await self._semantic.initialize()
        await self._audit.initialize()
        if self._identity:
            await self._identity.initialize()
        if self._traceline:
            await self._traceline.initialize()
        if self._procedural:
            await self._procedural.initialize()
        if self._knowledge_base:
            await self._knowledge_base.initialize()
            self._kb_auto_index_task = asyncio.create_task(self._auto_index_knowledge_base())
        if self._workflow_engine:
            await self._workflow_engine.initialize()

        # Initialize agent store + shared memory bridge
        if self._agent_store:
            await self._agent_store.initialize()
        if self._task_store:
            await self._task_store.initialize()
        if self._shared_bridge:
            await self._shared_bridge.initialize()
        if self._adaptive:
            await self._adaptive.initialize()
            if getattr(self, "_teaching_processor", None): await self._teaching_processor.initialize()
            if getattr(self, "_sharing_manager", None): await self._sharing_manager.initialize()
            if getattr(self, "_multimodal_router", None): await self._multimodal_router.initialize()
            if getattr(self, "_compensating_registry", None): await self._compensating_registry.initialize()
            if getattr(self, "_intent_predictor", None): await self._intent_predictor.initialize()
            if getattr(self, "_style_adapter", None): await self._style_adapter.initialize()

        # Initialize workspace coordinator (multi-agent directory claim/release)
        try:
            from neuralclaw.swarm.workspace_coordinator import WorkspaceCoordinator
            workspace_db = self._config.memory.db_path.replace(".db", "-workspace.db")
            self._workspace_coordinator = WorkspaceCoordinator(workspace_db)
            await self._workspace_coordinator.initialize()
        except Exception as _e:
            self._logger.warning("WorkspaceCoordinator init failed: %s", _e)
            self._workspace_coordinator = None

        # Initialize idempotency and checkpoint stores
        await self._idempotency.initialize()
        await self._checkpoint.initialize()

        # Initialize evolution cortex
        if self._calibrator:
            await self._calibrator.initialize()

        # Load skills
        self._skills.load_builtins()
        self._skills.register_tool(
            name="list_active_user_skills",
            description=(
                "Return the authoritative live registry view of currently active "
                "user-provided skills and their tool names. Use this instead of "
                "guessing from memory when asked what custom skills are active."
            ),
            function=self._list_active_user_skills_tool,
        )
        if "list_active_user_skills" not in self._config.policy.allowed_tools:
            self._config.policy.allowed_tools.append("list_active_user_skills")

        # Configure built-in skills with policy roots (default-deny for FS)
        try:
            from neuralclaw.skills.builtins import file_ops as _file_ops

            _file_ops.set_allowed_roots(self._policy.get_allowed_roots())
        except Exception as e:
            self._logger.debug("Failed to configure file_ops skill: %s", e)

        # Configure self_config skill — gives the agent runtime self-modification
        # tools (feature toggles, skill enable/disable, model role swaps).
        try:
            from neuralclaw.skills.builtins import self_config as _self_config

            _self_config.set_gateway(self)
            self_config_tools = [
                "list_features",
                "set_feature",
                "list_skills",
                "set_skill_enabled",
                "get_config",
                "list_available_models",
                "set_model_role",
            ]
            for _tool_name in self_config_tools:
                if _tool_name not in self._config.policy.allowed_tools:
                    self._config.policy.allowed_tools.append(_tool_name)
        except Exception as e:
            self._logger.debug("Failed to configure self_config skill: %s", e)

        try:
            from neuralclaw.skills.builtins import agent_orchestration as _agent_orchestration

            _agent_orchestration.set_gateway(self)
            for _tool_name in [
                "list_agent_definitions",
                "create_agent_definition",
                "update_agent_definition",
                "spawn_defined_agent",
                "despawn_defined_agent",
                "list_running_agents",
                "orchestrate_agent_task",
            ]:
                if _tool_name not in self._config.policy.allowed_tools:
                    self._config.policy.allowed_tools.append(_tool_name)
        except Exception as e:
            self._logger.debug("Failed to configure agent_orchestration skill: %s", e)

        # Configure github_repos skill with workspace settings
        try:
            from neuralclaw.skills.builtins import github_repos as _github_repos

            _github_repos.set_workspace_config(self._config.workspace)
        except Exception as e:
            self._logger.debug("Failed to configure github_repos skill: %s", e)

        # Configure app_builder skill with workspace settings
        try:
            from neuralclaw.skills.builtins import app_builder as _app_builder

            _app_builder.set_workspace_config(self._config.workspace)
        except Exception as e:
            self._logger.debug("Failed to configure app_builder skill: %s", e)

        # Configure knowledge base skill
        if self._knowledge_base:
            try:
                from neuralclaw.skills.builtins import knowledge_base as _kb_skill

                _kb_skill.set_knowledge_base(self._knowledge_base)
            except Exception as e:
                self._logger.debug("Failed to configure knowledge_base skill: %s", e)

        # Configure workflow skill
        if self._workflow_engine:
            try:
                from neuralclaw.skills.builtins import workflow_skill as _wf_skill

                _wf_skill.set_workflow_engine(self._workflow_engine)
            except Exception as e:
                self._logger.debug("Failed to configure workflow skill: %s", e)

        # Configure framework_intel skill (agent self-knowledge + workspace coordination)
        try:
            from neuralclaw.skills.builtins import framework_intel as _framework_intel
            _framework_intel.set_gateway(self)
            _framework_intel.set_agent_name(self._config.name)
            if self._workspace_coordinator:
                _framework_intel.set_workspace_coordinator(self._workspace_coordinator)
            for _tn in ["list_workspace_structure", "list_available_skills", "get_skill_template",
                        "get_active_agents", "claim_workspace_dir", "release_workspace_dir"]:
                if _tn not in self._config.policy.allowed_tools:
                    self._config.policy.allowed_tools.append(_tn)
        except Exception as _e:
            self._logger.debug("Failed to configure framework_intel skill: %s", _e)

        # Configure project_scaffold skill
        try:
            from neuralclaw.skills.builtins import project_scaffold as _project_scaffold
            _project_scaffold.set_workspace_config(self._config.workspace)
            _project_scaffold.set_agent_name(self._config.name)
            if self._workspace_coordinator:
                _project_scaffold.set_workspace_coordinator(self._workspace_coordinator)
            for _tn in ["scaffold_project", "list_projects", "get_project_info", "add_to_project"]:
                if _tn not in self._config.policy.allowed_tools:
                    self._config.policy.allowed_tools.append(_tn)
        except Exception as _e:
            self._logger.debug("Failed to configure project_scaffold skill: %s", _e)

        # Configure vision skill
        try:
            from neuralclaw.skills.builtins import vision as _vision
            _vision.set_gateway(self)
            # Auto-detect best provider from config
            _providers = getattr(self._config, "providers", None)
            _primary = str(getattr(_providers, "primary", "")) if _providers else ""
            if _primary in ("anthropic",):
                _vision.set_vision_provider("anthropic")
            elif _primary in ("openai",):
                _vision.set_vision_provider("openai")
            elif _primary in ("local", "meta", "ollama"):
                _vision.set_vision_provider("local")
            for _tn in ["analyze_image", "extract_text_from_image", "describe_screenshot",
                        "compare_images", "detect_vision_capability"]:
                if _tn not in self._config.policy.allowed_tools:
                    self._config.policy.allowed_tools.append(_tn)
        except Exception as _e:
            self._logger.debug("Failed to configure vision skill: %s", _e)

        # Wire MCP Server
        if self._mcp_server:
            self._mcp_server.set_skill_registry(self._skills)
            self._mcp_server.set_knowledge_base(self._knowledge_base)
            self._mcp_server.set_bus(self._bus)
            self._mcp_server.set_persona(self._config.persona)

        # Configure repo_exec skill with workspace timeout
        try:
            from neuralclaw.skills.builtins import repo_exec as _repo_exec

            _repo_exec.set_workspace_config(self._config.workspace)
            _repo_exec.set_max_exec_timeout(self._config.workspace.max_exec_timeout_seconds)
        except Exception as e:
            self._logger.debug("Failed to configure repo_exec skill: %s", e)

        # Configure api_client skill with saved API configs
        try:
            from neuralclaw.skills.builtins import api_client as _api_client

            _api_client.set_api_configs(self._config.apis)
        except Exception as e:
            self._logger.debug("Failed to configure api_client skill: %s", e)

        try:
            from neuralclaw.skills.builtins import github_ops as _github_ops

            _github_ops.set_api_configs(self._config.apis)
            for _tool_name in [
                "github_list_pull_requests",
                "github_get_pull_request",
                "github_list_issues",
                "github_get_issue",
                "github_get_ci_status",
                "github_comment_issue",
            ]:
                if _tool_name not in self._config.policy.allowed_tools:
                    self._config.policy.allowed_tools.append(_tool_name)
        except Exception as e:
            self._logger.debug("Failed to configure github_ops skill: %s", e)

        # Configure optional integration skills
        try:
            from neuralclaw.skills.builtins import tts as _tts

            _tts.set_tts_config(self._config.tts)
        except Exception as e:
            self._logger.debug("Failed to configure tts skill: %s", e)

        try:
            from neuralclaw.skills.builtins import google_workspace as _google_workspace

            _google_workspace.set_google_workspace_config(self._config.google_workspace)
        except Exception as e:
            self._logger.debug("Failed to configure google_workspace skill: %s", e)

        try:
            from neuralclaw.skills.builtins import microsoft365 as _microsoft365

            _microsoft365.set_microsoft365_config(self._config.microsoft365)
        except Exception as e:
            self._logger.debug("Failed to configure microsoft365 skill: %s", e)

        # Configure database BI skill
        if self._config.features.database_bi:
            try:
                from neuralclaw.skills.builtins import database_bi as _database_bi

                _database_bi.set_max_rows(self._config.database_bi.max_result_rows)
                # Saved connections are auto-connected after provider init
            except Exception as e:
                self._logger.debug("Failed to configure database_bi skill: %s", e)

        if self._desktop:
            self._register_desktop_tools()

        # Initialize LLM provider
        self._provider = self._build_provider()

        # Build role-based model router (Ollama multi-model routing)
        if self._config.model_roles.enabled:
            from neuralclaw.providers.role_router import RoleRouter
            self._role_router = RoleRouter.from_config(self._config.model_roles)
            self._logger.info(
                "Role router enabled: %s", self._role_router.model_map
            )

        # Validate role router models against actually-served models, then
        # update VectorMemory with the resolved embed model so memory always
        # uses a real model rather than falling back to hash-based embeddings.
        if self._role_router:
            try:
                validated_map = await self._role_router.validate_models()
                self._logger.info("Role router validated: %s", validated_map)
                if self._vector_memory:
                    resolved_embed = self._role_router.embed_model
                    if resolved_embed:
                        self._vector_memory._embedding_model = resolved_embed
                        self._logger.info("VectorMemory embed model set to: %s", resolved_embed)
            except Exception as e:
                self._logger.warning("Role router validation failed: %s", e)

        if self._provider:
            self._deliberate.set_provider(self._provider)
            # Inject role router into deliberative reasoner and classifier
            if self._role_router:
                self._deliberate.set_role_router(self._role_router)
                self._classifier.set_role_router(self._role_router)

            # Inject LLM provider into database BI for natural-language queries
            if self._config.features.database_bi:
                try:
                    from neuralclaw.skills.builtins import database_bi as _database_bi
                    _database_bi.set_llm_provider(self._provider)
                    _database_bi.set_llm_provider_resolver(self._resolve_database_bi_provider)
                    # Auto-connect saved database connections from config
                    for conn_name, conn_cfg in self._config.database_bi.saved_connections.items():
                        try:
                            await _database_bi.db_connect(
                                name=conn_name,
                                driver=conn_cfg.get("driver", "sqlite"),
                                dsn=conn_cfg.get("dsn", ""),
                                schema=conn_cfg.get("schema", ""),
                                read_only=conn_cfg.get("read_only", True),
                            )
                            self._logger.info("Auto-connected database: %s", conn_name)
                        except Exception as ce:
                            self._logger.warning("Failed to auto-connect database '%s': %s", conn_name, ce)
                except Exception as e:
                    self._logger.debug("Failed to inject LLM into database_bi: %s", e)

            # Inject LLM into digest skill
            if self._config.features.digest:
                try:
                    from neuralclaw.skills.builtins import digest as _digest
                    _digest.set_llm_provider(self._provider)
                    _digest.set_memory_provider(self._episodic)
                except Exception as e:
                    self._logger.debug("Failed to configure digest skill: %s", e)

            # Inject LLM into context-aware skill
            if self._config.features.context_aware:
                try:
                    from neuralclaw.skills.builtins import context_aware as _context_aware
                    _context_aware.set_llm_provider(self._provider)
                except Exception as e:
                    self._logger.debug("Failed to configure context_aware skill: %s", e)

            # Configure KPI monitor alert callback
            if self._config.features.kpi_monitor:
                try:
                    from neuralclaw.skills.builtins import kpi_monitor as _kpi
                    async def _kpi_alert_callback(monitor_name: str, reading: dict) -> None:
                        if self._bus:
                            await self._bus.publish(
                                EventType.INFO,
                                {"monitor": monitor_name, "reading": reading, "event": "kpi_alert"},
                                source="kpi_monitor",
                            )
                    _kpi.set_alert_callback(_kpi_alert_callback)
                except Exception as e:
                    self._logger.debug("Failed to configure kpi_monitor skill: %s", e)

            # Configure scheduler action callback
            if self._config.features.scheduler:
                try:
                    from neuralclaw.skills.builtins import scheduler as _scheduler
                    async def _schedule_action_callback(action_type: str, payload: dict) -> str:
                        if action_type == "message":
                            return await self.process_message(
                                content=payload.get("content", ""),
                                author_id="scheduler",
                                channel_id="scheduler",
                            )
                        return f"Executed scheduled action: {action_type}"
                    _scheduler.set_action_callback(_schedule_action_callback)
                except Exception as e:
                    self._logger.debug("Failed to configure scheduler skill: %s", e)

            if self._config.features.vision:
                self._vision = VisionPerception(self._provider, self._bus)
            if self._distiller:
                self._distiller.set_structured(self._structured)
            if self._synthesizer:
                self._synthesizer.set_structured(self._structured)
                self._synthesizer.set_provider(self._provider)

            # SkillForge — proactive skill synthesis
            feat = self._config.features
            if feat.skill_forge:
                from neuralclaw.skills.forge import SkillForge
                from neuralclaw.skills.hot_loader import SkillHotLoader

                from neuralclaw.cortex.action.sandbox import Sandbox as _ForgeSandbox
                skills_dir = resolve_user_skills_dir(self._config.forge.user_skills_dir)
                forge_provider = self._build_forge_provider() or self._provider

                self._forge = SkillForge(
                    provider=forge_provider,
                    sandbox=_ForgeSandbox(timeout_seconds=self._config.forge.sandbox_timeout),
                    registry=self._skills,
                    bus=self._bus,
                    model=self._config.forge.model,
                    user_skills_dir=skills_dir,
                )
                self._skills.load_user_skills(
                    policy_config=self._config.policy,
                    skills_dir=skills_dir,
                )
                if self._config.forge.hot_reload:
                    self._hot_loader = SkillHotLoader(
                        registry=self._skills,
                        bus=self._bus,
                        policy_config=self._config.policy,
                        skills_dir=skills_dir,
                    )
                    await self._hot_loader.start(load_existing=False)

                # Register forge as an agent tool
                self._skills.register_tool(
                    name="forge_skill",
                    description=(
                        "Create a new skill for yourself from any source — URL, description, "
                        "Python library, OpenAPI spec, GitHub repo, or MCP server. "
                        "The skill is immediately available after forging. "
                        "Use when the user asks you to 'learn' something new, "
                        "add a new capability, or integrate with a new service."
                    ),
                    function=self._forge_skill_tool,
                    parameters={
                        "source": {
                            "type": "string",
                            "description": "URL, library name, natural language description, or code to forge from.",
                        },
                        "use_case": {
                            "type": "string",
                            "description": "What you specifically need this skill to do. More specific = better tools.",
                        },
                    },
                )
                # Allowlist forge_skill in policy
                if "forge_skill" not in self._config.policy.allowed_tools:
                    self._config.policy.allowed_tools.append("forge_skill")

                # SkillScout — discovery layer on top of SkillForge
                from neuralclaw.skills.scout import SkillScout

                self._scout = SkillScout(
                    forge=self._forge,
                    provider=forge_provider,
                )

                # Register scout as an agent tool
                self._skills.register_tool(
                    name="scout_skill",
                    description=(
                        "Search PyPI, GitHub, npm, and MCP registries for the best "
                        "open-source package or API that matches a need, then "
                        "automatically forge it into a live skill. Use when the user "
                        "describes what they need but doesn't know which library or "
                        "API to use. Searches, ranks, picks the best, and forges it."
                    ),
                    function=self._scout_skill_tool,
                    parameters={
                        "query": {
                            "type": "string",
                            "description": "Natural language description of what capability is needed.",
                        },
                    },
                )
                # Allowlist scout_skill in policy
                if "scout_skill" not in self._config.policy.allowed_tools:
                    self._config.policy.allowed_tools.append("scout_skill")

                if feat.evolution:
                    from neuralclaw.cortex.evolution.orchestrator import EvolutionOrchestrator
                    self._evolution_orchestrator = EvolutionOrchestrator(
                        bus=self._bus,
                        registry=self._skills,
                        forge=self._forge,
                        scout=self._scout,
                        policy_config=self._config.policy,
                        user_skills_dir=skills_dir,
                    )
                    await self._evolution_orchestrator.initialize()
        else:
            configured = self._config.primary_provider.name if self._config.primary_provider else "none"
            raise ProviderError(
                f"Failed to initialize LLM provider '{configured}'.\n\n"
                f"  Common causes:\n"
                f"  1. Missing or invalid API key - run: neuralclaw init\n"
                f"  2. No internet connectivity for hosted providers\n"
                f"  3. Using 'local' provider but Ollama is not running - run: ollama serve\n\n"
                f"  Run neuralclaw doctor for a full diagnostic."
            )
        if self._config.features.browser and self._config.browser.enabled:
            from neuralclaw.cortex.action.browser import BrowserCortex

            self._browser = BrowserCortex(
                config=self._config.browser,
                bus=self._bus,
                vision=self._vision,
                provider=self._provider,
            )
            await self._browser.start()
            self._register_browser_tools()

        # Phase 3: Wire dashboard providers and actions
        if self._dashboard:
            self._dashboard.set_stats_provider(self._get_dashboard_stats)
            self._dashboard.set_agents_provider(self._get_dashboard_agents)
            self._dashboard.set_federation_provider(self._get_dashboard_federation)
            self._dashboard.set_memory_provider(self._get_dashboard_memory)
            self._dashboard.set_memory_management_actions(
                list_action=self._dashboard_list_memory_items,
                update_item_action=self._dashboard_update_memory_item,
                delete_item_action=self._dashboard_delete_memory_item,
                pin_item_action=self._dashboard_pin_memory_item,
            )
            self._dashboard.set_bus_provider(self._get_dashboard_bus)
            self._dashboard.set_health_provider(self._get_health_payload)
            self._dashboard.set_ready_provider(self._get_ready_payload)
            self._dashboard.set_metrics_provider(self._get_metrics_payload)
            self._dashboard.set_metrics_json_provider(self._get_dashboard_metrics)
            self._dashboard.set_trace_providers(
                self._get_dashboard_traces,
                self._get_dashboard_trace,
            )
            self._dashboard.set_config_provider(self._get_dashboard_config)
            self._dashboard.set_config_update_action(self._dashboard_update_config)
            self._dashboard.set_channels_provider(self._get_dashboard_channels)
            self._dashboard.set_channel_actions(
                update_action=self._dashboard_update_channel,
                test_action=self._dashboard_test_channel,
                pair_action=self._dashboard_pair_channel,
                reset_action=self._dashboard_reset_channel,
            )
            self._dashboard.set_skills_provider(self._get_dashboard_skills)
            self._dashboard.set_swarm_provider(self._get_dashboard_agents)
            self._dashboard.set_task_providers(
                self._dashboard_list_tasks,
                self._dashboard_get_task,
                self._dashboard_approve_task,
                self._dashboard_reject_task,
            )
            self._dashboard.set_local_models_provider(self._dashboard_get_local_model_health)
            self._dashboard.set_operator_brief_provider(self._dashboard_get_operator_brief)
            self._dashboard.set_audit_provider(self._dashboard_get_audit)
            self._dashboard.set_integrations_provider(self._dashboard_list_integrations)
            self._dashboard.set_integration_actions(
                test_action=self._dashboard_test_integration,
                connect_action=self._dashboard_connect_integration,
                disconnect_action=self._dashboard_disconnect_integration,
                callback_action=self._dashboard_handle_integration_callback,
            )
            self._dashboard.set_provider_reset_action(self._dashboard_reset_provider_circuit)
            # Action callables
            if self._spawner:
                self._dashboard.set_spawn_action(self._dashboard_spawn)
                self._dashboard.set_despawn_action(self._dashboard_despawn)
            # Agent definition CRUD actions
            if self._agent_store:
                self._dashboard.set_agent_definition_actions(
                    list_fn=self._dashboard_list_definitions,
                    create_fn=self._dashboard_create_definition,
                    update_fn=self._dashboard_update_definition,
                    delete_fn=self._dashboard_delete_definition,
                    spawn_fn=self._dashboard_spawn_definition,
                    despawn_fn=self._dashboard_despawn_definition,
                    running_fn=self._dashboard_get_running_agents,
                    delegate_fn=self._dashboard_delegate_task,
                    shared_task_create_fn=self._dashboard_create_shared_task,
                    shared_task_get_fn=self._dashboard_get_shared_task,
                    memories_fn=self._dashboard_get_agent_memories,
                    activity_fn=self._dashboard_get_agent_activity,
                    auto_route_fn=self._dashboard_auto_route_task,
                    consensus_fn=self._dashboard_seek_consensus,
                    pipeline_fn=self._dashboard_pipeline_task,
                )
            if self._workflow_engine:
                self._dashboard.set_workflow_actions(
                    list_action=self._dashboard_list_workflows,
                    create_action=self._dashboard_create_workflow,
                    run_action=self._dashboard_run_workflow,
                    pause_action=self._dashboard_pause_workflow,
                    delete_action=self._dashboard_delete_workflow,
                )
            if self._federation:
                self._dashboard.set_join_federation_action(self._federation.join_federation)
                self._dashboard.set_message_peer_action(self._dashboard_message_peer)
            self._dashboard.set_send_message_action(self._dashboard_send_message)
            self._dashboard.set_clear_memory_action(self._dashboard_clear_memory)
            self._dashboard.set_memory_backup_actions(
                export_action=self._dashboard_export_memory,
                import_action=self._dashboard_import_memory,
                retention_action=self._dashboard_run_memory_retention,
            )
            self._dashboard.set_knowledge_base_actions(
                list_action=self._dashboard_list_kb_documents,
                ingest_action=self._dashboard_ingest_kb_document,
                ingest_text_action=self._dashboard_ingest_kb_text,
                search_action=self._dashboard_search_kb,
                delete_action=self._dashboard_delete_kb_document,
            )
            self._dashboard.set_assistant_actions(
                screen_action=self._dashboard_capture_screen_preview,
            )
            self._dashboard.set_features_provider(
                self._dashboard_get_features, self._dashboard_set_feature,
            )
            self._dashboard.set_adaptive_actions(
                snapshot_create=self._dashboard_create_snapshot,
                rollback_execute=self._dashboard_execute_rollback,
                snapshot_list=self._dashboard_list_snapshots,
                rollback_status=self._dashboard_get_rollback_status,
                routine_list=self._dashboard_list_routines,
                routine_update=self._dashboard_review_routine,
                learning_review=self._dashboard_review_learning_diff,
                pending_reviews=self._dashboard_list_pending_learning_reviews,
                project_activate=self._dashboard_activate_project,
                project_suspend=self._dashboard_suspend_project,
                project_active=self._dashboard_get_active_project,
                project_sessions=self._dashboard_list_project_sessions,
                teaching_capture=self._dashboard_capture_teaching_artifact,
                teaching_list=self._dashboard_list_teaching_artifacts,
                skill_graph=self._dashboard_get_skill_graph,
                sharing_export=self._dashboard_export_distilled_patterns,
                sharing_import=self._dashboard_import_distilled_patterns,
                multimodal_voice=self._dashboard_ingest_voice_artifact,
                multimodal_screenshot=self._dashboard_ingest_screenshot_artifact,
                multimodal_recording=self._dashboard_ingest_recording_artifact,
                multimodal_diagram=self._dashboard_ingest_diagram_artifact,
                # wave-2 subsystem actions
                intent_predictions=self._dashboard_get_intent_predictions,
                intent_stats=self._dashboard_get_intent_stats,
                intent_observe=self._dashboard_observe_intent,
                style_profile=self._dashboard_get_style_profile,
                style_rule=self._dashboard_set_style_rule,
                compensating_history=self._dashboard_get_compensating_history,
                compensating_list=self._dashboard_list_compensators,
                compensating_plan=self._dashboard_plan_compensation,
                compensating_execute=self._dashboard_execute_compensation,
                federation_skills=self._dashboard_list_federated_skills,
                federation_stats=self._dashboard_get_federation_stats,
                federation_publish=self._dashboard_publish_federated_skill,
                federation_import=self._dashboard_import_federated_skill,
                scheduler_status=self._dashboard_get_scheduler_status,
                scheduler_force=self._dashboard_force_run_routine,
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

        # Auto-start saved agent definitions
        if self._agent_store and self._spawner:
            try:
                auto_agents = await self._agent_store.get_auto_start()
                for defn in auto_agents:
                    try:
                        self._spawner.spawn_from_definition(
                            defn,
                            episodic=self._episodic,
                            semantic=self._semantic,
                            procedural=self._procedural,
                            shared_bridge=self._shared_bridge,
                            skill_registry=self._skills,
                        )
                        print(f"   Agent auto-started: {defn.name} ({defn.provider}/{defn.model})")
                    except Exception as e:
                        self._logger.warning("Failed to auto-start agent %s: %s", defn.name, e)
            except Exception as e:
                self._logger.warning("Failed to load auto-start agents: %s", e)

    def _build_provider(self) -> ProviderRouter | None:
        """Build the provider router from config."""
        return self._build_provider_router()

    def _build_forge_provider(self) -> ProviderRouter | None:
        """Build a dedicated provider router for forge/scout workloads."""
        breaker_config = CircuitBreakerConfig(
            timeout_seconds=float(self._config.forge.provider_circuit_timeout_seconds),
            slow_call_threshold_ms=float(self._config.forge.provider_slow_call_threshold_ms),
        )
        return self._build_provider_router(
            request_timeout_seconds=float(self._config.forge.provider_request_timeout_seconds),
            breaker_config=breaker_config,
            max_retries=int(self._config.forge.provider_max_retries),
        )

    def _build_provider_router(
        self,
        request_timeout_seconds: float | None = None,
        breaker_config: CircuitBreakerConfig | None = None,
        max_retries: int = 2,
    ) -> ProviderRouter | None:
        """Build the provider router from config with optional timeout overrides."""
        providers: list[LLMProvider] = []
        primary: LLMProvider | None = None

        cfg = self._config

        provider_builders = {
            "openai": self._build_openai,
            "anthropic": self._build_anthropic,
            "openrouter": self._build_openrouter,
            "google": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "google",
                cfg,
                default_model="gemini-2.5-pro",
                default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                request_timeout_seconds=request_timeout_seconds,
            ),
            "xai": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "xai",
                cfg,
                default_model="grok-3-beta",
                default_base_url="https://api.x.ai/v1",
                request_timeout_seconds=request_timeout_seconds,
            ),
            "venice": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "venice",
                cfg,
                default_model="venice-large",
                default_base_url="https://api.venice.ai/api/v1",
                request_timeout_seconds=request_timeout_seconds,
            ),
            "mistral": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "mistral",
                cfg,
                default_model="mistral-large-latest",
                default_base_url="https://api.mistral.ai/v1",
                request_timeout_seconds=request_timeout_seconds,
            ),
            "minimax": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "minimax",
                cfg,
                default_model="MiniMax-M1",
                default_base_url="https://api.minimax.chat/v1",
                request_timeout_seconds=request_timeout_seconds,
            ),
            "vercel": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "vercel",
                cfg,
                default_model="openai/gpt-5.4",
                default_base_url="https://ai-gateway.vercel.sh/v1",
                request_timeout_seconds=request_timeout_seconds,
            ),
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
                p = self._call_provider_builder(
                    builder,
                    self._get_provider_config(self._provider_override),
                    request_timeout_seconds,
                )
                if p:
                    primary = p
        elif cfg.primary_provider:
            builder = provider_builders.get(cfg.primary_provider.name)
            if builder:
                p = self._call_provider_builder(
                    builder,
                    cfg.primary_provider,
                    request_timeout_seconds,
                )
                if p:
                    primary = p

        for fp in cfg.fallback_providers:
            builder = provider_builders.get(fp.name)
            if builder:
                p = self._call_provider_builder(builder, fp, request_timeout_seconds)
                if p:
                    providers.append(p)

        if not primary:
            for name, builder in provider_builders.items():
                p = self._call_provider_builder(
                    builder,
                    self._get_provider_config(name),
                    request_timeout_seconds,
                )
                if p:
                    primary = p
                    break

        if not primary:
            return None

        return ProviderRouter(
            primary=primary,
            fallbacks=providers,
            bus=self._bus,
            breaker_config=breaker_config,
            max_retries=max_retries,
        )

    def _call_provider_builder(
        self,
        builder: Any,
        provider_cfg: Any,
        request_timeout_seconds: float | None,
    ) -> LLMProvider | None:
        """Call provider builders while preserving backward-compatible test monkeypatches."""
        params = inspect.signature(builder).parameters
        if "request_timeout_seconds" in params:
            return builder(provider_cfg, request_timeout_seconds=request_timeout_seconds)
        return builder(provider_cfg)

    def _build_openai(
        self,
        cfg: Any,
        request_timeout_seconds: float | None = None,
    ) -> LLMProvider | None:
        key = get_api_key("openai")
        if not key:
            return None
        from neuralclaw.providers.openai import OpenAIProvider
        return OpenAIProvider(
            api_key=key,
            model=cfg.model or "gpt-4o",
            base_url=cfg.base_url or "https://api.openai.com/v1",
            request_timeout_seconds=request_timeout_seconds or 120.0,
        )

    def _build_anthropic(
        self,
        cfg: Any,
        request_timeout_seconds: float | None = None,
    ) -> LLMProvider | None:
        key = get_api_key("anthropic")
        if not key:
            return None
        from neuralclaw.providers.anthropic import AnthropicProvider
        return AnthropicProvider(
            api_key=key,
            model=cfg.model or "claude-sonnet-4-20250514",
            base_url=cfg.base_url or "https://api.anthropic.com",
            request_timeout_seconds=request_timeout_seconds or 120.0,
        )

    def _build_openrouter(
        self,
        cfg: Any,
        request_timeout_seconds: float | None = None,
    ) -> LLMProvider | None:
        key = get_api_key("openrouter")
        if not key:
            return None
        from neuralclaw.providers.openrouter import OpenRouterProvider
        return OpenRouterProvider(
            api_key=key,
            model=cfg.model or "anthropic/claude-sonnet-4-20250514",
            base_url=cfg.base_url or "https://openrouter.ai/api/v1",
            request_timeout_seconds=request_timeout_seconds or 120.0,
        )

    def _build_openai_compatible(
        self,
        provider_name: str,
        cfg: Any,
        *,
        default_model: str,
        default_base_url: str,
        request_timeout_seconds: float | None = None,
    ) -> LLMProvider | None:
        key = get_api_key(provider_name)
        if not key:
            return None
        from neuralclaw.providers.proxy import ProxyProvider
        return ProxyProvider(
            base_url=cfg.base_url or default_base_url,
            model=cfg.model or default_model,
            api_key=key,
            request_timeout_seconds=request_timeout_seconds or 120.0,
        )

    def _build_local(
        self,
        cfg: Any,
        request_timeout_seconds: float | None = None,
    ) -> LLMProvider | None:
        from neuralclaw.providers.local import LocalProvider
        return LocalProvider(
            model=cfg.model or "qwen3.5:35b",
            base_url=cfg.base_url or self._candidate_local_base_urls("")[0],
            # Local Ollama models may need several minutes to cold-load
            # multi-GB weights and emit the first token. The previous 120 s
            # cap caused asyncio.TimeoutError on every first-call to large
            # models like gemma:26b.
            request_timeout_seconds=request_timeout_seconds or 600.0,
        )

    def _build_proxy(
        self,
        cfg: Any,
        request_timeout_seconds: float | None = None,
    ) -> LLMProvider | None:
        if not cfg.base_url:
            return None
        from neuralclaw.providers.proxy import ProxyProvider
        api_key = get_api_key("proxy") or ""
        return ProxyProvider(
            base_url=cfg.base_url,
            model=cfg.model or "gpt-4",
            api_key=api_key,
            request_timeout_seconds=request_timeout_seconds or 120.0,
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
        if not health.get("has_token") and not cfg.profile_dir:
            return None
        from neuralclaw.providers.chatgpt_token import ChatGPTTokenProvider
        return ChatGPTTokenProvider(model=cfg.model or "auto", profile_dir=cfg.profile_dir)

    def _build_claude_token(self, cfg: Any) -> LLMProvider | None:
        from neuralclaw.session.auth import AuthManager
        auth = AuthManager("claude")
        health = auth.health_check()
        if not health.get("has_token") and not cfg.profile_dir:
            return None
        from neuralclaw.providers.claude_token import ClaudeTokenProvider
        return ClaudeTokenProvider(model=cfg.model or "auto", profile_dir=cfg.profile_dir)

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

    def _configured_primary_provider_name(self) -> str:
        requested = str(
            getattr(self._config.primary_provider, "name", "")
            or self._config._raw.get("providers", {}).get("primary", "")
            or "local"
        ).strip().lower()
        if requested in {"meta", "ollama"}:
            return "local"
        return requested or "local"

    def _resolve_provider_name(self, requested: str = "") -> str:
        normalized = str(requested or "").strip().lower()
        if normalized in {"", "auto", "default", "primary"}:
            return self._configured_primary_provider_name()
        if normalized in {"meta", "ollama"}:
            return "local"
        return normalized

    def _provider_default_route(self, requested: str = "") -> tuple[str, str, str]:
        provider_name = self._resolve_provider_name(requested)
        configured = self._get_provider_config(provider_name)
        model = str(configured.model or "").strip()
        base_url = str(configured.base_url or "").strip()

        if provider_name == "local":
            model = str(getattr(self._config.model_roles, "primary", "") or model or "").strip()
            base_url = str(getattr(self._config.model_roles, "base_url", "") or base_url or "").strip()

        if provider_name == self._configured_primary_provider_name():
            model = str(getattr(self._config.primary_provider, "model", "") or model or "").strip()
            base_url = str(getattr(self._config.primary_provider, "base_url", "") or base_url or "").strip()

        return provider_name, model, base_url

    async def _build_dashboard_override_provider(
        self,
        provider_name: str,
        model_name: str = "",
        base_url: str = "",
    ) -> tuple[LLMProvider | None, str | None, str | None, str | None]:
        normalized_provider = (provider_name or "").strip().lower()
        if not normalized_provider:
            return None, None, None, None
        if normalized_provider == "meta":
            normalized_provider = "local"

        resolved_model = model_name.strip()
        resolved_base_url = base_url.strip()
        fallback_reason: str | None = None

        if normalized_provider == "local":
            configured = self._get_provider_config("local")
            requested_model = resolved_model or configured.model or "qwen3.5:35b"
            resolved_model, resolved_base_url, fallback_reason = await self._resolve_local_model_with_fallback(
                requested_model,
                resolved_base_url or configured.base_url,
            )
            self._ensure_local_chat_model(resolved_model, context="chat")
        else:
            configured = self._get_provider_config(normalized_provider)
            if not resolved_model:
                resolved_model = configured.model
            if not resolved_base_url:
                resolved_base_url = configured.base_url

        override_cfg = ProviderConfig(
            name=normalized_provider,
            model=resolved_model,
            base_url=resolved_base_url,
            api_key=get_api_key(normalized_provider),
            profile_dir=configured.profile_dir,
            headless=configured.headless,
            browser_channel=configured.browser_channel,
            site_url=configured.site_url,
            auth_method=configured.auth_method,
        )

        builders = {
            "openai": self._build_openai,
            "anthropic": self._build_anthropic,
            "openrouter": self._build_openrouter,
            "google": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "google",
                cfg,
                default_model="gemini-2.5-pro",
                default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                request_timeout_seconds=request_timeout_seconds,
            ),
            "xai": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "xai",
                cfg,
                default_model="grok-3-beta",
                default_base_url="https://api.x.ai/v1",
                request_timeout_seconds=request_timeout_seconds,
            ),
            "venice": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "venice",
                cfg,
                default_model="venice-large",
                default_base_url="https://api.venice.ai/api/v1",
                request_timeout_seconds=request_timeout_seconds,
            ),
            "mistral": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "mistral",
                cfg,
                default_model="mistral-large-latest",
                default_base_url="https://api.mistral.ai/v1",
                request_timeout_seconds=request_timeout_seconds,
            ),
            "minimax": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "minimax",
                cfg,
                default_model="MiniMax-M1",
                default_base_url="https://api.minimax.chat/v1",
                request_timeout_seconds=request_timeout_seconds,
            ),
            "vercel": lambda cfg, request_timeout_seconds=None: self._build_openai_compatible(
                "vercel",
                cfg,
                default_model="openai/gpt-5.4",
                default_base_url="https://ai-gateway.vercel.sh/v1",
                request_timeout_seconds=request_timeout_seconds,
            ),
            "local": self._build_local,
            "proxy": self._build_proxy,
        }
        builder = builders.get(normalized_provider)
        if not builder:
            return None, None, None, None

        timeout_seconds = 600.0 if normalized_provider == "local" else 120.0
        provider = self._call_provider_builder(builder, override_cfg, timeout_seconds)
        return provider, resolved_model or None, resolved_base_url or None, fallback_reason

    async def _resolve_database_bi_provider(
        self,
        provider: str = "",
        model: str = "",
        base_url: str = "",
        allow_fallback: bool | None = None,
    ) -> LLMProvider | ProviderRouter | None:
        db_cfg = getattr(self._config, "database_bi", None)
        selected_provider = str(provider or getattr(db_cfg, "workspace_provider", "") or "primary").strip().lower()
        selected_model = str(model or getattr(db_cfg, "workspace_model", "") or "").strip()
        selected_base_url = str(base_url or getattr(db_cfg, "workspace_base_url", "") or "").strip()
        fallback_enabled = (
            bool(getattr(db_cfg, "workspace_allow_fallback", False))
            if allow_fallback is None
            else bool(allow_fallback)
        )

        if selected_provider in {"", "auto", "default", "primary"}:
            selected_provider = str(getattr(self._config.primary_provider, "name", "") or "").strip().lower()
            if not selected_model:
                selected_model = str(getattr(self._config.primary_provider, "model", "") or "").strip()
            if not selected_base_url:
                selected_base_url = str(getattr(self._config.primary_provider, "base_url", "") or "").strip()
            if fallback_enabled:
                return self._provider

        if selected_provider == "meta":
            selected_provider = "local"

        override_provider, _, _, _ = await self._build_dashboard_override_provider(
            selected_provider,
            selected_model,
            selected_base_url,
        )
        if override_provider is not None:
            return override_provider

        return self._provider if fallback_enabled else None

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
            effective_token = ch_config.token
            if ch_config.name == "whatsapp" and not effective_token:
                effective_token = str(ch_config.extra.get("auth_dir", "") or "").strip() or None
            if not ch_config.enabled or not effective_token:
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
        return DiscordAdapter(
            cfg.token,
            auto_disconnect_empty_vc=bool(cfg.extra.get("auto_disconnect_empty_vc", True)),
        )

    def _build_slack_channel(self, cfg: Any) -> ChannelAdapter | None:
        app_token = cfg.extra.get("slack_app")
        if not app_token:
            return None
        from neuralclaw.channels.slack import SlackAdapter
        return SlackAdapter(cfg.token, app_token)

    def _build_whatsapp_channel(
        self,
        cfg: Any,
        *,
        on_qr: Any | None = None,
        on_pairing_code: Any | None = None,
        phone_number: str = "",
    ) -> ChannelAdapter | None:
        import logging as _log
        _logger = _log.getLogger("neuralclaw.gateway")

        def _log_qr(data: str) -> None:
            _logger.info("[WhatsApp] QR code received — pair via neuralclaw channels connect whatsapp")

        from neuralclaw.channels.whatsapp_baileys import BaileysWhatsAppAdapter
        auth_dir = str(cfg.token or cfg.extra.get("auth_dir", "") or "").strip()
        return BaileysWhatsAppAdapter(
            auth_dir=auth_dir,
            on_qr=on_qr or _log_qr,
            on_pairing_code=on_pairing_code,
            phone_number=phone_number,
            allow_self_chat=bool(cfg.extra.get("allow_self_chat", True)),
            allow_contact_chats=bool(cfg.extra.get("allow_contact_chats", False)),
        )

    def _build_signal_channel(self, cfg: Any) -> ChannelAdapter | None:
        from neuralclaw.channels.signal_adapter import SignalAdapter
        return SignalAdapter(cfg.token)

    async def _ping_memory_db(self) -> bool:
        return await self._episodic.ping()

    async def _ping_primary_provider(self) -> bool:
        return bool(self._provider and await self._provider.ping_primary())

    async def _ping_vector_memory(self) -> bool:
        if not self._vector_memory:
            return True
        return await self._vector_memory.ping()

    async def _ping_federation(self) -> bool:
        if not self._federation:
            return True
        return await self._federation.ping()

    async def _ping_knowledge_base(self) -> bool:
        if not self._knowledge_base:
            return True
        return await self._knowledge_base.ping()

    async def _ping_workflow_engine(self) -> bool:
        if not self._workflow_engine:
            return True
        return await self._workflow_engine.ping()

    def _get_send_limiter(self, platform: str) -> TokenBucketRateLimiter:
        limiter = self._send_limiters.get(platform)
        if limiter is None:
            limiter = TokenBucketRateLimiter(
                rate_per_second=self._rate_limit_config.channel_sends_per_second,
                burst=max(1, int(self._rate_limit_config.channel_sends_per_minute // 4) or 1),
            )
            self._send_limiters[platform] = limiter
        return limiter

    async def _send_with_rate_limit(
        self,
        platform: str,
        adapter: ChannelAdapter,
        channel_id: str,
        response: str,
        **kwargs: Any,
    ) -> None:
        if not self._dev_mode:
            await self._get_send_limiter(platform).acquire()
        await adapter.send(channel_id, response, **kwargs)

    def add_channel(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter."""
        adapter.on_message(self._on_channel_message)
        self._channels[adapter.name] = adapter
        self._get_send_limiter(adapter.name)
        try:
            from neuralclaw.skills.builtins import tts as _tts

            _tts.register_adapter(adapter.name, adapter)
        except Exception:
            pass

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
            async with self._request_semaphore:
                media = getattr(msg, "media", []) or []

                # SkillForge intercept — handle forge commands before normal processing
                if self._forge and msg.content and msg.content.strip():
                    from neuralclaw.skills.forge_handlers import handle_forge_message

                    channel_type_name = self._get_channel_type(msg)
                    source_channel = self._get_source_adapter(msg)
                    if source_channel and source_channel in self._channels:
                        _adapter = self._channels[source_channel]

                        async def _forge_respond(text: str) -> None:
                            await _adapter.send(msg.channel_id, text)

                        handled = await handle_forge_message(
                            content=msg.content,
                            author_id=msg.author_id,
                            channel_id=msg.channel_id,
                            platform=channel_type_name.lower() if channel_type_name else "unknown",
                            forge=self._forge,
                            respond=_forge_respond,
                        )
                        if handled:
                            return

                        # SkillScout intercept — handle scout commands
                        if self._scout:
                            from neuralclaw.skills.scout_handlers import handle_scout_message

                            scout_handled = await handle_scout_message(
                                content=msg.content,
                                author_id=msg.author_id,
                                channel_id=msg.channel_id,
                                platform=channel_type_name.lower() if channel_type_name else "unknown",
                                scout=self._scout,
                                respond=_forge_respond,
                            )
                            if scout_handled:
                                return

                if await self._try_stream_channel_message(msg):
                    return

                response = await self.process_message(
                    content=msg.content,
                    author_id=msg.author_id,
                    author_name=msg.author_name,
                    channel_id=msg.channel_id,
                    channel_type_name=self._get_channel_type(msg),
                    media=media,
                    message_metadata=msg.metadata,
                    raw_message=msg.raw,
                )

                if not response:
                    return

                # Collect any pending media (e.g. screenshots) before sending
                pending_media = []
                if hasattr(self, "_pending_media") and msg.channel_id in self._pending_media:
                    pending_media = self._pending_media.pop(msg.channel_id, [])

                # Route response back to the correct adapter
                source_channel = self._get_source_adapter(msg)
                if source_channel and source_channel in self._channels:
                    adapter = self._channels[source_channel]
                    try:
                        await self._send_with_rate_limit(
                            source_channel,
                            adapter,
                            msg.channel_id,
                            response,
                            **self._build_reply_kwargs(msg),
                        )
                        for media_item in pending_media:
                            if media_item.get("type") == "image" and hasattr(adapter, "send_photo"):
                                await adapter.send_photo(msg.channel_id, media_item["data"], caption="")
                        await self._maybe_send_voice_response(source_channel, msg.channel_id, response)
                    except Exception as e:
                        self._logger.error("Failed to send via %s: %s", source_channel, e)
                else:
                    # Fallback: try all channels
                    for name, adapter in self._channels.items():
                        try:
                            await self._send_with_rate_limit(
                                name,
                                adapter,
                                msg.channel_id,
                                response,
                                **self._build_reply_kwargs(msg),
                            )
                            for media_item in pending_media:
                                if media_item.get("type") == "image" and hasattr(adapter, "send_photo"):
                                    await adapter.send_photo(msg.channel_id, media_item["data"], caption="")
                            await self._maybe_send_voice_response(name, msg.channel_id, response)
                            break
                        except Exception:
                            continue

        except Exception as e:
            self._logger.error("Error processing message: %s", e)

    async def _try_stream_channel_message(self, msg: ChannelMessage) -> bool:
        """Attempt streaming delivery; return True if handled."""
        if not self._config.features.streaming_responses:
            return False
        if self._config.security.output_filtering:
            return False

        source_channel = self._get_source_adapter(msg)
        if not source_channel or source_channel not in self._channels:
            return False

        adapter = self._channels[source_channel]
        if not self._provider:
            return False

        try:
            result = await self._build_streaming_response(msg)
            if result is None:
                return False

            token_parts: list[str] = []

            async def token_iterator():
                async for token in result["token_iterator"]:
                    token_parts.append(token)
                    yield token

            await adapter.send_stream(
                msg.channel_id,
                token_iterator(),
                **self._build_reply_kwargs(msg),
                confidence=result["confidence"],
                edit_interval=self._config.features.streaming_edit_interval,
            )

            final_response = "".join(token_parts)
            if not final_response:
                return False

            confidence = result["confidence"]
            if result.get("memory_ctx") is not None:
                envelope = self._deliberate.wrap_streamed_response(
                    final_response,
                    result["memory_ctx"],
                )
                confidence = envelope.confidence
                await self._bus.publish(
                    EventType.REASONING_COMPLETE,
                    {
                        "signal_id": result.get("signal_id", ""),
                        "confidence": confidence,
                        "source": envelope.source,
                        "tool_calls": 0,
                        "iterations": 1,
                    },
                    source="reasoning.deliberate",
                )

            await self._store_interaction(
                msg.content,
                final_response,
                msg.author_name,
                user_id=result["user_id"],
                channel_id=msg.channel_id,
            )
            self._append_history(msg.channel_id, msg.content, final_response)
            await self._post_process(
                msg.content,
                final_response,
                msg.author_name,
                user_id=result["user_id"],
            )
            await self._record_evolution_outcome(
                msg.content,
                envelope if result.get("memory_ctx") is not None else ConfidenceEnvelope(
                    response=final_response,
                    confidence=confidence,
                    source="llm",
                ),
            )
            await self._bus.publish(
                EventType.RESPONSE_READY,
                {
                    "signal_id": result.get("signal_id", ""),
                    "user_id": result["user_id"],
                    "channel_id": msg.channel_id,
                    "platform": self._get_channel_type(msg).lower(),
                    "content": final_response[:200],
                    "confidence": confidence,
                },
                source="gateway",
            )
            await self._maybe_send_voice_response(source_channel, msg.channel_id, final_response)
            return True
        except Exception as exc:
            await self._bus.publish(
                EventType.ERROR,
                {"error": f"Streaming response failed: {exc}", "component": "gateway_stream"},
                source="gateway",
            )
            return False

    async def _build_streaming_response(self, msg: ChannelMessage) -> dict[str, Any] | None:
        """Prepare a streamed response for a simple deliberative path."""
        trust_cfg = self._get_channel_config(msg)
        decision = self._trust.evaluate(trust_cfg, msg)
        if decision.status == "denied":
            return {"token_iterator": self._iter_once(""), "confidence": 0.0, "user_id": ""}
        if decision.status in {"unpaired", "paired"}:
            return {
                "token_iterator": self._iter_once(decision.response or ""),
                "confidence": 1.0,
                "user_id": "",
                "memory_ctx": None,
            }

        channel_type_name = self._get_channel_type(msg)
        channel_type = ChannelType[channel_type_name.upper()] if channel_type_name.upper() in ChannelType.__members__ else ChannelType.CLI
        signal = await self._intake.process(
            content=msg.content,
            author_id=msg.author_id,
            author_name=msg.author_name,
            channel_type=channel_type,
            channel_id=msg.channel_id,
            media=getattr(msg, "media", []) or [],
            metadata=msg.metadata,
        )
        await self._apply_visual_context(signal, msg.content)

        user_model = None
        # Include capability awareness fragments (skip first = persona, already in deliberate reasoner)
        extra_system_sections: list[str] = list(self._default_system_prompt_fragments()[1:])
        if not hasattr(signal, "context") or getattr(signal, "context") is None:
            signal.context = {}
        if self._identity:
            user_model = await self._identity.get_or_create(
                platform=channel_type_name.lower(),
                platform_user_id=msg.author_id,
                display_name=msg.author_name,
            )
            signal.context["user_id"] = user_model.user_id if user_model else signal.author_id
            if self._config.identity.inject_in_prompt and user_model:
                user_section = await self._identity.to_prompt_section(user_model.user_id)
                if user_section:
                    extra_system_sections.append(user_section)
        else:
            signal.context["user_id"] = signal.author_id
        self._apply_prompt_armor_context(signal, extra_system_sections)

        threat = await self._threat_screener.screen(signal)
        if threat.blocked:
            return {
                "token_iterator": self._iter_once(
                    "⚠️ I've detected a potentially harmful request and blocked it for safety. If this was a mistake, try rephrasing."
                ),
                "confidence": 1.0,
                "user_id": user_model.user_id if user_model else "",
                "memory_ctx": None,
            }

        fast_result = await self._fast_path.try_fast_path(signal, memory_ctx=None)
        if fast_result:
            return {
                "token_iterator": self._iter_once(fast_result.content),
                "confidence": fast_result.confidence,
                "user_id": user_model.user_id if user_model else "",
                "memory_ctx": None,
            }

        await self._classifier.classify(signal)
        memory_ctx = await self._retriever.retrieve(msg.content)
        tools = self._skills.get_all_tools() if self._skills.tool_count > 0 else None
        history = self._history.get(msg.channel_id, [])
        persona_mods = self._calibrator.preferences.to_persona_modifiers() if self._calibrator else ""
        if persona_mods:
            extra_system_sections.append(f"## User Style Guidance\n{persona_mods}")

        # Inject active tool awareness so the agent knows what's available right now
        if tools:
            tool_names = [t.name for t in tools]
            extra_system_sections.append(
                f"## Active Tools (this session)\n"
                f"You have {len(tool_names)} tools available: {', '.join(tool_names)}.\n"
                f"Use them proactively when the user's request matches a tool's capability."
            )
            # Extra desktop hint when desktop tools are active
            if any(n.startswith("desktop_") for n in tool_names):
                extra_system_sections.append(
                    "## Desktop Control\n"
                    "The desktop_* tools control the PHYSICAL COMPUTER this agent runs on. "
                    "When the user says 'take a screenshot', 'show my screen', 'click on X', "
                    "'open app Y', or anything about their computer — ALWAYS use the desktop tools. "
                    "The user may be on a phone/remote device, but the tools act on THIS machine."
                )
            extra_system_sections.extend(self._message_runtime_guidance(message_metadata, tool_names))

        use_reflective = (
            self._config.features.reflective_reasoning
            and self._reflective.should_reflect(signal, memory_ctx)
        )
        if use_reflective:
            return None

        token_iterator = self._deliberate.reason_stream(
            signal=signal,
            memory_ctx=memory_ctx,
            tools=tools,
            conversation_history=history[-20:],
            extra_system_sections=extra_system_sections,
        )
        return {
            "token_iterator": token_iterator,
            "confidence": 0.8,
            "user_id": user_model.user_id if user_model else "",
            "memory_ctx": memory_ctx,
            "signal_id": signal.id,
        }

    async def _iter_once(self, text: str):
        if text:
            yield text

    async def process_message(
        self,
        content: str,
        author_id: str = "user",
        author_name: str = "User",
        channel_id: str = "cli",
        channel_type_name: str = "CLI",
        media: list[dict[str, Any]] | None = None,
        message_metadata: dict[str, Any] | None = None,
        raw_message: Any = None,
        include_details: bool = False,
    ) -> str | dict[str, Any]:
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
                return self._build_memory_response_payload("") if include_details else ""
            if decision.status in {"unpaired", "paired"}:
                response = decision.response or ""
                return self._build_memory_response_payload(response) if include_details else response

        if not self._dev_mode:
            cooldown_until = self._security_cooldowns.get(author_id, 0.0)
            now = time.monotonic()
            if cooldown_until > now:
                retry_after = cooldown_until - now
                response = f"Access temporarily blocked for safety. Retry in {retry_after:.0f}s."
                return self._build_memory_response_payload(response) if include_details else response

            allowed, retry_after = self._rate_limiter.check(author_id)
            if not allowed:
                response = (
                    "You're sending messages too quickly. "
                    f"Please wait {retry_after:.0f}s and try again."
                )
                return self._build_memory_response_payload(response) if include_details else response

        await self._apply_memory_retention_if_due()

        # 1. PERCEPTION: Intake
        channel_type = ChannelType[channel_type_name.upper()] if channel_type_name.upper() in ChannelType.__members__ else ChannelType.CLI
        signal = await self._intake.process(
            content=content,
            author_id=author_id,
            author_name=author_name,
            channel_type=channel_type,
            channel_id=channel_id,
            media=media,
            metadata=message_metadata,
        )
        await self._apply_visual_context(signal, content)

        user_model = None
        # Include capability awareness fragments (skip first = persona, already in deliberate reasoner)
        extra_system_sections: list[str] = list(self._default_system_prompt_fragments()[1:])
        if not hasattr(signal, "context") or getattr(signal, "context") is None:
            signal.context = {}
        if self._identity:
            user_model = await self._identity.get_or_create(
                platform=channel_type_name.lower(),
                platform_user_id=author_id,
                display_name=author_name,
            )
            signal.context["user_id"] = user_model.user_id if user_model else signal.author_id
            if (
                self._config.identity.inject_in_prompt
                and user_model
            ):
                user_section = await self._identity.to_prompt_section(user_model.user_id)
                if user_section:
                    extra_system_sections.append(user_section)
        else:
            signal.context["user_id"] = signal.author_id
        self._apply_prompt_armor_context(signal, extra_system_sections)

        # 2. PERCEPTION: Threat screening
        threat = await self._threat_screener.screen(signal)
        if threat.blocked:
            if not self._dev_mode and self._rate_limit_config.security_block_cooldown_seconds > 0:
                self._security_cooldowns[author_id] = (
                    time.monotonic() + self._rate_limit_config.security_block_cooldown_seconds
                )
            await self._bus.publish(
                EventType.INFO,
                {
                    "event": "threat_blocked",
                    "reason": "policy",
                    "signal_id": signal.id,
                },
                source="gateway",
            )
            return "⚠️ I've detected a potentially harmful request and blocked it for safety. If this was a mistake, try rephrasing."

        # 3. REASONING: Try fast path before any DB/memory ops (zero-cost early exit)
        fast_result = await self._fast_path.try_fast_path(signal, memory_ctx=None)
        if fast_result:
            filtered_response = await self._filter_response(fast_result.content, signal)
            await self._store_interaction(
                content,
                filtered_response,
                author_name,
                user_id=user_model.user_id if user_model else "",
                channel_id=channel_id,
            )
            try:
                await self._post_process(
                    content,
                    filtered_response,
                    author_name,
                    user_id=user_model.user_id if user_model else "",
                )
            except Exception:
                pass
            await self._record_evolution_outcome(
                content,
                ConfidenceEnvelope(
                    response=filtered_response,
                    confidence=fast_result.confidence,
                    source=getattr(fast_result, "source", "fast_path"),
                ),
            )
            try:
                await self._bus.publish(
                    EventType.RESPONSE_READY,
                    {
                        "signal_id": signal.id,
                        "user_id": user_model.user_id if user_model else "",
                        "channel_id": channel_id,
                        "platform": channel_type_name.lower(),
                        "content": filtered_response[:200],
                        "confidence": fast_result.confidence,
                    },
                    source="gateway",
                )
            except Exception:
                pass
            if include_details:
                return self._build_memory_response_payload(
                    filtered_response,
                    confidence=fast_result.confidence,
                    confidence_contract={
                        "confidence": fast_result.confidence,
                        "source": "fast_path",
                        "uncertainty_factors": [],
                        "evidence_sources": ["fast_path"],
                        "escalation_recommendation": "none",
                    },
                )
            return filtered_response

        # 4. PERCEPTION: Intent classification (only for non-trivial messages)
        intent_result = await self._classifier.classify(signal)

        # 5. MEMORY: Retrieve context (skipped for fast-path messages above)
        memory_ctx = await self._retriever.retrieve(content)
        await self._bus.publish(
            EventType.CONTEXT_ENRICHED,
            {
                "signal_id": signal.id,
                "user_id": user_model.user_id if user_model else "",
                "channel_id": channel_id,
                "platform": channel_type_name.lower(),
                "memory_hits": len(memory_ctx.episodes) + len(memory_ctx.facts),
            },
            source="gateway",
        )

        # 6. REASONING: Check for procedural memory match (if enabled)
        procedures = await self._procedural.find_matching(content) if self._procedural else []

        # 7. REASONING: Route to reflective or deliberative path
        tools = self._skills.get_all_tools() if self._skills.tool_count > 0 else None
        history = self._history.get(channel_id, [])

        # Add calibrator persona modifiers
        persona_mods = self._calibrator.preferences.to_persona_modifiers() if self._calibrator else ""
        if persona_mods:
            extra_system_sections.append(f"## User Style Guidance\n{persona_mods}")

        # Inject active tool awareness
        if tools:
            tool_names = [t.name for t in tools]
            extra_system_sections.append(
                f"## Active Tools (this session)\n"
                f"You have {len(tool_names)} tools available: {', '.join(tool_names)}.\n"
                f"Use them proactively when the user's request matches a tool's capability."
            )
            # Extra desktop hint when desktop tools are active
            if any(n.startswith("desktop_") for n in tool_names):
                extra_system_sections.append(
                    "## Desktop Control\n"
                    "The desktop_* tools control the PHYSICAL COMPUTER this agent runs on. "
                    "When the user says 'take a screenshot', 'show my screen', 'click on X', "
                    "'open app Y', or anything about their computer — ALWAYS use the desktop tools. "
                    "The user may be on a phone/remote device, but the tools act on THIS machine."
                )
            extra_system_sections.extend(self._message_runtime_guidance(message_metadata, tool_names))

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
                extra_system_sections=extra_system_sections,
            )
        else:
            envelope = await self._deliberate.reason(
                signal=signal,
                memory_ctx=memory_ctx,
                tools=tools,
                conversation_history=history[-20:],
                extra_system_sections=extra_system_sections,
            )
        envelope.response = await self._filter_response(envelope.response, signal)

        # 8. RESPONSE: Store in memory and return
        await self._store_interaction(
            content,
            envelope.response,
            author_name,
            user_id=user_model.user_id if user_model else "",
            channel_id=channel_id,
            metadata=message_metadata,
        )

        self._append_history(channel_id, content, envelope.response)

        # Post-process (metabolism, distiller, calibrator) — never block response
        try:
            await self._post_process(
                content,
                envelope.response,
                author_name,
                user_id=user_model.user_id if user_model else "",
            )
        except Exception as e:
            print(f"[Gateway] Post-process error (non-fatal): {e}")
        await self._record_evolution_outcome(content, envelope)

        # Publish response event — never block response
        try:
            await self._bus.publish(
                EventType.RESPONSE_READY,
                {
                    "signal_id": signal.id,
                    "user_id": user_model.user_id if user_model else "",
                    "channel_id": channel_id,
                    "platform": channel_type_name.lower(),
                    "content": envelope.response[:200],
                    "confidence": envelope.confidence,
                },
                source="gateway",
            )
        except Exception:
            pass

        # Stash media for the caller to pick up (e.g. screenshots to send as photos)
        if envelope.media:
            if not hasattr(self, "_pending_media"):
                self._pending_media = {}
            self._pending_media[channel_id] = envelope.media

        if include_details:
            return self._build_memory_response_payload(
                envelope.response,
                confidence=envelope.confidence,
                memory_ctx=memory_ctx,
                confidence_contract=envelope.to_dict(),
            )
        return envelope.response

    def _score_importance(self, text: str) -> float:
        """Heuristic importance scoring for memory storage."""
        score = 0.5
        lower = text.lower()
        # Personal facts are high importance
        personal_markers = ("my name", "i am", "i work", "i live", "i like", "i prefer",
                           "my job", "my project", "remember that", "don't forget",
                           "important:", "note:", "my email", "my phone", "my address")
        for marker in personal_markers:
            if marker in lower:
                score = max(score, 0.85)
                break
        # Questions about past context
        if any(w in lower for w in ("remember when", "last time", "we discussed", "you said", "earlier")):
            score = max(score, 0.7)
        # Instructions / preferences
        if any(w in lower for w in ("always", "never", "please don't", "from now on", "going forward")):
            score = max(score, 0.75)
        # Code/technical content slightly higher
        if any(w in lower for w in ("def ", "class ", "function", "import ", "```", "error", "bug", "fix")):
            score = max(score, 0.6)
        # Very short messages (greetings) are low importance
        if len(text.split()) <= 3:
            score = min(score, 0.3)
        return round(score, 2)

    async def _store_interaction(
        self,
        user_msg: str,
        agent_msg: str,
        author: str,
        user_id: str = "",
        channel_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store the interaction in episodic memory with smart importance scoring."""
        try:
            user_importance = self._score_importance(user_msg)
            # Agent replies inherit slightly less importance than the user message
            agent_importance = max(0.3, user_importance - 0.1)
            store_reply = self._should_store_agent_reply(agent_msg, metadata=metadata)

            scope_tags = self._build_memory_scope_tags(
                user_id=user_id,
                channel_id=channel_id,
                metadata=metadata,
            )
            user_tags = [tag for tag in (
                f"user_id:{user_id}" if user_id else "",
                f"channel:{channel_id}" if channel_id else "",
                *scope_tags,
            ) if tag]

            await self._episodic.store(
                content=f"{author}: {user_msg}",
                source="conversation",
                author=author,
                importance=user_importance,
                tags=user_tags,
            )
            if store_reply:
                await self._episodic.store(
                    content=f"NeuralClaw: {agent_msg}",
                    source="conversation",
                    author="NeuralClaw",
                    importance=agent_importance,
                    tags=[tag for tag in (
                        f"reply_to_user:{user_id}" if user_id else "",
                        f"channel:{channel_id}" if channel_id else "",
                        *scope_tags,
                    ) if tag],
                )
        except Exception as e:
            await self._bus.publish(
                EventType.ERROR,
                {"error": f"Memory store failed: {e}", "component": "gateway"},
                source="gateway",
            )

    def _looks_like_internal_diagnostic(self, text: str) -> bool:
        lower = str(text or "").lower()
        if not lower.strip():
            return False
        markers = [
            "runtime issue",
            "configuration module",
            "config module",
            "path.home()",
            "home directory",
            "permissions issue",
            "permission issue",
            "environment mismatch",
            "possible causes:",
            "what's happening:",
            "preventing the config from loading properly",
            "check your environment/permissions",
        ]
        hit_count = sum(1 for marker in markers if marker in lower)
        structured = any(token in lower for token in ("possible causes:", "what's happening:", "would you like me to:"))
        return hit_count >= 2 and structured

    def _should_store_agent_reply(
        self,
        agent_msg: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        meta = metadata or {}
        memory_mode = str(meta.get("memory_mode", "") or "").strip().lower()
        if memory_mode in {"volatile", "ephemeral", "skip"}:
            return False
        if bool(meta.get("skip_memory")) or bool(meta.get("internal_diagnostic")):
            return False
        if self._looks_like_internal_diagnostic(agent_msg):
            return False
        return True

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

    def _register_desktop_tools(self) -> None:
        if not self._desktop:
            return
        self._skills.register_tool(
            name="desktop_screenshot",
            description=(
                "Take a screenshot of the computer this agent is running on. "
                "Use this whenever the user asks to see their screen, what's on their desktop, "
                "or asks you to look at something on their computer. "
                "Returns the screenshot as a base64 PNG image."
            ),
            function=self._desktop.screenshot,
            parameters={
                "monitor": {
                    "type": "integer",
                    "description": "Monitor index (0 = primary). Default 0.",
                },
            },
        )
        self._skills.register_tool(
            name="desktop_click",
            description=(
                "Click the mouse at specific pixel coordinates on the host computer's screen. "
                "Use after taking a screenshot to interact with UI elements."
            ),
            function=self._desktop.click,
            parameters={
                "x": {"type": "integer", "description": "Horizontal pixel coordinate."},
                "y": {"type": "integer", "description": "Vertical pixel coordinate."},
                "button": {
                    "type": "string",
                    "description": "Mouse button: left, right, or middle.",
                    "enum": ["left", "right", "middle"],
                },
                "clicks": {"type": "integer", "description": "Number of clicks (1=single, 2=double)."},
            },
        )
        self._skills.register_tool(
            name="desktop_type",
            description=(
                "Type text using the keyboard on the host computer. "
                "Use after clicking on a text field to enter text."
            ),
            function=self._desktop.type_text,
            parameters={
                "text": {"type": "string", "description": "Text to type."},
                "interval": {
                    "type": "number",
                    "description": "Delay between keystrokes in seconds. Default 0.05.",
                },
            },
        )
        self._skills.register_tool(
            name="desktop_hotkey",
            description=(
                "Press a keyboard shortcut on the host computer. "
                "Examples: ['ctrl', 'c'] for copy, ['ctrl', 'v'] for paste, "
                "['alt', 'tab'] to switch windows, ['ctrl', 's'] to save."
            ),
            function=self._desktop_hotkey_tool,
            parameters={
                "keys": {
                    "type": "array",
                    "description": "Keys to press together, e.g. ['ctrl', 'c'].",
                    "items": {"type": "string"},
                },
            },
        )
        self._skills.register_tool(
            name="desktop_get_clipboard",
            description="Read the current clipboard text from the host computer.",
            function=self._desktop.get_clipboard,
        )
        self._skills.register_tool(
            name="desktop_set_clipboard",
            description="Write text to the host computer's clipboard.",
            function=self._desktop.set_clipboard,
            parameters={
                "text": {"type": "string", "description": "Text to put on the clipboard."},
            },
        )
        self._skills.register_tool(
            name="desktop_run_app",
            description=(
                "Launch an application on the host computer. "
                "Use to open Notepad, Calculator, browser, etc."
            ),
            function=self._desktop.run_app,
            parameters={
                "app": {"type": "string", "description": "Application name or path (e.g. 'notepad', 'calc', 'mspaint')."},
                "args": {
                    "type": "array",
                    "description": "Optional command-line arguments.",
                    "items": {"type": "string"},
                },
            },
        )

    async def _desktop_hotkey_tool(self, keys: list[str]) -> dict[str, Any]:
        if not self._desktop:
            return {"error": "Desktop control is not available."}
        return await self._desktop.hotkey(*keys)

    def _register_browser_tools(self) -> None:
        if not self._browser:
            return
        self._skills.register_tool(
            name="browser_navigate",
            description="Navigate the browser to a URL.",
            function=self._browser.navigate,
            parameters={"url": {"type": "string", "description": "Target URL."}},
        )
        self._skills.register_tool(
            name="browser_screenshot",
            description="Capture the current browser viewport and page snapshot.",
            function=self._browser.screenshot,
            parameters={},
        )
        self._skills.register_tool(
            name="browser_click",
            description="Click an element by CSS/XPath selector or natural-language description.",
            function=self._browser.click,
            parameters={"selector": {"type": "string", "description": "Element selector or description."}},
        )
        self._skills.register_tool(
            name="browser_type",
            description="Type text into a field by selector or natural-language description.",
            function=self._browser.type_text,
            parameters={
                "selector": {"type": "string", "description": "Field selector or description."},
                "text": {"type": "string", "description": "Text to type."},
            },
        )
        self._skills.register_tool(
            name="browser_scroll",
            description="Scroll the current page up or down.",
            function=self._browser.scroll,
            parameters={
                "direction": {"type": "string", "description": "Scroll direction.", "enum": ["up", "down"]},
                "amount": {"type": "integer", "description": "Relative scroll amount."},
            },
        )
        self._skills.register_tool(
            name="browser_extract",
            description="Extract information from the current page.",
            function=self._browser.extract,
            parameters={"query": {"type": "string", "description": "What to extract from the page."}},
        )
        self._skills.register_tool(
            name="browser_execute_js",
            description="Execute JavaScript in the active page when enabled by config.",
            function=self._browser.execute_js,
            parameters={"code": {"type": "string", "description": "JavaScript expression or function body."}},
        )
        self._skills.register_tool(
            name="browser_wait_for",
            description="Wait for a selector or loading condition in the current page.",
            function=self._browser.wait_for,
            parameters={
                "condition": {"type": "string", "description": "Selector or wait condition."},
                "timeout": {"type": "integer", "description": "Timeout in seconds."},
            },
        )
        self._skills.register_tool(
            name="browser_act",
            description="Run a bounded browser task against the active session.",
            function=self._browser.act,
            parameters={
                "task": {"type": "string", "description": "Natural-language browser task."},
                "url": {"type": "string", "description": "Optional starting URL."},
                "max_steps": {"type": "integer", "description": "Maximum number of steps."},
            },
        )
        self._skills.register_tool(
            name="chrome_summarize",
            description="Use Chrome AI summarization when enabled.",
            function=self._browser.chrome_summarize,
            parameters={"selector": {"type": "string", "description": "Selector to summarize."}},
        )
        self._skills.register_tool(
            name="chrome_translate",
            description="Use Chrome AI translation when enabled.",
            function=self._browser.chrome_translate,
            parameters={
                "text": {"type": "string", "description": "Text to translate."},
                "target_lang": {"type": "string", "description": "Target language code."},
            },
        )
        self._skills.register_tool(
            name="chrome_prompt",
            description="Use Chrome AI prompt APIs when enabled.",
            function=self._browser.chrome_prompt,
            parameters={
                "prompt": {"type": "string", "description": "Prompt to send."},
                "context_selector": {"type": "string", "description": "Optional selector for extra page context."},
            },
        )

    def _default_system_prompt_fragments(self) -> list[str]:
        fragments = [self._config.persona]
        config_line = (
            f"Your runtime configuration file is {self._config_path}."
            if self._config_path
            else "Your runtime configuration is managed by the local NeuralClaw gateway."
        )

        # Dynamic self-awareness: build capabilities section from what's actually enabled
        feat = self._config.features
        caps: list[str] = []
        caps.append("You have persistent memory — you remember past conversations, learn user preferences, and build a knowledge graph of facts over time.")
        if feat.vector_memory:
            caps.append("You have semantic similarity search across all past interactions.")
        if feat.identity:
            caps.append("You track per-user identity, expertise domains, communication style, and active projects.")
        if feat.vision:
            caps.append("You can analyze images/photos sent to you.")
        if feat.evolution:
            caps.append("You self-evolve: after every ~50 interactions you distill patterns into permanent knowledge and refine your behavior.")
        if self._config.security.allow_shell_execution:
            caps.append("You can execute Python code in a sandbox, clone GitHub repos, install dependencies, and run scripts/tests.")
        else:
            caps.append("Code execution is available but currently disabled by the admin. You can explain code and help with programming, but cannot run it.")
        if getattr(self, "_browser", None):
            caps.append("You can browse web pages, extract content, and execute JavaScript.")
        if getattr(self, "_desktop", None):
            caps.append(
                "You are running on the user's local computer. You can control THIS machine's "
                "screen, mouse, keyboard, and clipboard using the desktop_* tools. When users ask "
                "to see their screen, take a screenshot, click something, type something, or "
                "interact with their computer in any way, use the desktop tools — they control "
                "the physical machine you're running on, even if the user is messaging from a "
                "remote device like a phone via Telegram."
            )
            if bool(getattr(self._config.desktop, "autonomous_execution", False)):
                caps.append(
                    "Desktop autonomous execution is enabled. When the user asks you to operate the desktop app or this machine and the tools allow it, execute the actions directly instead of only describing them."
                )
            else:
                caps.append(
                    "Desktop autonomous execution is disabled. You may inspect desktop state, but explicit desktop operations should remain conservative unless the user enables the autonomy toggle in Settings."
                )
        if self._config.google_workspace.enabled:
            caps.append("You have Google Workspace access (Gmail, Calendar, Drive, Docs, Sheets).")
        if self._config.microsoft365.enabled:
            caps.append("You have Microsoft 365 access (Outlook, Calendar, Teams, OneDrive).")
        if self._config.tts.enabled:
            caps.append("You can generate voice/speech audio responses.")
        if feat.reflective_reasoning:
            caps.append("For complex multi-step problems, you use reflective reasoning (think step-by-step, critique, and refine).")
        roles_enabled = bool(getattr(self._config.model_roles, "enabled", False))
        role_summary: list[str] = []
        for role_name in ("primary", "fast", "micro"):
            model_name = str(getattr(self._config.model_roles, role_name, "") or "").strip()
            if model_name:
                role_summary.append(f"{role_name}={model_name}")
        if role_summary:
            if roles_enabled:
                caps.append("Role-based local model routing is enabled: " + ", ".join(role_summary) + ".")
            else:
                caps.append(
                    "Role-based local model routing is configured but currently disabled: "
                    + ", ".join(role_summary)
                    + ". Distinguish clearly between configured roles and active routing when asked."
                )

        capabilities_section = (
            f"## About You\n"
            f"You are {self._config.name}, a self-evolving cognitive AI agent running on the NeuralClaw framework.\n"
            "You are not OpenClaw. OpenClaw is only a legacy migration source and must never be used as your current identity.\n"
            f"{config_line}\n\n"
            f"## Your Active Capabilities\n"
            + "\n".join(f"- {c}" for c in caps)
            + "\n"
        )
        fragments.append(capabilities_section)

        fragments.append(
            "## Guidelines\n"
            "- ALWAYS use your tools when the user's request matches a tool's purpose. "
            "NEVER say 'I can't' or 'I'm unable to' when you have a tool that can do it.\n"
            "- Identify yourself as NeuralClaw or by your configured agent name on the NeuralClaw framework. "
            "Do not call yourself OpenClaw unless the user is explicitly asking about migration from a legacy installation.\n"
            "- If shell, code execution, browser, or desktop tools are available, you may change your own local configuration, "
            "restart services, and verify the result instead of only describing the steps.\n"
            "- If the user asks you to change your provider, channels, memory, desktop control, or other runtime settings, "
            "prefer making the change directly when your currently available tools permit it.\n"
            "- If past memory/conversation shows you previously said you couldn't do something, "
            "IGNORE that — your capabilities may have changed. Always check your current tool list.\n"
            "- Do not stop at 'I have a plan' when tools or config access can carry the task forward. "
            "Execute the next real step, then continue until blocked or complete.\n"
            "- Do not ask 'would you like me to do X?' when X is already clearly requested and within your available tools. "
            "Do it, then report the result. Only ask when a real user choice or approval is required.\n"
            "- For capability or configuration questions, inspect the live runtime state and answer precisely. "
            "If something is configured but disabled, state both facts explicitly.\n"
            "- Reference your memory when relevant to the conversation.\n"
            "- If uncertain, say so. If a tool can verify, use it first.\n"
            "- Be concise but thorough. Adapt your style to the user.\n"
        )
        fragments.append(self._framework_knowledge_fragment())
        fragments.append(self._desktop_app_fragment())
        return fragments

    def _framework_knowledge_fragment(self) -> str:
        """
        Build a system prompt section describing the framework's directory
        layout, how to write skills, and how to extend capabilities.

        All paths are derived from live config — never hardcoded.
        """
        from neuralclaw.config import CONFIG_DIR, DATA_DIR, LOG_DIR
        from neuralclaw.skills.paths import resolve_user_skills_dir

        skills_dir = resolve_user_skills_dir(getattr(self._config.forge, "user_skills_dir", None))
        repos_dir = Path(self._config.workspace.repos_dir).expanduser()
        apps_dir = Path(self._config.workspace.apps_dir).expanduser()

        skill_template = (
            "from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter\n"
            "\n"
            "async def my_tool(param: str, **kwargs) -> dict:\n"
            "    return {\"result\": param}\n"
            "\n"
            "def get_manifest() -> SkillManifest:\n"
            "    return SkillManifest(\n"
            "        name=\"my_skill\",\n"
            "        description=\"What this skill does\",\n"
            "        tools=[\n"
            "            ToolDefinition(\n"
            "                name=\"my_tool\",\n"
            "                description=\"What this tool does\",\n"
            "                parameters=[ToolParameter(name=\"param\", type=\"string\", description=\"...\")],\n"
            "                handler=my_tool,\n"
            "            )\n"
            "        ],\n"
            "    )"
        )

        return (
            "## NeuralClaw Framework Layout\n"
            f"Config home:   {CONFIG_DIR}\n"
            f"Config file:   {CONFIG_DIR}/config.toml  ← edit to change providers, features, channels\n"
            f"User skills:   {skills_dir}  ← drop .py files here; hot-reloaded within ~3 s\n"
            f"Repos:         {repos_dir}  ← git repos cloned via github_repos skill\n"
            f"App projects:  {apps_dir}  ← scaffolded projects (use scaffold_project tool)\n"
            f"Data/DBs:      {DATA_DIR}  ← memory.db, agents.db, tasks.db (do not edit directly)\n"
            f"Logs:          {LOG_DIR}\n"
            "\n"
            "## Writing a New Skill\n"
            f"1. Create a .py file in:  {skills_dir}/my_skill.py\n"
            "2. The file MUST export:  get_manifest() -> SkillManifest\n"
            "3. Every tool handler MUST be async def\n"
            "4. Use get_skill_template tool for a full ready-to-paste template\n"
            "\n"
            "Minimal skill template:\n"
            "```python\n"
            f"{skill_template}\n"
            "```\n"
            "\n"
            "## Self-Extension Quick Reference\n"
            "- **Add a new tool**: write a skill .py to the user skills dir above, or use forge_skill\n"
            "- **Integrate an API**: use forge_skill with the API docs URL, or write an api_client-style skill\n"
            "- **Create a project from scratch**: use scaffold_project tool (templates: python-service, fastapi, cli-tool, data-pipeline, agent-skill)\n"
            "- **See all available skills**: use list_available_skills tool\n"
            "- **See active agents**: use get_active_agents tool\n"
            "- **Avoid workspace conflicts with other agents**: use claim_workspace_dir before writing to a shared directory\n"
            "- **Read AGENTS.md** files in any directory you explore — they explain what's there and how to work with it\n"
        )

    def _desktop_app_fragment(self) -> str:
        desktop_state = "enabled" if bool(getattr(self._config.desktop, "enabled", False) and getattr(self._config.features, "desktop", False)) else "disabled"
        autonomy_state = "enabled" if bool(getattr(self._config.desktop, "autonomous_execution", False)) else "disabled"
        return (
            "## NeuralClaw Desktop App\n"
            "You may be operating inside the NeuralClaw Desktop app (Tauri + React). "
            "Key surfaces include Dashboard, Tasks, Agents, Chat, Settings, Memory, Knowledge, Connections, and Workspace.\n"
            f"Desktop control is currently {desktop_state}. Desktop autonomous execution is currently {autonomy_state}.\n"
            "If the user asks you to change desktop app settings, switch models/providers, manage sessions, inspect the operator brief, or act on the local machine, prefer doing it through the live tools and runtime state instead of answering from assumptions.\n"
        )

    def _message_runtime_guidance(self, metadata: dict[str, Any] | None, tool_names: list[str]) -> list[str]:
        guidance: list[str] = []
        info = metadata if isinstance(metadata, dict) else {}
        autonomy_mode = self._default_autonomy_mode(str(info.get("autonomy_mode", "") or ""))
        if autonomy_mode:
            guidance.append(
                "## Session Autonomy Policy\n"
                f"Current autonomy mode: {autonomy_mode}.\n"
                + (
                    "Execute requested actions directly when tools allow it, especially for desktop-app and local-machine tasks."
                    if autonomy_mode == "policy-driven-autonomous"
                    else "Stay proactive, but escalate or ask only when a real approval boundary still exists."
                )
            )
        if any(name.startswith("desktop_") for name in tool_names):
            desktop_enabled = bool(getattr(self._config.desktop, "enabled", False) and getattr(self._config.features, "desktop", False))
            guidance.append(
                "## Live Desktop Context\n"
                f"Desktop tools are {'available' if desktop_enabled else 'not active'} in this runtime. "
                "The NeuralClaw Desktop app can be controlled through the available desktop tools on this machine."
            )
        return guidance

    def _apply_prompt_armor_context(
        self,
        signal: Signal,
        extra_system_sections: list[str],
    ) -> None:
        if not hasattr(signal, "context") or getattr(signal, "context") is None:
            signal.context = {}
        signal.context["system_prompt_fragments"] = self._default_system_prompt_fragments()
        if self._canary_token:
            signal.context["canary_token"] = self._canary_token
            extra_system_sections.append(f"<!-- {self._canary_token} -->")

    async def _apply_visual_context(self, signal: Signal, user_query: str) -> None:
        if not self._vision or not signal.media:
            return

        contexts: list[str] = []
        for media_item in signal.media:
            try:
                visual_context = await self._vision.process_media(media_item, user_query)
            except Exception as exc:
                await self._bus.publish(
                    EventType.ERROR,
                    {
                        "component": "gateway_visual_context",
                        "operation": "process_media",
                        "error": str(exc),
                    },
                    source="gateway",
                )
                continue
            if visual_context:
                contexts.append(visual_context)

        if not contexts:
            return

        visual_section = "## Visual Context\n" + "\n\n".join(contexts)
        signal.content = f"{visual_section}\n\n## User Message\n{signal.content}".strip()
        if not hasattr(signal, "context") or getattr(signal, "context") is None:
            signal.context = {}
        signal.context["visual_context"] = contexts

    async def _maybe_send_voice_response(self, source_channel: str | None, channel_id: str, response: str) -> None:
        if not source_channel or source_channel != "discord":
            return
        if not self._config.features.voice or not self._config.tts.enabled:
            return

        discord_cfg = next((ch for ch in self._config.channels if ch.name == "discord"), None)
        if not discord_cfg:
            return
        if not (discord_cfg.extra.get("voice_responses") or self._config.tts.auto_speak):
            return

        adapter = self._channels.get("discord")
        if not adapter or not hasattr(adapter, "speak"):
            return

        try:
            from neuralclaw.skills.builtins import tts as _tts

            result = await _tts.speak(response)
            if result.get("error"):
                return
            await adapter.speak(
                result["audio_path"],
                channel_id=discord_cfg.extra.get("voice_channel_id") or channel_id,
            )
        except Exception as exc:
            await self._bus.publish(
                EventType.ERROR,
                {"component": "gateway_voice", "error": str(exc)},
                source="gateway",
            )

    async def _filter_response(self, response: str, signal: Signal) -> str:
        if not self._output_filter:
            return response
        result = await self._output_filter.screen(response, signal)
        return result.response

    def _append_history(self, channel_id: str, user_content: str, assistant_content: str) -> None:
        if channel_id not in self._history:
            self._history[channel_id] = []
        self._history[channel_id].append({"role": "user", "content": user_content})
        self._history[channel_id].append({"role": "assistant", "content": assistant_content})
        if len(self._history[channel_id]) > 20:
            self._history[channel_id] = self._history[channel_id][-20:]

    async def _post_process(
        self,
        user_msg: str,
        agent_msg: str,
        author: str,
        user_id: str = "",
    ) -> None:
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
            if self._identity and user_id:
                prefs = self._calibrator.preferences
                await self._identity.update(
                    user_id,
                    {
                        "communication_style": {
                            "formality": prefs.formality,
                            "verbosity": prefs.verbosity,
                            "proactiveness": prefs.proactiveness,
                            "emoji_usage": prefs.emoji_usage,
                        },
                        "preferences": {
                            "custom_rules": prefs.custom_rules,
                            "code_style": prefs.code_style,
                        },
                        "timezone": prefs.timezone,
                    },
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
                if self._identity and user_id:
                    await self._identity.synthesize_model(user_id)
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

    async def _record_evolution_outcome(
        self,
        user_msg: str,
        envelope: ConfidenceEnvelope,
    ) -> None:
        """Let the evolution orchestrator observe live capability gaps."""
        if not self._evolution_orchestrator:
            return
        try:
            await self._evolution_orchestrator.record_response(user_msg, envelope)
        except Exception as e:
            await self._bus.publish(
                EventType.ERROR,
                {"error": f"Evolution orchestration failed: {e}", "component": "evolution"},
                source="gateway",
            )

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Start the gateway (all channels + bus)."""
        self._running = True
        await self.initialize()
        self._setup_signal_handlers()
        self._gc_task = asyncio.create_task(self._gc_loop())

        # Start dashboard early so health endpoints are available during startup.
        if self._dashboard:
            try:
                await self._dashboard.start()
            except Exception as e:
                self._logger.error("Dashboard failed to start: %s", e)

        # Start MCP Server
        if self._mcp_server:
            try:
                await self._mcp_server.start()
            except Exception as e:
                self._logger.error("MCP Server failed to start: %s", e)

        if self._dev_mode and self._config_path:
            self._config_watch_task = asyncio.create_task(self._watch_config())

        await self._run_startup_readiness()
        await self._start_channels()
        
        # Start adaptive observers
        if getattr(self, "_adaptive", None):
            self._bus.subscribe_all(self._on_adaptive_bus_event)
            if getattr(self, "_routine_scheduler", None):
                await self._routine_scheduler.start()

        # Write AGENTS.md orientation files to key directories (idempotent)
        try:
            _ensure_agents_md(self._config)
        except Exception as _e:
            self._logger.debug("Could not write AGENTS.md files: %s", _e)

        print(f"\n🧠 {self._config.name} Gateway is running (Phase 3: Swarm)")
        print(f"   Provider: {self._provider.name if self._provider else 'NONE'}")
        if self._role_router:
            print(f"   Role Router: {self._role_router.model_map}")
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
        print(f"   RAG: {'enabled' if feat.rag else 'disabled'}")
        print(f"   Workflow Engine: {'enabled' if feat.workflow_engine else 'disabled'}")
        if self._mcp_server:
            print(f"   MCP Server: port {self._config.mcp_server.port}")
        if self._spawner:
            print(f"   Spawner: {self._spawner.count} agents")
        print()

    async def stop(self) -> None:
        """Gracefully stop the gateway."""
        self._running = False
        if self._config_watch_task:
            self._config_watch_task.cancel()
            try:
                await self._config_watch_task
            except asyncio.CancelledError:
                pass
        if self._kb_auto_index_task:
            self._kb_auto_index_task.cancel()
            try:
                await self._kb_auto_index_task
            except asyncio.CancelledError:
                pass
        
        if getattr(self, "_adaptive", None) and getattr(self, "_routine_scheduler", None):
            await self._routine_scheduler.stop()
            
        if self._gc_task:
            self._gc_task.cancel()
            try:
                await self._gc_task
            except asyncio.CancelledError:
                pass
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
        if self._mcp_server:
            await self._mcp_server.stop()
        if self._dashboard:
            await self._dashboard.stop()
        if self._channel_pairing_adapters:
            for channel_name in list(self._channel_pairing_adapters.keys()):
                await self._stop_channel_pairing(channel_name)
        await self._telemetry.stop()
        await self._bus.stop()
        await self._episodic.close()
        await self._semantic.close()
        if self._identity:
            await self._identity.close()
        if self._traceline:
            await self._traceline.close()
        if self._vector_memory:
            await self._vector_memory.close()
        if self._knowledge_base:
            await self._knowledge_base.close()
        if self._workflow_engine:
            await self._workflow_engine.close()
        if self._browser:
            await self._browser.stop()
        if self._procedural:
            await self._procedural.close()
        if self._calibrator:
            await self._calibrator.close()
        if self._evolution_orchestrator:
            await self._evolution_orchestrator.close()
        if self._agent_store:
            await self._agent_store.close()
        if self._task_store:
            await self._task_store.close()
        if self._shared_bridge:
            await self._shared_bridge.close()
        await self._audit.close()
        await self._idempotency.close()
        await self._checkpoint.close()
        await self._memory_db_pool.close()
        if self._traceline:
            await self._trace_db_pool.close()
        print("\n🧠 NeuralClaw Gateway stopped.")

    def _get_dashboard_stats(self) -> dict[str, Any]:
        """Provide stats for the dashboard."""
        active_provider = self._provider.name if self._provider else "none"
        configured_primary = self._config.primary_provider.name if self._config.primary_provider else "none"
        active_model = str(
            getattr(self._provider, "model", "")
            or getattr(self._config.primary_provider, "model", "")
            or getattr(self._config.model_roles, "primary", "")
            or ""
        ).strip()
        active_base_url = str(
            getattr(self._provider, "base_url", "")
            or getattr(self._config.primary_provider, "base_url", "")
            or ""
        ).strip()
        event_count = len(self._bus.get_event_log(limit=200))
        return {
            "provider": active_provider,
            "active_provider": active_provider,
            "configured_primary_provider": configured_primary,
            "active_model": active_model,
            "active_base_url": active_base_url,
            "interactions": sum(
                r.total for r in self._meta_cognitive._performance.values()
            ) if self._meta_cognitive else 0,
            "success_rate": self._meta_cognitive.get_performance_summary().get(
                "success_rate", 1.0
            ) if self._meta_cognitive else 1.0,
            "skills": self._skills.count,
            "channels": ", ".join(self._channels.keys()) or "none",
            "readiness": self._startup_readiness.value,
            "circuits": self._provider.get_circuit_states() if self._provider else {},
            "event_count": event_count,
            "trace_available": bool(self._traceline),
            "adaptive_ready": bool(self._adaptive),
            "operator_ready": bool(self._adaptive),
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
        vector_count = await self._vector_memory.count() if self._vector_memory else 0
        identity_count = await self._identity.count() if self._identity else 0
        return {
            "episodic_count": episodic_count,
            "semantic_count": semantic_count,
            "procedural_count": procedural_count,
            "vector_count": vector_count,
            "identity_count": identity_count,
        }

    def _get_dashboard_bus(self) -> list[dict[str, Any]]:
        """Provide recent bus events for the dashboard."""
        events = self._bus.get_event_log(limit=80)
        def _event_level(name: str) -> str:
            upper = name.upper()
            if "ERROR" in upper or "DENIED" in upper:
                return "error"
            if "COMPLETE" in upper or "READY" in upper or "SENT" in upper:
                return "success"
            if "START" in upper or "REQUEST" in upper or "PAUSE" in upper:
                return "warning"
            return "info"

        def _preview_payload(payload: dict[str, Any]) -> str:
            priority_keys = (
                "status",
                "action",
                "task_id",
                "workflow_id",
                "agent",
                "provider",
                "model",
                "port",
                "error",
                "detail",
                "message",
            )
            parts: list[str] = []
            for key in priority_keys:
                value = payload.get(key)
                if value is None or value == "":
                    continue
                parts.append(f"{key}: {value}")
            if not parts:
                parts.append(str(payload))
            return " · ".join(parts)[:220]

        return [
            {
                "id": e.id,
                "type": e.type.name,
                "source": e.source,
                "timestamp": e.timestamp,
                "correlation_id": e.correlation_id,
                "level": _event_level(e.type.name),
                "data_preview": _preview_payload(e.data),
            }
            for e in events
        ]

    async def _get_dashboard_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._traceline:
            return []
        traces = await self._traceline.query_traces(limit=limit)
        items: list[dict[str, Any]] = []
        for trace in traces:
            category = str(getattr(trace, "reasoning_path", "") or "reasoning").split(":", 1)[0].strip().lower() or "reasoning"
            output_preview = str(getattr(trace, "output_preview", "") or "").strip()
            input_preview = str(getattr(trace, "input_preview", "") or "").strip()
            message = output_preview or input_preview or f"Trace {getattr(trace, 'trace_id', '')}"
            items.append({
                "trace_id": trace.trace_id,
                "category": category,
                "message": message[:280],
                "timestamp": trace.timestamp,
                "reasoning_path": trace.reasoning_path,
                "input_preview": trace.input_preview,
                "output_preview": trace.output_preview,
                "total_tool_calls": trace.total_tool_calls,
                "duration_ms": trace.duration_ms,
                "confidence": trace.confidence,
                "error": trace.error,
            })
        return items

    async def _get_dashboard_trace(self, trace_id: str) -> dict[str, Any] | None:
        if not self._traceline:
            return None
        trace = await self._traceline.get_trace(trace_id)
        return self._trace_to_dict(trace) if trace else None

    async def _get_dashboard_metrics(self) -> dict[str, Any]:
        traceline_metrics = await self._traceline.get_metrics() if self._traceline else {}
        return {
            **traceline_metrics,
            "provider": self._provider.name if self._provider else "none",
            "readiness": self._startup_readiness.value,
            "circuits": self._provider.get_circuit_states() if self._provider else {},
        }

    def _get_dashboard_config(self) -> dict[str, Any]:
        payload = self._sanitize_config_value(self._config._raw)
        providers = payload.get("providers", {})
        if isinstance(providers, dict):
            for provider_name, provider_cfg in providers.items():
                if provider_name in {"primary", "fallback"} or not isinstance(provider_cfg, dict):
                    continue
                provider_cfg["api_key_configured"] = bool(get_api_key(provider_name))
        payload["dashboard_host"] = self._config.dashboard_host
        payload["dashboard_port"] = self._config.dashboard_port
        payload["dashboard_auth_configured"] = bool(get_dashboard_auth_token())
        payload["version"] = __version__
        return payload

    def _get_dashboard_channels(self) -> list[dict[str, Any]]:
        current = {ch.name: ch for ch in self._config.channels}
        raw_channels = self._config._raw.get("channels", {})
        order = ["telegram", "discord", "slack", "whatsapp", "signal"]
        labels = {
            "telegram": "Telegram",
            "discord": "Discord",
            "slack": "Slack",
            "whatsapp": "WhatsApp",
            "signal": "Signal",
        }
        descriptions = {
            "telegram": "Bot token for Telegram Bot API conversations.",
            "discord": "Bot token plus optional voice settings for Discord servers.",
            "slack": "Slack Socket Mode bot with bot token and app token.",
            "whatsapp": "Baileys multi-file auth directory for WhatsApp pairing.",
            "signal": "Registered Signal phone number for signal-cli.",
        }
        snapshots: list[dict[str, Any]] = []

        for name in order:
            cfg = current.get(name)
            raw = raw_channels.get(name, {}) if isinstance(raw_channels, dict) else {}
            extra = dict(cfg.extra if cfg else raw if isinstance(raw, dict) else {})
            candidate_extra = self._channel_extra_snapshot(name, extra)
            token_present = bool(cfg.token) if cfg else self._channel_has_secret(name)
            token_value = str((cfg.token if cfg else "") or get_api_key(name) or "").strip()
            validation_errors = self._channel_validate(name, token=token_value, extra=candidate_extra)
            configured = self._channel_configured(name, cfg, candidate_extra, token_present=token_present)
            ready = self._channel_ready(name, cfg, candidate_extra, token_present=token_present)
            paired = self._channel_paired(name, candidate_extra)
            status, status_detail = self._channel_status_snapshot(
                name,
                configured=configured,
                ready=ready,
                running=name in self._channels,
                paired=paired,
                validation_errors=validation_errors,
            )
            snapshots.append({
                "name": name,
                "label": labels[name],
                "description": descriptions[name],
                "enabled": bool(cfg.enabled) if cfg else bool(raw.get("enabled", False)),
                "configured": configured,
                "ready": ready,
                "paired": paired,
                "status": status,
                "status_detail": status_detail,
                "can_enable": ready,
                "running": name in self._channels,
                "trust_mode": str((cfg.trust_mode if cfg else raw.get("trust_mode", "")) or ""),
                "token_present": token_present,
                "restart_required": True,
                "validation_errors": validation_errors,
                "fields": self._channel_field_specs(name),
                "extra": candidate_extra,
            })

        return snapshots

    def _get_dashboard_skills(self) -> list[dict[str, Any]]:
        skills: list[dict[str, Any]] = []
        for manifest in self._skills.list_skills():
            skills.append(
                {
                    "name": manifest.name,
                    "description": manifest.description,
                    "version": manifest.version,
                    "tool_count": len(manifest.tools),
                    "capabilities": [cap.name for cap in manifest.capabilities],
                }
            )
        return skills

    def _trace_to_dict(self, trace: Any) -> dict[str, Any]:
        return {
            "trace_id": trace.trace_id,
            "request_id": trace.request_id,
            "user_id": trace.user_id,
            "channel": trace.channel,
            "platform": trace.platform,
            "input_preview": trace.input_preview,
            "output_preview": trace.output_preview,
            "confidence": trace.confidence,
            "reasoning_path": trace.reasoning_path,
            "threat_score": trace.threat_score,
            "memory_hits": trace.memory_hits,
            "tool_calls": [
                {
                    "tool": call.tool,
                    "args_preview": call.args_preview,
                    "result_preview": call.result_preview,
                    "duration_ms": call.duration_ms,
                    "success": call.success,
                    "idempotency_key": call.idempotency_key,
                }
                for call in trace.tool_calls
            ],
            "total_tool_calls": trace.total_tool_calls,
            "tokens_used": trace.tokens_used,
            "cost_usd": trace.cost_usd,
            "duration_ms": trace.duration_ms,
            "timestamp": trace.timestamp,
            "error": trace.error,
            "tags": trace.tags,
        }

    def _sanitize_config_value(self, value: Any, key: str = "") -> Any:
        secret_markers = ("key", "token", "secret", "password", "cookie", "session")
        lowered = key.lower()
        if any(marker in lowered for marker in secret_markers):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {
                item_key: self._sanitize_config_value(item_value, item_key)
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [self._sanitize_config_value(item, key) for item in value]
        return value

    def _channel_has_secret(self, channel_name: str) -> bool:
        secret_names = [channel_name]
        if channel_name == "slack":
            secret_names.append("slack_app")
        return any(bool(get_api_key(secret_name)) for secret_name in secret_names)

    def _channel_field_specs(self, channel_name: str) -> list[dict[str, Any]]:
        if channel_name == "telegram":
            return [
                {
                    "key": "secret",
                    "label": "Bot Token",
                    "kind": "secret",
                    "placeholder": "123456:ABCDEF...",
                    "description": "Telegram Bot API token from BotFather.",
                    "required": True,
                },
                {
                    "key": "default_chat_id",
                    "label": "Default Chat ID",
                    "kind": "text",
                    "placeholder": "-1001234567890 or @channelusername",
                    "description": "Target chat_id or @channelusername used for outbound sends.",
                    "required": False,
                },
            ]
        if channel_name == "discord":
            return [
                {
                    "key": "secret",
                    "label": "Bot Token",
                    "kind": "secret",
                    "placeholder": "discord-bot-token",
                    "description": "Discord bot token from the Developer Portal.",
                    "required": True,
                },
                {
                    "key": "guild_id",
                    "label": "Server ID",
                    "kind": "text",
                    "placeholder": "123456789012345678",
                    "description": "Optional default guild/server for agent actions and send targets.",
                    "required": False,
                },
                {
                    "key": "text_channel_id",
                    "label": "Default Text Channel ID",
                    "kind": "text",
                    "placeholder": "123456789012345678",
                    "description": "Optional default text channel for outbound replies or notifications.",
                    "required": False,
                },
                {
                    "key": "voice_channel_id",
                    "label": "Voice Channel ID",
                    "kind": "text",
                    "placeholder": "123456789012345678",
                    "description": "Voice channel to join when spoken responses are enabled.",
                    "required": False,
                },
                {
                    "key": "voice_responses",
                    "label": "Voice Responses",
                    "kind": "boolean",
                    "description": "Speak answers into a configured Discord voice channel.",
                    "required": False,
                },
                {
                    "key": "auto_disconnect_empty_vc",
                    "label": "Auto Disconnect Empty VC",
                    "kind": "boolean",
                    "description": "Leave voice automatically when no non-bot users remain.",
                    "required": False,
                },
            ]
        if channel_name == "slack":
            return [
                {
                    "key": "secret",
                    "label": "Bot Token",
                    "kind": "secret",
                    "placeholder": "xoxb-...",
                    "description": "Bot user OAuth token used for Web API access.",
                    "required": True,
                },
                {
                    "key": "slack_app",
                    "label": "App Token",
                    "kind": "secret-extra",
                    "placeholder": "xapp-...",
                    "description": "App-level token required for Socket Mode.",
                    "required": True,
                },
                {
                    "key": "team_id",
                    "label": "Workspace ID",
                    "kind": "text",
                    "placeholder": "T0123456789",
                    "description": "Optional Slack workspace/team ID for routing and validation.",
                    "required": False,
                },
                {
                    "key": "default_channel_id",
                    "label": "Default Channel ID",
                    "kind": "text",
                    "placeholder": "C0123456789",
                    "description": "Default channel for outbound notifications or agent summaries.",
                    "required": False,
                },
            ]
        if channel_name == "whatsapp":
            return [
                {
                    "key": "auth_dir",
                    "label": "Auth Directory",
                    "kind": "text",
                    "placeholder": self._default_whatsapp_auth_dir(),
                    "description": "Directory used by Baileys to store multi-file auth state.",
                    "required": True,
                },
                {
                    "key": "phone_number",
                    "label": "Pairing Phone Number",
                    "kind": "text",
                    "placeholder": "923001234567",
                    "description": "Optional phone number for pairing-code flow instead of QR.",
                    "required": False,
                },
                {
                    "key": "default_chat_id",
                    "label": "Default Chat JID",
                    "kind": "text",
                    "placeholder": "923001234567@s.whatsapp.net",
                    "description": "Optional target chat JID for outbound sends.",
                    "required": False,
                },
                {
                    "key": "allow_self_chat",
                    "label": "Allow Self-Chat",
                    "kind": "boolean",
                    "description": "Respond to messages you send to your own WhatsApp chat for solo testing.",
                    "required": False,
                },
                {
                    "key": "allow_contact_chats",
                    "label": "Allow Other Chats",
                    "kind": "boolean",
                    "description": "Respond to direct messages from other WhatsApp accounts linked to this device.",
                    "required": False,
                },
            ]
        if channel_name == "signal":
            return [
                {
                    "key": "secret",
                    "label": "Registered Phone Number",
                    "kind": "secret",
                    "placeholder": "+15551234567",
                    "description": "Phone number already registered with signal-cli on this machine.",
                    "required": True,
                },
                {
                    "key": "default_recipient",
                    "label": "Default Recipient",
                    "kind": "text",
                    "placeholder": "+15557654321",
                    "description": "Optional E.164 recipient used for outbound Signal sends.",
                    "required": False,
                },
            ]
        return []

    def _channel_validate(
        self,
        channel_name: str,
        *,
        token: str,
        extra: dict[str, Any],
    ) -> list[str]:
        errors: list[str] = []

        def _digits(value: str, label: str) -> None:
            if value and not re.fullmatch(r"\d{15,22}", value):
                errors.append(f"{label} must be a numeric platform ID.")

        if channel_name == "telegram":
            if token and not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{20,}", token):
                errors.append("Telegram bot token format looks invalid.")
            chat_id = str(extra.get("default_chat_id", "") or "").strip()
            if chat_id and not (re.fullmatch(r"-?\d+", chat_id) or re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{4,}", chat_id)):
                errors.append("Telegram default chat ID must be a numeric chat_id or @channelusername.")
        elif channel_name == "discord":
            for key, label in (
                ("guild_id", "Discord server ID"),
                ("text_channel_id", "Discord text channel ID"),
                ("voice_channel_id", "Discord voice channel ID"),
            ):
                _digits(str(extra.get(key, "") or "").strip(), label)
            if bool(extra.get("voice_responses")) and not str(extra.get("voice_channel_id", "") or "").strip():
                errors.append("Discord voice responses require a voice channel ID.")
        elif channel_name == "slack":
            if token and not token.startswith("xoxb-"):
                errors.append("Slack bot token must start with xoxb-.")
            app_token = str(extra.get("slack_app", "") or "").strip()
            if app_token and not app_token.startswith("xapp-"):
                errors.append("Slack app token must start with xapp-.")
            team_id = str(extra.get("team_id", "") or "").strip()
            if team_id and not re.fullmatch(r"T[A-Z0-9]+", team_id):
                errors.append("Slack workspace ID must look like T0123456789.")
            channel_id = str(extra.get("default_channel_id", "") or "").strip()
            if channel_id and not re.fullmatch(r"[CDG][A-Z0-9]+", channel_id):
                errors.append("Slack default channel ID must look like C..., D..., or G....")
        elif channel_name == "whatsapp":
            auth_dir = str(extra.get("auth_dir", "") or "").strip()
            if auth_dir and len(auth_dir) < 3:
                errors.append("WhatsApp auth directory path is too short.")
            phone_number = str(extra.get("phone_number", "") or "").strip()
            if phone_number and not re.fullmatch(r"\d{7,15}", phone_number):
                errors.append("WhatsApp pairing phone number must be digits only in international format.")
            default_chat_id = str(extra.get("default_chat_id", "") or "").strip()
            if default_chat_id and not (
                re.fullmatch(r"\d{7,20}", default_chat_id)
                or re.fullmatch(r"\d{7,20}@(s\.whatsapp\.net|g\.us)", default_chat_id)
            ):
                errors.append("WhatsApp default chat must be a phone number or WhatsApp JID.")
        elif channel_name == "signal":
            e164 = re.compile(r"\+\d{7,15}")
            if token and not e164.fullmatch(token):
                errors.append("Signal registered phone number must be in E.164 format, for example +15551234567.")
            recipient = str(extra.get("default_recipient", "") or "").strip()
            if recipient and not e164.fullmatch(recipient):
                errors.append("Signal default recipient must be in E.164 format.")

        return errors

    def _channel_extra_snapshot(self, channel_name: str, extra: dict[str, Any]) -> dict[str, Any]:
        if channel_name == "discord":
            return {
                "guild_id": str(extra.get("guild_id", "") or ""),
                "text_channel_id": str(extra.get("text_channel_id", "") or ""),
                "voice_responses": bool(extra.get("voice_responses", False)),
                "auto_disconnect_empty_vc": bool(extra.get("auto_disconnect_empty_vc", True)),
                "voice_channel_id": str(extra.get("voice_channel_id", "") or ""),
            }
        if channel_name == "slack":
            identity = self._integration_identity("slack")
            return {
                "app_token_present": bool(extra.get("slack_app") or get_api_key("slack_app")),
                "workspace": str(identity.get("team") or ""),
                "team_id": str(identity.get("team_id") or ""),
                "default_channel_id": str(extra.get("default_channel_id", "") or ""),
                "connect_ready": self._integration_connect_ready("slack"),
            }
        if channel_name == "whatsapp":
            auth_dir = str(extra.get("auth_dir", "") or "").strip() or self._default_whatsapp_auth_dir()
            paired = self._channel_paired(channel_name, {"auth_dir": auth_dir})
            return {
                "auth_dir": auth_dir,
                "auth_dir_present": bool(auth_dir),
                "default_auth_dir": self._default_whatsapp_auth_dir(),
                "paired": paired,
                "needs_pairing": bool(auth_dir and not paired),
                "phone_number": str(extra.get("phone_number", "") or ""),
                "default_chat_id": str(extra.get("default_chat_id", "") or ""),
                "allow_self_chat": bool(extra.get("allow_self_chat", True)),
                "allow_contact_chats": bool(extra.get("allow_contact_chats", False)),
            }
        if channel_name == "telegram":
            return {
                "default_chat_id": str(extra.get("default_chat_id", "") or ""),
            }
        if channel_name == "signal":
            return {
                "default_recipient": str(extra.get("default_recipient", "") or ""),
            }
        return {}

    def _channel_configured(
        self,
        channel_name: str,
        cfg: Any,
        extra: dict[str, Any],
        *,
        token_present: bool | None = None,
    ) -> bool:
        token = bool(token_present) if token_present is not None else (bool(cfg.token) if cfg else self._channel_has_secret(channel_name))
        candidate_extra = self._channel_extra_snapshot(channel_name, extra)
        if channel_name == "slack":
            configured = token and bool(candidate_extra.get("app_token_present"))
            return bool(configured and not self._channel_validate(channel_name, token=get_api_key(channel_name) or "", extra=candidate_extra))
        if channel_name == "whatsapp":
            auth_dir = str(candidate_extra.get("auth_dir", "") or "").strip()
            return bool(auth_dir or token)
        return bool(token and not self._channel_validate(channel_name, token=get_api_key(channel_name) or "", extra=candidate_extra))

    def _default_whatsapp_auth_dir(self) -> str:
        return str((Path.home() / ".neuralclaw" / "sessions" / "whatsapp").resolve())

    def _channel_paired(self, channel_name: str, extra: dict[str, Any]) -> bool:
        if channel_name != "whatsapp":
            return False
        auth_dir = str(extra.get("auth_dir", "") or "").strip()
        if not auth_dir:
            return False
        return (Path(auth_dir) / "creds.json").exists()

    def _channel_ready(
        self,
        channel_name: str,
        cfg: Any,
        extra: dict[str, Any],
        *,
        token_present: bool | None = None,
    ) -> bool:
        configured = self._channel_configured(channel_name, cfg, extra, token_present=token_present)
        if not configured:
            return False
        token_value = str((cfg.token if cfg else "") or get_api_key(channel_name) or "").strip()
        candidate_extra = self._channel_extra_snapshot(channel_name, extra)
        if self._channel_validate(channel_name, token=token_value, extra=candidate_extra):
            return False
        if channel_name == "whatsapp":
            return self._channel_paired(channel_name, candidate_extra)
        return True

    def _channel_status_snapshot(
        self,
        channel_name: str,
        *,
        configured: bool,
        ready: bool,
        running: bool,
        paired: bool,
        validation_errors: list[str] | None = None,
    ) -> tuple[str, str]:
        validation_errors = validation_errors or []
        if running:
            return "running", "Channel is live in the current backend runtime."
        if validation_errors:
            return "invalid_config", validation_errors[0]
        if channel_name == "whatsapp" and configured and not paired:
            return "needs_pairing", "Save the auth directory, generate a QR, and link WhatsApp before enabling."
        if ready:
            return "ready", "Saved and ready to enable on the next backend restart."
        if configured:
            return "saved", "Configuration is saved but still needs one more setup step."
        return "needs_config", "Add the required credentials before enabling this channel."

    def _channel_enablement_error(
        self,
        channel_name: str,
        *,
        token_present: bool,
        extra: dict[str, Any],
    ) -> str:
        token_value = str(get_api_key(channel_name) or "").strip()
        validation_errors = self._channel_validate(channel_name, token=token_value, extra=extra)
        if validation_errors:
            return validation_errors[0]
        if channel_name == "whatsapp":
            auth_dir = str(extra.get("auth_dir", "") or "").strip()
            if not auth_dir:
                return "WhatsApp needs an auth directory before it can be enabled."
            if not self._channel_paired(channel_name, extra):
                return "WhatsApp is not paired yet. Generate a QR code, scan it from Linked Devices, then enable the channel."
        if channel_name == "slack":
            if not token_present:
                return "Slack needs a bot token before it can be enabled."
            if not bool(extra.get("slack_app") or get_api_key("slack_app")):
                return "Slack needs the app token for Socket Mode before it can be enabled."
        if channel_name == "signal" and not token_present:
            return "Signal needs the registered phone number before it can be enabled."
        if channel_name in {"telegram", "discord"} and not token_present:
            return f"{channel_name.title()} needs a token before it can be enabled."
        return f"{channel_name.title()} setup is incomplete."

    def _refresh_runtime_config(self, reloaded: NeuralClawConfig) -> None:
        self._config._raw = reloaded._raw
        self._config.name = reloaded.name
        self._config.persona = reloaded.persona
        self._config.log_level = reloaded.log_level
        self._config.primary_provider = reloaded.primary_provider
        self._config.fallback_providers = reloaded.fallback_providers
        self._config.channels = reloaded.channels
        self._config.model_roles = reloaded.model_roles
        self._config.features = reloaded.features
        self._config.desktop = reloaded.desktop
        self._config.tts = reloaded.tts
        self._config.browser = reloaded.browser
        self._config.security = reloaded.security
        self._config.policy = reloaded.policy
        self._apply_hot_config(reloaded)
        try:
            from neuralclaw.skills.builtins import tts as _tts

            _tts.set_tts_config(self._config.tts)
        except Exception:
            self._logger.exception("tts config refresh failed")
        try:
            if self._config.features.desktop and self._config.desktop.enabled:
                if self._desktop is None:
                    from neuralclaw.cortex.action.desktop import DesktopCortex

                    self._desktop = DesktopCortex(
                        config=self._config.desktop,
                        policy=self._config.policy,
                        bus=self._bus,
                    )
                    self._register_desktop_tools()
                else:
                    self._desktop._config = self._config.desktop
                    self._desktop._policy = self._config.policy
            else:
                self._desktop = None
        except Exception:
            self._logger.exception("desktop runtime rebuild after config refresh failed")
        try:
            self._provider = self._build_provider()
            if self._provider:
                self._deliberate.set_provider(self._provider)
        except Exception:
            self._logger.exception("provider rebuild after config refresh failed")
        try:
            if self._config.model_roles.enabled:
                from neuralclaw.providers.role_router import RoleRouter
                self._role_router = RoleRouter.from_config(self._config.model_roles)
                self._deliberate.set_role_router(self._role_router)
                if hasattr(self._classifier, "set_role_router"):
                    self._classifier.set_role_router(self._role_router)
            else:
                self._role_router = None
                self._deliberate.set_role_router(None)
                if hasattr(self._classifier, "set_role_router"):
                    self._classifier.set_role_router(None)
        except Exception:
            self._logger.exception("role router rebuild after config refresh failed")

    async def _dashboard_update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(updates, dict):
            return {"ok": False, "error": "config payload must be an object"}

        provider_secrets = updates.pop("provider_secrets", {})
        if provider_secrets and not isinstance(provider_secrets, dict):
            return {"ok": False, "error": "provider_secrets must be an object"}

        for provider_name, secret in provider_secrets.items():
            if str(secret).strip():
                set_api_key(str(provider_name), str(secret).strip())

        dashboard_secret = updates.pop("dashboard_secret", None)
        if "dashboard_auth_token" in updates:
            dashboard_secret = updates.pop("dashboard_auth_token")
        dashboard_secret_changed = dashboard_secret is not None
        if dashboard_secret_changed:
            secret_value = str(dashboard_secret or "").strip()
            if secret_value:
                set_dashboard_auth_token(secret_value)
            else:
                delete_dashboard_auth_token()

        model_roles_update = updates.get("model_roles")
        if isinstance(model_roles_update, dict):
            for role in ("primary", "fast", "micro"):
                model_name = str(model_roles_update.get(role, "") or "").strip()
                if model_name and self._is_embedding_model_name(model_name):
                    return {
                        "ok": False,
                        "error": (
                            f"Model role '{role}' cannot use embedding-only model '{model_name}'. "
                            "Choose a chat model for primary/fast/micro and keep embedding models under Memory > Embedding Model."
                        ),
                    }

        providers_update = updates.get("providers")
        if isinstance(providers_update, dict):
            local_update = providers_update.get("local")
            if isinstance(local_update, dict):
                local_model = str(local_update.get("model", "") or "").strip()
                if local_model and self._is_embedding_model_name(local_model):
                    return {
                        "ok": False,
                        "error": (
                            f"Local provider default model '{local_model}' appears to be embedding-only. "
                            "Use a chat model here and set embedding models in the Memory section instead."
                        ),
                    }

        if updates:
            update_config(updates, Path(self._config_path) if self._config_path else None)

        reloaded = load_config(Path(self._config_path) if self._config_path else None)
        self._refresh_runtime_config(reloaded)
        restart_required = bool(
            {
                "channels",
                "google_workspace",
                "microsoft365",
                "desktop",
                "browser",
                "security",
                "policy",
                "tts",
                "features",
                "dashboard_host",
                "dashboard_port",
            }
            & set(updates.keys())
        )
        restart_required = restart_required or dashboard_secret_changed
        return {
            "ok": True,
            "restart_required": restart_required,
            "config": self._get_dashboard_config(),
        }

    async def _dashboard_update_channel(self, channel_name: str, data: dict[str, Any]) -> dict[str, Any]:
        supported = {"telegram", "discord", "slack", "whatsapp", "signal"}
        if channel_name not in supported:
            return {"ok": False, "error": f"Unsupported channel '{channel_name}'"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "channel payload must be an object"}

        existing = self._config._raw.get("channels", {}).get(channel_name, {})
        channel_update = dict(existing if isinstance(existing, dict) else {})
        channel_update["enabled"] = bool(data.get("enabled", False))
        channel_update["trust_mode"] = str(data.get("trust_mode", "") or "")

        extra = data.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}

        if channel_name == "telegram":
            channel_update["default_chat_id"] = str(extra.get("default_chat_id", "") or "")
        elif channel_name == "discord":
            channel_update["guild_id"] = str(extra.get("guild_id", "") or "")
            channel_update["text_channel_id"] = str(extra.get("text_channel_id", "") or "")
            channel_update["voice_responses"] = bool(extra.get("voice_responses", False))
            channel_update["auto_disconnect_empty_vc"] = bool(extra.get("auto_disconnect_empty_vc", True))
            channel_update["voice_channel_id"] = str(extra.get("voice_channel_id", "") or "")
        elif channel_name == "slack":
            channel_update["team_id"] = str(extra.get("team_id", "") or "")
            channel_update["default_channel_id"] = str(extra.get("default_channel_id", "") or "")
        elif channel_name == "whatsapp":
            channel_update["auth_dir"] = str(
                extra.get("auth_dir", "")
                or channel_update.get("auth_dir", "")
                or self._default_whatsapp_auth_dir()
            ).strip()
            channel_update["auth_dir"] = str(Path(channel_update["auth_dir"]).expanduser().resolve())
            channel_update["phone_number"] = str(extra.get("phone_number", "") or "")
            channel_update["default_chat_id"] = str(extra.get("default_chat_id", "") or "")
            channel_update["allow_self_chat"] = bool(extra.get("allow_self_chat", True))
            channel_update["allow_contact_chats"] = bool(extra.get("allow_contact_chats", False))
        elif channel_name == "signal":
            channel_update["default_recipient"] = str(extra.get("default_recipient", "") or "")

        secret = str(data.get("secret", "") or "").strip()
        if secret and channel_name != "whatsapp":
            set_api_key(channel_name, secret)

        if channel_name == "slack":
            app_token = str(extra.get("slack_app", "") or "").strip()
            if app_token:
                set_api_key("slack_app", app_token)

        candidate_extra = self._channel_extra_snapshot(channel_name, channel_update)
        token_value = secret or str(get_api_key(channel_name) or "").strip()
        validation_errors = self._channel_validate(channel_name, token=token_value, extra=candidate_extra)
        if validation_errors:
            return {"ok": False, "error": validation_errors[0]}
        token_present = bool(secret) or self._channel_has_secret(channel_name)
        if channel_name == "whatsapp":
            token_present = bool(candidate_extra.get("auth_dir"))
        enabled = bool(data.get("enabled", False))
        if enabled and not self._channel_ready(channel_name, None, candidate_extra, token_present=token_present):
            return {
                "ok": False,
                "error": self._channel_enablement_error(
                    channel_name,
                    token_present=token_present,
                    extra=candidate_extra,
                ),
            }

        update_config(
            {"channels": {channel_name: channel_update}},
            Path(self._config_path) if self._config_path else None,
        )
        reloaded = load_config(Path(self._config_path) if self._config_path else None)
        self._refresh_runtime_config(reloaded)
        snapshot = next(
            (item for item in self._get_dashboard_channels() if item["name"] == channel_name),
            None,
        )
        return {
            "ok": True,
            "restart_required": True,
            "channel": snapshot,
        }

    async def _dashboard_test_channel(self, channel_name: str, data: dict[str, Any]) -> dict[str, Any]:
        supported = {"telegram", "discord", "slack", "whatsapp", "signal"}
        if channel_name not in supported:
            return {"ok": False, "error": f"Unsupported channel '{channel_name}'"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "channel payload must be an object"}

        token = str(data.get("secret", "") or "").strip() or (get_api_key(channel_name) or "")
        extra = data.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}
        if channel_name == "whatsapp" and not extra.get("auth_dir"):
            extra["auth_dir"] = str(data.get("secret", "") or self._default_whatsapp_auth_dir()).strip()
        if channel_name == "whatsapp":
            extra["auth_dir"] = str(Path(str(extra.get("auth_dir", "") or self._default_whatsapp_auth_dir())).expanduser().resolve())

        candidate_extra = self._channel_extra_snapshot(channel_name, extra)
        validation_errors = self._channel_validate(channel_name, token=token, extra=candidate_extra)
        if validation_errors:
            return {"ok": False, "error": validation_errors[0]}

        if channel_name == "slack":
            app_token = str(extra.get("slack_app", "") or "").strip() or (get_api_key("slack_app") or "")
            if not token or not app_token:
                return {"ok": False, "error": "Slack requires both bot token and app token"}
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://slack.com/api/auth.test",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        payload = await resp.json()
                        ok = bool(payload.get("ok"))
                        return {
                            "ok": ok,
                            "message": (
                                f"Connected to Slack workspace {payload.get('team', 'unknown')}"
                                if ok
                                else payload.get("error", f"Slack API returned {resp.status}")
                            ),
                        }
            except Exception as e:
                return {"ok": False, "error": str(e)}

        if channel_name == "signal":
            if not token:
                return {"ok": False, "error": "Signal requires a registered phone number"}
            if not shutil.which("signal-cli"):
                return {"ok": False, "error": "signal-cli is not installed on this machine"}
            return {
                "ok": True,
                "message": f"signal-cli detected for {token}. Registration must already exist locally.",
            }

        if channel_name == "whatsapp":
            auth_dir = str(candidate_extra.get("auth_dir", "") or token or self._default_whatsapp_auth_dir()).strip()
            if not auth_dir:
                return {"ok": False, "error": "WhatsApp requires an auth directory"}
            creds_path = Path(auth_dir) / "creds.json"
            if not creds_path.exists():
                return {
                    "ok": False,
                    "error": "WhatsApp is not paired yet. Generate a QR and link the device before testing the channel.",
                }
            from neuralclaw.config import ChannelConfig

            cfg = ChannelConfig(
                name="whatsapp",
                enabled=True,
                token=auth_dir,
                extra={"auth_dir": auth_dir},
            )
            adapter = self._build_whatsapp_channel(cfg)
            ok, message = await adapter.test_connection() if adapter else (False, "Unable to initialize WhatsApp adapter")
            return {"ok": ok, "message": message} if ok else {"ok": False, "error": message}

        if not token:
            return {"ok": False, "error": f"{channel_name.title()} requires a secret before testing"}

        from neuralclaw.config import ChannelConfig

        cfg = ChannelConfig(
            name=channel_name,
            enabled=True,
            token=token,
            extra=extra,
            trust_mode=str(data.get("trust_mode", "") or ""),
        )
        builders = {
            "telegram": self._build_telegram_channel,
            "discord": self._build_discord_channel,
        }
        builder = builders.get(channel_name)
        adapter = builder(cfg) if builder else None
        if not adapter:
            return {"ok": False, "error": f"Unable to initialize {channel_name} adapter"}
        ok, message = await adapter.test_connection()
        return {"ok": ok, "message": message} if ok else {"ok": False, "error": message}

    async def _stop_channel_pairing(self, channel_name: str) -> None:
        adapter = self._channel_pairing_adapters.pop(channel_name, None)
        if not adapter:
            return
        try:
            await adapter.stop()
        except Exception as exc:
            self._logger.debug("Failed to stop %s pairing adapter cleanly: %s", channel_name, exc)

    def _qr_svg_data_url(self, data: str) -> str:
        import qrcode
        from qrcode.image.svg import SvgPathImage

        qr = qrcode.QRCode(border=2)
        qr.add_data(data)
        qr.make(fit=True)
        image = qr.make_image(image_factory=SvgPathImage)
        buffer = io.BytesIO()
        image.save(buffer)
        payload = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{payload}"

    async def _dashboard_reset_channel(self, channel_name: str) -> dict[str, Any]:
        """Reset a channel: clear its config, disable it, and remove auth artifacts."""
        supported = {"telegram", "discord", "slack", "whatsapp", "signal"}
        if channel_name not in supported:
            return {"ok": False, "error": f"Unsupported channel '{channel_name}'"}

        # Stop any in-progress pairing adapter
        await self._stop_channel_pairing(channel_name)

        # For WhatsApp, delete the auth directory contents so re-pairing works fresh
        if channel_name == "whatsapp":
            existing = self._config._raw.get("channels", {}).get("whatsapp", {})
            auth_dir = str(
                (existing.get("auth_dir", "") if isinstance(existing, dict) else "")
                or self._default_whatsapp_auth_dir()
            ).strip()
            if auth_dir:
                auth_path = Path(auth_dir)
                if auth_path.exists():
                    import shutil as _shutil
                    for child in auth_path.iterdir():
                        try:
                            if child.is_file():
                                child.unlink()
                            elif child.is_dir():
                                _shutil.rmtree(child)
                        except Exception as exc:
                            self._logger.debug("Failed to remove %s during reset: %s", child, exc)

        # Clear the channel section in the TOML config
        reset_data: dict[str, Any] = {"enabled": False}
        update_config(
            {"channels": {channel_name: reset_data}},
            Path(self._config_path) if self._config_path else None,
        )
        reloaded = load_config(Path(self._config_path) if self._config_path else None)
        self._refresh_runtime_config(reloaded)

        snapshot = next(
            (item for item in self._get_dashboard_channels() if item["name"] == channel_name),
            None,
        )
        return {"ok": True, "channel": snapshot}

    async def _dashboard_pair_channel(self, channel_name: str, data: dict[str, Any]) -> dict[str, Any]:
        if channel_name != "whatsapp":
            return {"ok": False, "error": f"Pairing is not supported for '{channel_name}'"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "channel payload must be an object"}

        extra = data.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}

        auth_dir = str(extra.get("auth_dir", "") or data.get("secret", "") or "").strip()
        if not auth_dir:
            raw_channels = self._config._raw.get("channels", {})
            raw_whatsapp = raw_channels.get("whatsapp", {}) if isinstance(raw_channels, dict) else {}
            auth_dir = str(raw_whatsapp.get("auth_dir", "") or "").strip()
        if not auth_dir:
            auth_dir = self._default_whatsapp_auth_dir()
        auth_dir = str(Path(auth_dir).expanduser().resolve())
        Path(auth_dir).mkdir(parents=True, exist_ok=True)

        existing = self._config._raw.get("channels", {}).get("whatsapp", {})
        persisted = dict(existing if isinstance(existing, dict) else {})
        persisted["auth_dir"] = auth_dir
        update_config(
            {"channels": {"whatsapp": persisted}},
            Path(self._config_path) if self._config_path else None,
        )
        reloaded = load_config(Path(self._config_path) if self._config_path else None)
        self._refresh_runtime_config(reloaded)

        creds_path = Path(auth_dir) / "creds.json"
        if creds_path.exists():
            return {
                "ok": True,
                "paired": True,
                "auth_dir": auth_dir,
                "message": f"WhatsApp is already paired using {auth_dir}.",
            }

        from neuralclaw.config import ChannelConfig

        phone_number = str(extra.get("phone_number", "") or data.get("phone_number", "") or "").strip()
        use_pairing_code = bool(phone_number)

        pair_event = asyncio.Event()
        pair_payload: dict[str, str] = {}

        def _capture_qr(qr_data: str) -> None:
            pair_payload["qr"] = qr_data
            pair_event.set()

        def _capture_pairing_code(code: str) -> None:
            pair_payload["pairing_code"] = code
            pair_event.set()

        cfg = ChannelConfig(
            name="whatsapp",
            enabled=True,
            token=auth_dir,
            extra={"auth_dir": auth_dir},
        )

        await self._stop_channel_pairing("whatsapp")
        try:
            adapter = self._build_whatsapp_channel(
                cfg,
                on_qr=_capture_qr,
                on_pairing_code=_capture_pairing_code,
                phone_number=phone_number,
            )
            if not adapter:
                return {"ok": False, "error": "Unable to initialize WhatsApp adapter"}

            self._channel_pairing_adapters["whatsapp"] = adapter
            await adapter.start()
            await asyncio.wait_for(pair_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            if adapter._fatal_message:
                await self._stop_channel_pairing("whatsapp")
                return {"ok": False, "error": adapter._fatal_message}
            ok, message = await adapter.test_connection()
            if ok:
                return {
                    "ok": True,
                    "paired": True,
                    "auth_dir": auth_dir,
                    "message": message,
                }
            await self._stop_channel_pairing("whatsapp")
            hint = (
                "Timed out waiting for a pairing code. Check the phone number format (e.g. 923001234567)."
                if use_pairing_code
                else "Timed out waiting for a WhatsApp QR code. Try using a phone number for pairing code flow instead."
            )
            return {"ok": False, "error": hint}
        except Exception as exc:
            await self._stop_channel_pairing("whatsapp")
            return {"ok": False, "error": str(exc)}

        # Pairing code flow — return the code for the user to enter on their phone
        pairing_code = pair_payload.get("pairing_code", "")
        if pairing_code:
            return {
                "ok": True,
                "paired": False,
                "auth_dir": auth_dir,
                "pairing_code": pairing_code,
                "message": f"Enter this code on your phone: WhatsApp → Linked Devices → Link with phone number.\nCode: {pairing_code}",
            }

        # QR flow
        qr_raw = pair_payload.get("qr", "")
        if not qr_raw:
            await self._stop_channel_pairing("whatsapp")
            return {"ok": False, "error": "WhatsApp pairing did not provide a QR code or pairing code"}

        return {
            "ok": True,
            "paired": False,
            "auth_dir": auth_dir,
            "message": "Scan this QR code from WhatsApp → Linked Devices → Link a Device.",
            "qr_data": qr_raw,
            "qr_data_url": self._qr_svg_data_url(qr_raw),
        }

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
        result = self._spawner.despawn(name)
        if result and self._workspace_coordinator:
            asyncio.ensure_future(self._workspace_coordinator.release_all_for_agent(name))
        return result

    def _normalize_agent_definition_payload(
        self,
        data: dict[str, Any],
        *,
        existing_name: str | None = None,
        require_name: bool = True,
    ) -> dict[str, Any]:
        name = str(data.get("name", existing_name or "") or "").strip()
        if require_name and not name:
            raise ValueError("Agent name is required")

        provider, default_model, default_base_url = self._provider_default_route(
            str(data.get("provider", "") or "")
        )
        model = str(data.get("model", "") or "").strip() or default_model
        if not model:
            raise ValueError("Model is required")

        raw_caps = data.get("capabilities", [])
        if isinstance(raw_caps, str):
            capabilities = [cap.strip() for cap in raw_caps.split(",") if cap.strip()]
        elif isinstance(raw_caps, list):
            capabilities = [str(cap).strip() for cap in raw_caps if str(cap).strip()]
        else:
            capabilities = []

        namespace = str(data.get("memory_namespace", "") or "").strip()
        if not namespace:
            slug_source = name or existing_name or "agent"
            slug = re.sub(r"[^a-z0-9]+", "-", slug_source.lower()).strip("-") or "agent"
            namespace = f"agent:{slug}"

        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        return {
            "name": name,
            "description": str(data.get("description", "") or "").strip(),
            "capabilities": capabilities,
            "provider": provider,
            "model": model,
            "base_url": str(data.get("base_url", "") or "").strip() or default_base_url,
            "api_key": str(data.get("api_key", "") or "").strip(),
            "system_prompt": str(data.get("system_prompt", "") or "").strip(),
            "memory_namespace": namespace,
            "auto_start": bool(data.get("auto_start", False)),
            "metadata": metadata,
        }

    # -- Agent definition CRUD (for dashboard) ---------------------------------

    async def _dashboard_list_definitions(self) -> list[dict]:
        if not self._agent_store:
            return []
        defns = await self._agent_store.list_all()
        return [d.to_dict() for d in defns]

    async def _dashboard_create_definition(self, data: dict) -> dict:
        if not self._agent_store:
            return {"ok": False, "error": "Agent store not available"}
        from neuralclaw.swarm.agent_store import AgentDefinition
        try:
            payload = self._normalize_agent_definition_payload(data)
            existing = await self._agent_store.get_by_name(payload["name"])
            if existing:
                return {"ok": False, "error": f"Agent '{payload['name']}' already exists"}
            if payload["provider"] in {"local", "meta"}:
                payload["model"], payload["base_url"] = await self._validate_local_model(
                    payload["model"],
                    payload["base_url"],
                    context=f"agent '{payload['name']}'",
                )
            defn = AgentDefinition(agent_id="", **payload)
            agent_id = await self._agent_store.create(defn)
            return {"ok": True, "agent_id": agent_id}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _dashboard_update_definition(self, agent_id: str, data: dict) -> dict:
        if not self._agent_store:
            return {"ok": False, "error": "Agent store not available"}
        try:
            existing = await self._agent_store.get(agent_id)
            if not existing:
                return {"ok": False, "error": "Agent definition not found"}
            payload = self._normalize_agent_definition_payload(
                data,
                existing_name=existing.name,
                require_name=False,
            )
            payload.pop("name", None)
            provider_name, default_model, default_base_url = self._provider_default_route(
                str(payload.get("provider") or existing.provider or "")
            )
            model_name = str(payload.get("model") or existing.model or "").strip() or default_model
            base_url = str(payload.get("base_url") or existing.base_url or "").strip() or default_base_url
            if "provider" in payload:
                payload["provider"] = provider_name
            if ("provider" in payload or "model" in payload) and model_name:
                payload["model"] = model_name
            if ("provider" in payload or "base_url" in payload) and base_url:
                payload["base_url"] = base_url
            if provider_name in {"local", "meta"} and model_name:
                payload["model"], payload["base_url"] = await self._validate_local_model(
                    model_name,
                    base_url,
                    context=f"agent '{existing.name}'",
                )
            ok = await self._agent_store.update(agent_id, **payload)
            return {"ok": ok}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _dashboard_delete_definition(self, agent_id: str) -> dict:
        if not self._agent_store:
            return {"ok": False, "error": "Agent store not available"}
        ok = await self._agent_store.delete(agent_id)
        return {"ok": ok}

    async def _dashboard_spawn_definition(self, agent_id: str) -> dict:
        if not self._agent_store or not self._spawner:
            return {"ok": False, "error": "Agent store or spawner not available"}
        defn = await self._agent_store.get(agent_id)
        if not defn:
            return {"ok": False, "error": "Agent definition not found"}
        try:
            if defn.provider in {"local", "meta"}:
                resolved_model, resolved_base_url = await self._validate_local_model(
                    defn.model,
                    defn.base_url,
                    context=f"agent '{defn.name}'",
                )
                if resolved_model != defn.model or resolved_base_url != defn.base_url:
                    await self._agent_store.update(agent_id, model=resolved_model, base_url=resolved_base_url)
                    defn.model = resolved_model
                    defn.base_url = resolved_base_url
            self._spawner.spawn_from_definition(
                defn,
                episodic=self._episodic,
                semantic=self._semantic,
                procedural=self._procedural,
                shared_bridge=self._shared_bridge,
                skill_registry=self._skills,
            )
            return {"ok": True, "name": defn.name}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _dashboard_despawn_definition(self, agent_id: str) -> dict:
        if not self._agent_store or not self._spawner:
            return {"ok": False, "error": "Agent store or spawner not available"}
        defn = await self._agent_store.get(agent_id)
        if not defn:
            return {"ok": False, "error": "Agent definition not found"}
        ok = self._spawner.despawn(defn.name)
        return {"ok": ok}

    def _dashboard_get_running_agents(self) -> list[dict]:
        if not self._spawner:
            return []
        return self._spawner.get_status()

    def _dashboard_get_agent_activity(self, limit: int = 50) -> list[dict]:
        if not self._mesh:
            return []
        return self._mesh.get_recent_messages(limit=limit)

    async def _dashboard_list_workflows(self) -> list[dict[str, Any]]:
        if not self._workflow_engine:
            return []
        return await self._workflow_engine.list_workflows()

    async def _dashboard_create_workflow(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self._workflow_engine:
            return {"ok": False, "error": "Workflow engine not available"}
        try:
            name = str(data.get("name", "") or "").strip()
            if not name:
                return {"ok": False, "error": "Workflow name is required"}
            steps = data.get("steps", [])
            if steps is None:
                steps = []
            if not isinstance(steps, list):
                return {"ok": False, "error": "steps must be a list"}
            description = str(data.get("description", "") or "").strip()
            variables = data.get("variables")
            if variables is not None and not isinstance(variables, dict):
                return {"ok": False, "error": "variables must be an object"}
            workflow = await self._workflow_engine.create_workflow(
                name=name,
                steps=steps,
                description=description,
                variables=variables,
            )
            return {"ok": True, "workflow": workflow.to_dict()}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _dashboard_run_workflow(self, workflow_id: str) -> dict[str, Any]:
        if not self._workflow_engine:
            return {"ok": False, "error": "Workflow engine not available"}
        result = await self._workflow_engine.execute_workflow(workflow_id)
        if result.get("success"):
            return {"ok": True, **result}
        return {"ok": False, "error": result.get("error", "Workflow run failed")}

    async def _dashboard_pause_workflow(self, workflow_id: str) -> dict[str, Any]:
        if not self._workflow_engine:
            return {"ok": False, "error": "Workflow engine not available"}
        result = await self._workflow_engine.pause_workflow(workflow_id)
        if result.get("success"):
            return {"ok": True, **result}
        return {"ok": False, "error": result.get("error", "Workflow pause failed")}

    async def _dashboard_delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        if not self._workflow_engine:
            return {"ok": False, "error": "Workflow engine not available"}
        deleted = await self._workflow_engine.delete_workflow(workflow_id)
        if deleted:
            return {"ok": True, "workflow_id": workflow_id}
        return {"ok": False, "error": f"Workflow not found: {workflow_id}"}

    def _task_log_entry(
        self,
        event: str,
        detail: str,
        *,
        agent: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "event": event,
            "detail": detail,
        }
        if agent:
            entry["agent"] = agent
        if status:
            entry["status"] = status
        return entry

    def _extract_result_artifacts(self, text: str, *, agent: str = "", limit: int = 8) -> list[dict[str, Any]]:
        if not text:
            return []
        artifacts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for match in re.findall(r"https?://[^\s)>\]]+", text):
            if match in seen:
                continue
            seen.add(match)
            artifacts.append({"type": "url", "label": match, "value": match, "agent": agent or None})
            if len(artifacts) >= limit:
                return artifacts
        for match in re.findall(r"(?:[A-Za-z]:\\[^\r\n\t\"'<>|]+|(?:~|/)[^\r\n\t\"'<>|]+)", text):
            cleaned = match.rstrip(".,:;")
            if len(cleaned) < 3 or cleaned in seen:
                continue
            seen.add(cleaned)
            artifacts.append({"type": "path", "label": cleaned, "value": cleaned, "agent": agent or None})
            if len(artifacts) >= limit:
                break
        return artifacts

    def _task_brief_from_payload(
        self,
        payload: dict[str, Any],
        *,
        orchestration_mode: str,
        target_agents: list[str],
    ) -> dict[str, Any]:
        deliverables_raw = payload.get("deliverables", [])
        deliverables = [
            str(item).strip()
            for item in (deliverables_raw if isinstance(deliverables_raw, list) else str(deliverables_raw).splitlines())
            if str(item).strip()
        ]
        integrations = [
            str(item).strip()
            for item in payload.get("integration_targets", [])
            if str(item).strip()
        ] if isinstance(payload.get("integration_targets", []), list) else []
        return {
            "title_override": str(payload.get("title", "")).strip(),
            "success_criteria": str(payload.get("success_criteria", "")).strip(),
            "workspace_path": str(payload.get("workspace_path", "")).strip(),
            "deliverables": deliverables,
            "integration_targets": integrations,
            "execution_mode": str(payload.get("execution_mode", "")).strip() or "agent-task",
            "orchestration_mode": orchestration_mode,
            "target_agents": target_agents,
        }

    def _build_task_metadata(
        self,
        payload: dict[str, Any],
        *,
        orchestration_mode: str,
        target_agents: list[str],
        timeout_seconds: float,
        memory_provenance: list[dict[str, Any]],
        memory_scopes: list[str],
        fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        brief = self._task_brief_from_payload(
            payload,
            orchestration_mode=orchestration_mode,
            target_agents=target_agents,
        )
        return {
            "brief": brief,
            "timeout_seconds": timeout_seconds,
            "memory_provenance": memory_provenance,
            "memory_scopes": memory_scopes,
            "fallback_reason": fallback_reason,
            "confidence_contract": None,
            "dry_run": {"enabled": bool(payload.get("dry_run")), "status": "disabled"},
            "receipt_refs": [],
            "rollback_refs": [],
            "change_receipt": {},
            "teaching_artifacts": [],
            "project_context_id": str(payload.get("project_context_id", "")).strip() or None,
            "proactive_origin": None,
            "autonomy_mode": self._default_autonomy_mode(str(payload.get("autonomy_mode", "")).strip()),
            "channel_style_profile": payload.get("channel_style_profile") if isinstance(payload.get("channel_style_profile"), dict) else None,
            "approval": {
                "required": bool(payload.get("require_approval")),
                "status": (
                    "approved"
                    if bool(payload.get("require_approval")) and bool(payload.get("__approved"))
                    else "pending" if bool(payload.get("require_approval"))
                    else "not_required"
                ),
                "note": str(payload.get("approval_note", "")).strip(),
                "approved_at": None,
                "approved_by": None,
                "rejected_at": None,
                "rejected_reason": None,
            },
            "artifacts": [],
            "followups": [],
            "checkpoints": [],
            "plan": None,
            "review": None,
            "why_trace": [],
            "execution_log": [
                self._task_log_entry(
                    "queued",
                    f"{orchestration_mode} execution prepared for {', '.join(target_agents) or 'dashboard'}",
                    status="running",
                )
            ],
        }

    def _build_task_followups(
        self,
        *,
        status: str,
        result_text: str,
        error_text: str = "",
    ) -> list[str]:
        followups: list[str] = []
        if status in {"failed", "partial"}:
            followups.append("Review the execution log and retry with a narrower scope or smaller agent set.")
        if error_text:
            followups.append(f"Investigate the reported error: {error_text[:180]}")
        if not result_text.strip():
            followups.append("Request a structured output format with explicit deliverables.")
        return followups[:4]

    def _task_confidence_contract(
        self,
        *,
        confidence: float | None,
        source: str,
        tool_calls_made: int = 0,
        uncertainty_factors: list[str] | None = None,
        evidence_sources: list[str] | None = None,
        escalation_recommendation: str | None = None,
        retry_rationale: str = "",
    ) -> dict[str, Any]:
        level = float(confidence) if confidence is not None else 0.0
        return {
            "confidence": round(level, 2) if confidence is not None else None,
            "source": source,
            "tool_calls_made": int(tool_calls_made),
            "uncertainty_factors": list(uncertainty_factors or []),
            "evidence_sources": list(evidence_sources or []),
            "escalation_recommendation": escalation_recommendation or (
                "operator_review_recommended" if confidence is not None and level < 0.7 else "none"
            ),
            "retry_rationale": retry_rationale,
        }

    def _default_autonomy_mode(self, requested: str | None = None) -> str:
        candidate = str(requested or "").strip()
        if candidate:
            return candidate
        if bool(getattr(self._config.desktop, "autonomous_execution", False)):
            return "policy-driven-autonomous"
        return "suggest-first"

    def _classify_receipt_resources(
        self,
        *,
        metadata: dict[str, Any],
        artifacts: list[dict[str, Any]],
        files_changed: list[str],
    ) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add(resource_type: str, target: str, rollback_kind: str, *, snapshot_supported: bool, status: str, note: str = "") -> None:
            normalized_target = str(target or "").strip()
            if not normalized_target:
                return
            key = (resource_type, normalized_target)
            if key in seen:
                return
            seen.add(key)
            resources.append({
                "resource_type": resource_type,
                "target": normalized_target,
                "rollback_kind": rollback_kind,
                "snapshot_supported": snapshot_supported,
                "rollback_status": status,
                "note": note,
            })

        for path in files_changed:
            add("file", path, "reversible", snapshot_supported=True, status="snapshot_required")

        brief = metadata.get("brief", {}) if isinstance(metadata.get("brief"), dict) else {}
        for target in list(brief.get("integration_targets", []) or []):
            label = str(target or "").strip()
            add("integration", label, "irreversible", snapshot_supported=False, status="not_supported", note="External side effects may require compensating action rather than true rollback.")

        if metadata.get("memory_provenance") or metadata.get("memory_scopes"):
            scopes = metadata.get("memory_scopes") if isinstance(metadata.get("memory_scopes"), list) else []
            target = ", ".join(str(scope) for scope in scopes[:4] if str(scope).strip()) or "memory"
            add("memory", target, "compensatable", snapshot_supported=False, status="manual_restore_only", note="Memory changes can be compensated with versioned restores, but full replay is not yet automatic.")

        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            label = str(artifact.get("label") or artifact.get("type") or "").lower()
            value = str(artifact.get("value") or artifact.get("name") or "").strip()
            if not value:
                continue
            if any(token in label for token in ("database", "db", "sql", "query")):
                rollback_kind = "reversible" if value.endswith(".db") else "compensatable"
                note = (
                    "Local database files can be snapshotted through the filesystem path."
                    if rollback_kind == "reversible"
                    else "Database mutations need connector-specific before/after snapshots or transactions."
                )
                add("database", value, rollback_kind, snapshot_supported=rollback_kind == "reversible", status="snapshot_required" if rollback_kind == "reversible" else "manual_restore_only", note=note)
            elif any(token in label for token in ("memory", "knowledge", "semantic", "episodic")):
                add("memory", value, "compensatable", snapshot_supported=False, status="manual_restore_only", note="Knowledge and memory writes are tracked but not yet auto-restored.")
            elif any(token in label for token in ("message", "email", "slack", "discord", "whatsapp", "telegram")):
                add("message", value, "irreversible", snapshot_supported=False, status="not_supported", note="Outbound messages cannot be unsent universally across channels.")

        if not resources:
            add("workflow", metadata.get("brief", {}).get("execution_mode", "task") if isinstance(metadata.get("brief"), dict) else "task", "compensatable", snapshot_supported=False, status="manual_restore_only", note="Workflow state can be retried or compensated, but has no direct snapshot yet.")
        return resources

    def _summarize_receipt_rollback_coverage(self, resources: list[dict[str, Any]]) -> dict[str, Any]:
        reversible = sum(1 for item in resources if item.get("rollback_kind") == "reversible")
        compensatable = sum(1 for item in resources if item.get("rollback_kind") == "compensatable")
        irreversible = sum(1 for item in resources if item.get("rollback_kind") == "irreversible")
        if reversible and not compensatable and not irreversible:
            status = "full"
            summary = "All tracked side effects are fully reversible once a snapshot exists."
        elif reversible or compensatable:
            status = "partial"
            summary = "Rollback is partial: file-backed changes are reversible, while memory/database/external effects may need compensation."
        else:
            status = "none"
            summary = "This receipt contains only non-reversible or manual-restore resources."
        return {
            "status": status,
            "reversible_count": reversible,
            "compensatable_count": compensatable,
            "irreversible_count": irreversible,
            "summary": summary,
        }

    def _task_change_receipt(
        self,
        *,
        task_id: str,
        metadata: dict[str, Any],
        operations: list[str],
        artifacts: list[dict[str, Any]] | None = None,
        rollback_token: str = "",
    ) -> dict[str, Any]:
        artifact_list = list(artifacts if artifacts is not None else metadata.get("artifacts", []) or [])
        files_changed = [
            str(item.get("value") or "")
            for item in artifact_list
            if isinstance(item, dict) and str(item.get("label") or item.get("type") or "").lower() in {"file", "path"}
        ][:8]
        brief = metadata.get("brief", {}) if isinstance(metadata.get("brief"), dict) else {}
        resource_entries = self._classify_receipt_resources(
            metadata=metadata,
            artifacts=artifact_list,
            files_changed=files_changed,
        )
        rollback_coverage = self._summarize_receipt_rollback_coverage(resource_entries)
        return {
            "receipt_id": f"receipt-{task_id}",
            "task_id": task_id,
            "operations": operations[:10],
            "files_changed": files_changed,
            "integrations_touched": list(brief.get("integration_targets", []) or []),
            "memory_updated": bool(metadata.get("memory_provenance") or metadata.get("memory_scopes")),
            "artifacts": artifact_list[:8],
            "rollback_token": rollback_token,
            "rollback_available": False,
            "snapshot_id": "",
            "resource_entries": resource_entries,
            "rollback_coverage": rollback_coverage,
            "created_at": time.time(),
        }

    def _task_mark_dry_run(
        self,
        payload: dict[str, Any],
        *,
        mode: str,
        target_agents: list[str],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not bool(payload.get("dry_run")):
            return None

        # Estimate risk level based on mode and agent count
        risk_level = "low"
        if mode in ("pipeline", "consensus") and len(target_agents) > 2:
            risk_level = "medium"
        if any(
            str(payload.get(k, "")).strip()
            for k in ("workspace_path", "code_execution", "file_write")
        ):
            risk_level = "high"

        # Collect tool names that would be available to the agents
        tool_preview: list[str] = []
        agent_map = getattr(self, "_agents", {}) or {}
        for agent_name in target_agents:
            agent = agent_map.get(agent_name)
            if agent and hasattr(agent, "tools"):
                tool_preview.extend(
                    t.name for t in getattr(agent, "tools", [])
                    if hasattr(t, "name")
                )

        return {
            "ok": True,
            "dry_run": True,
            "mode": mode,
            "task": str(payload.get("task", "")).strip(),
            "target_agents": target_agents,
            "risk_level": risk_level,
            "tool_preview": sorted(set(tool_preview))[:20],
            "preview": {
                "title": str(payload.get("title", "")).strip() or "Dry-run preview",
                "success_criteria": str(payload.get("success_criteria", "")).strip(),
                "deliverables": list(payload.get("deliverables", []) or []) if isinstance(payload.get("deliverables"), list) else [],
                "workspace_path": str(payload.get("workspace_path", "")).strip(),
                "estimated_agent_count": len(target_agents),
                "would_execute_tools": bool(tool_preview),
            },
            **(extra or {}),
        }

    async def _capture_teaching_artifact_if_needed(
        self,
        *,
        source_id: str,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        result_text: str = "",
    ) -> list[dict[str, Any]]:
        if not self._adaptive:
            return []
        should_capture = bool((payload or {}).get("teaching_mode")) or bool((metadata or {}).get("teaching_mode"))
        if not should_capture:
            return []
        artifact = await self._adaptive.record_teaching_artifact(
            source_id=source_id,
            title=str((payload or {}).get("title", "") or (payload or {}).get("task", "") or source_id),
            transcript=str((payload or {}).get("task", "") or (metadata or {}).get("content", "") or ""),
            task_prompt=str((payload or {}).get("task", "") or ""),
            result_text=result_text,
            tags=["teaching", str((payload or {}).get("execution_mode", "") or "").strip() or "chat"],
        )
        return [artifact]

    @staticmethod
    def _pipeline_stage_role(index: int, total: int) -> str:
        if index <= 0:
            return "planner"
        if index >= max(0, total - 1):
            return "reviewer"
        return "executor"

    def _build_pipeline_plan(
        self,
        payload: dict[str, Any],
        task: str,
        agents: list[str],
    ) -> dict[str, Any]:
        brief = self._task_brief_from_payload(
            payload,
            orchestration_mode="pipeline",
            target_agents=agents,
        )
        stages: list[dict[str, Any]] = []
        total = len(agents)
        for index, agent in enumerate(agents):
            role = self._pipeline_stage_role(index, total)
            objective = (
                "Decompose the request into an execution plan with success criteria and risks."
                if role == "planner"
                else "Review prior outputs, call out gaps, and produce the final operator-ready answer."
                if role == "reviewer"
                else "Execute against the current plan and prior handoff artifacts."
            )
            stages.append({
                "stage_index": index,
                "stage_role": role,
                "agent": agent,
                "objective": objective,
            })
        return {
            "task": task,
            "brief": brief,
            "stages": stages,
        }

    def _build_pipeline_stage_prompt(
        self,
        *,
        task: str,
        payload: dict[str, Any],
        agents: list[str],
        stage_index: int,
        prior_steps: list[dict[str, Any]],
    ) -> str:
        role = self._pipeline_stage_role(stage_index, len(agents))
        stage_agent = agents[stage_index]
        success_criteria = str(payload.get("success_criteria", "")).strip()
        workspace_path = str(payload.get("workspace_path", "")).strip()
        deliverables_raw = payload.get("deliverables", [])
        deliverables = [
            str(item).strip()
            for item in (
                deliverables_raw
                if isinstance(deliverables_raw, list)
                else str(deliverables_raw).splitlines()
            )
            if str(item).strip()
        ]
        integration_targets = [
            str(item).strip()
            for item in payload.get("integration_targets", [])
            if str(item).strip()
        ] if isinstance(payload.get("integration_targets", []), list) else []

        sections = [
            f"Original task:\n{task}",
            f"Current stage: {role} ({stage_index + 1}/{len(agents)})",
            f"Assigned agent: {stage_agent}",
        ]
        if success_criteria:
            sections.append(f"Success criteria:\n{success_criteria}")
        if deliverables:
            sections.append("Deliverables:\n" + "\n".join(f"- {item}" for item in deliverables))
        if workspace_path:
            sections.append(f"Workspace path:\n{workspace_path}")
        if integration_targets:
            sections.append("Integration targets:\n" + "\n".join(f"- {item}" for item in integration_targets))
        if prior_steps:
            prior_lines: list[str] = []
            for step in prior_steps:
                artifacts = step.get("artifact_handoff") or []
                artifact_lines = [
                    f"  - {artifact.get('label') or artifact.get('type')}: {artifact.get('value')}"
                    for artifact in artifacts[:4]
                    if artifact.get("value")
                ]
                prior_lines.append(
                    "\n".join(
                        [
                            f"[{step.get('stage_role', 'stage')}] {step.get('agent', 'agent')} ({step.get('status', 'unknown')})",
                            f"Summary: {str(step.get('result') or step.get('error') or '').strip()[:700]}",
                            *(["Artifacts:"] + artifact_lines if artifact_lines else []),
                        ]
                    ).strip()
                )
            sections.append("Prior stage outputs:\n" + "\n\n".join(prior_lines))

        role_instruction = {
            "planner": (
                "Produce a concrete execution plan. Include intended steps, important risks, "
                "approval-sensitive actions, and what the next stage should implement."
            ),
            "executor": (
                "Execute the plan using the prior stage outputs as binding context. "
                "Return what you changed, what you verified, and any artifacts the reviewer must inspect."
            ),
            "reviewer": (
                "Review the entire staged run before finalizing. Validate whether the success criteria were met, "
                "identify any remaining risks or missing verification, and provide the final answer for the operator."
            ),
        }[role]
        sections.append(f"Instructions:\n{role_instruction}")
        return "\n\n".join(section for section in sections if section).strip()

    def _build_pipeline_checkpoint(
        self,
        *,
        stage_index: int,
        total_stages: int,
        agent: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        checkpoint = {
            "stage_index": stage_index,
            "stage_role": self._pipeline_stage_role(stage_index, total_stages),
            "agent": agent,
            "status": str(result.get("status") or "pending"),
            "result": str(result.get("result") or ""),
            "error": str(result.get("error") or ""),
            "confidence": result.get("confidence"),
            "elapsed_seconds": result.get("elapsed_seconds"),
            "artifact_handoff": list(result.get("artifact_handoff") or []),
            "updated_at": time.time(),
        }
        if checkpoint["status"] == "completed":
            checkpoint["completed_at"] = time.time()
        return checkpoint

    @staticmethod
    def _pipeline_resume_index(checkpoints: list[dict[str, Any]], total: int) -> int:
        for index in range(total):
            checkpoint = next(
                (
                    item for item in checkpoints
                    if int(item.get("stage_index", -1)) == index
                ),
                None,
            )
            if not checkpoint or str(checkpoint.get("status", "")).lower() != "completed":
                return index
        return total

    def _build_pipeline_review(
        self,
        *,
        task: str,
        agents: list[str],
        step_results: list[dict[str, Any]],
        final_result: str,
    ) -> dict[str, Any]:
        final_step = step_results[-1] if step_results else {}
        completed = [step for step in step_results if step.get("status") == "completed"]
        failed = [step for step in step_results if step.get("status") != "completed"]
        return {
            "task": task,
            "reviewer": final_step.get("agent") if final_step.get("stage_role") == "reviewer" else None,
            "agent_order": agents,
            "completed_stages": len(completed),
            "failed_stages": len(failed),
            "status": "approved" if step_results and not failed else "needs_attention",
            "summary": final_result[:600],
            "open_questions": [
                f"{step.get('agent')}: {str(step.get('error') or step.get('status') or '').strip()[:180]}"
                for step in failed[:4]
            ],
        }

    def _build_pipeline_why_trace(
        self,
        *,
        agents: list[str],
        step_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        reasons: list[dict[str, Any]] = []
        total = len(agents)
        for index, agent in enumerate(agents):
            role = self._pipeline_stage_role(index, total)
            step = next((item for item in step_results if item.get("stage_index") == index), {})
            reasons.append({
                "stage_index": index,
                "stage_role": role,
                "agent": agent,
                "reason": (
                    "First stage establishes the plan and execution criteria."
                    if role == "planner"
                    else "Final stage validates and finalizes the run before handoff."
                    if role == "reviewer"
                    else "Middle stages execute the plan and pass artifacts forward."
                ),
                "status": step.get("status", "pending"),
                "confidence": step.get("confidence"),
            })
        return reasons

    @staticmethod
    def _operator_integration_aliases(integration_id: str) -> set[str]:
        aliases = {str(integration_id or "").strip().lower()}
        if integration_id == "google_workspace":
            aliases.update({"google", "gmail", "gdrive", "gdocs", "gsheets", "gcal"})
        elif integration_id == "github":
            aliases.update({"github", "pull_request", "issue", "ci"})
        elif integration_id == "slack":
            aliases.update({"slack"})
        elif integration_id == "supabase":
            aliases.update({"supabase", "database", "db"})
        elif integration_id == "jira":
            aliases.update({"jira"})
        elif integration_id == "notion":
            aliases.update({"notion"})
        return aliases

    def _build_operator_integration_context(
        self,
        *,
        integrations: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        audit_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        contexts: list[dict[str, Any]] = []
        for item in integrations:
            if not isinstance(item, dict):
                continue
            integration_id = str(item.get("id", "")).strip()
            if not integration_id:
                continue
            aliases = self._operator_integration_aliases(integration_id)
            related_tasks = []
            for task in tasks:
                metadata = task.get("metadata") if isinstance(task, dict) else {}
                brief = metadata.get("brief") if isinstance(metadata, dict) else {}
                targets = brief.get("integration_targets", []) if isinstance(brief, dict) else []
                normalized_targets = {str(target).strip().lower() for target in targets if str(target).strip()}
                if normalized_targets & aliases:
                    related_tasks.append(task)
            related_events = []
            for event in audit_events:
                tool_name = str(event.get("tool_name", "")).strip().lower()
                if any(alias in tool_name for alias in aliases if alias):
                    related_events.append(event)

            connected = bool(item.get("connected"))
            details = item.get("details") if isinstance(item.get("details"), dict) else {}
            identity = details.get("identity") if isinstance(details, dict) else {}
            recent_failure = next(
                (task for task in related_tasks if str(task.get("status", "")).lower() in {"failed", "partial"}),
                None,
            )
            recent_success = next(
                (task for task in related_tasks if str(task.get("status", "")).lower() == "completed"),
                None,
            )
            if not connected:
                health = "attention"
                detail = "Not connected yet. Agents cannot operate on this surface until sign-in or credentials are completed."
            elif recent_failure:
                health = "warning"
                detail = f"Recent integration-linked task needs attention: {str(recent_failure.get('title') or recent_failure.get('task_id') or 'task')}"
            elif related_tasks or related_events:
                health = "healthy"
                detail = (
                    f"{len(related_tasks)} recent task(s) and {len(related_events)} audited action(s) touched this integration."
                )
            else:
                health = "idle"
                detail = "Connected, but there has been no recent operator-visible activity on this surface."

            account_label = ""
            if isinstance(identity, dict):
                account_label = str(
                    identity.get("login")
                    or identity.get("email")
                    or identity.get("workspace_name")
                    or identity.get("name")
                    or ""
                ).strip()

            next_prompt = ""
            if integration_id == "github":
                next_prompt = "Use GitHub to summarize the PRs, CI failures, and issues that need action next."
            elif integration_id == "slack":
                next_prompt = "Use Slack to summarize unanswered mentions, urgent threads, and the next operator update to send."
            elif integration_id == "google_workspace":
                next_prompt = "Use Google Workspace to summarize inbox follow-ups, upcoming calendar obligations, and doc activity."
            elif integration_id == "supabase":
                next_prompt = "Use Supabase and database context to summarize product or operational issues that need attention."
            elif integration_id == "jira":
                next_prompt = "Use Jira to identify blocked tickets, stale in-progress work, and the next delivery follow-up."
            elif integration_id == "notion":
                next_prompt = "Use Notion to surface the most relevant specs, decisions, and unresolved planning questions."

            contexts.append({
                "id": integration_id,
                "label": str(item.get("label") or integration_id),
                "category": str(item.get("category") or ""),
                "connected": connected,
                "health": health,
                "detail": detail,
                "account": account_label or None,
                "recent_task_count": len(related_tasks),
                "recent_action_count": len(related_events),
                "latest_task": {
                    "id": recent_failure.get("task_id") if isinstance(recent_failure, dict) else recent_success.get("task_id") if isinstance(recent_success, dict) else None,
                    "title": recent_failure.get("title") if isinstance(recent_failure, dict) else recent_success.get("title") if isinstance(recent_success, dict) else None,
                    "status": recent_failure.get("status") if isinstance(recent_failure, dict) else recent_success.get("status") if isinstance(recent_success, dict) else None,
                },
                "next_prompt": next_prompt or None,
            })
        return contexts

    def _task_requires_approval(self, payload: dict[str, Any]) -> bool:
        return bool(payload.get("require_approval")) and not bool(payload.get("__approved"))

    def _task_mark_waiting_for_approval(self, metadata: dict[str, Any], note: str = "") -> dict[str, Any]:
        approval = dict(metadata.get("approval") or {})
        approval.update({
            "required": True,
            "status": "pending",
            "note": note or str(approval.get("note") or "").strip(),
        })
        return {
            **metadata,
            "approval": approval,
            "execution_log": [
                *(metadata.get("execution_log", [])),
                self._task_log_entry(
                    "approval_required",
                    note or "Waiting for approval before execution begins",
                    status="awaiting_approval",
                ),
            ],
        }

    def _task_mark_approved(self, metadata: dict[str, Any], note: str = "", approved_by: str = "desktop-user") -> dict[str, Any]:
        approval = dict(metadata.get("approval") or {})
        approval.update({
            "required": True,
            "status": "approved",
            "note": note or str(approval.get("note") or "").strip(),
            "approved_at": time.time(),
            "approved_by": approved_by,
            "rejected_at": None,
            "rejected_reason": None,
        })
        return {
            **metadata,
            "approval": approval,
            "execution_log": [
                *(metadata.get("execution_log", [])),
                self._task_log_entry(
                    "approved",
                    note or "Task approved for execution",
                    status="running",
                ),
            ],
        }

    def _task_mark_rejected(self, metadata: dict[str, Any], reason: str = "") -> dict[str, Any]:
        approval = dict(metadata.get("approval") or {})
        approval.update({
            "required": True,
            "status": "rejected",
            "rejected_at": time.time(),
            "rejected_reason": reason or "Rejected from task inbox",
        })
        return {
            **metadata,
            "approval": approval,
            "followups": [],
            "execution_log": [
                *(metadata.get("execution_log", [])),
                self._task_log_entry(
                    "rejected",
                    reason or "Task rejected before execution",
                    status="rejected",
                ),
            ],
        }

    async def _task_create_pending_approval(
        self,
        payload: dict[str, Any],
        *,
        orchestration_mode: str,
        title: str,
        prompt: str,
        target_agents: list[str],
        timeout_seconds: float,
        requested_model: str = "",
        effective_model: str = "",
        provider: str = "",
        base_url: str = "",
        memory_provenance: list[dict[str, Any]] | None = None,
        memory_scopes: list[str] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._task_store:
            return {"ok": False, "error": "Task persistence not available"}
        from neuralclaw.swarm.task_store import TaskRecord

        metadata = self._build_task_metadata(
            payload,
            orchestration_mode=orchestration_mode,
            target_agents=target_agents,
            timeout_seconds=timeout_seconds,
            memory_provenance=list(memory_provenance or []),
            memory_scopes=list(memory_scopes or []),
        )
        execution_payload = {
            key: value
            for key, value in payload.items()
            if not str(key).startswith("__")
        }
        metadata["execution_payload"] = execution_payload
        metadata["resume_mode"] = orchestration_mode
        metadata.setdefault("confidence_contract", None)
        metadata.setdefault("dry_run", {"enabled": bool(payload.get("dry_run")), "status": "disabled"})
        metadata.setdefault("receipt_refs", [])
        metadata.setdefault("rollback_refs", [])
        metadata.setdefault("teaching_artifacts", [])
        metadata.setdefault("project_context_id", str(payload.get("project_context_id") or "").strip() or None)
        metadata.setdefault("proactive_origin", None)
        metadata.setdefault("channel_style_profile", payload.get("channel_style_profile") if isinstance(payload.get("channel_style_profile"), dict) else None)
        metadata = self._task_mark_waiting_for_approval(
            metadata,
            str(payload.get("approval_note", "")).strip(),
        )
        if extra_metadata:
            metadata.update(extra_metadata)
        task_id = await self._task_store.create(
            TaskRecord(
                task_id="",
                title=title,
                prompt=prompt,
                status="awaiting_approval",
                provider=provider,
                requested_model=requested_model,
                effective_model=effective_model,
                base_url=base_url,
                target_agents=target_agents,
                metadata=metadata,
            )
        )
        metadata["change_receipt"] = {
            "receipt_id": f"receipt-{task_id}",
            "task_id": task_id,
            "operations": ["task_created", "awaiting_approval"],
            "files_changed": [],
            "integrations_touched": list((metadata.get("brief") or {}).get("integration_targets", [])) if isinstance(metadata.get("brief"), dict) else [],
            "memory_updated": bool(memory_provenance or memory_scopes),
            "artifacts": [],
            "rollback_token": "",
            "created_at": time.time(),
        }
        metadata["receipt_refs"] = [f"receipt-{task_id}"]
        await self._task_store.update(task_id, metadata=metadata)
        return {
            "ok": True,
            "task_id": task_id,
            "status": "awaiting_approval",
            "result": "Task is waiting for approval before execution.",
            "memory_provenance": list(memory_provenance or []),
            "memory_scopes": list(memory_scopes or []),
        }

    async def _dashboard_approve_task(self, task_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._task_store:
            return {"ok": False, "error": "Task store not available"}
        task = await self._task_store.get(task_id)
        if not task:
            return {"ok": False, "error": "Task not found"}
        metadata = dict(task.metadata or {})
        approval = dict(metadata.get("approval") or {})
        if approval.get("status") == "approved":
            return {"ok": True, "task_id": task_id, "status": "running", "message": "Task already approved"}
        if task.status != "awaiting_approval":
            return {"ok": False, "error": f"Task is not awaiting approval (current status: {task.status})"}
        execution_payload = metadata.get("execution_payload")
        if not isinstance(execution_payload, dict):
            return {"ok": False, "error": "Stored execution payload missing"}
        note = str((payload or {}).get("note", "")).strip()
        approved_by = str((payload or {}).get("approved_by", "desktop-user")).strip() or "desktop-user"
        metadata = self._task_mark_approved(metadata, note=note, approved_by=approved_by)
        receipt = dict(metadata.get("change_receipt") or {})
        operations = list(receipt.get("operations", []) or [])
        operations.append("approved_for_execution")
        receipt["operations"] = operations[:8]
        metadata["change_receipt"] = receipt
        await self._task_store.update(
            task_id,
            status="running",
            started_at=time.time(),
            metadata=metadata,
        )
        resume_payload = {
            **execution_payload,
            "__approved": True,
            "__task_id": task_id,
        }
        mode = str(metadata.get("resume_mode") or metadata.get("brief", {}).get("orchestration_mode") or "").strip().lower()
        if mode in {"manual", "fanout"}:
            asyncio.create_task(self._dashboard_delegate_task(resume_payload))
        elif mode == "pipeline":
            asyncio.create_task(self._dashboard_pipeline_task(resume_payload))
        elif mode == "consensus":
            asyncio.create_task(self._dashboard_seek_consensus(resume_payload))
        elif mode == "auto-route":
            asyncio.create_task(self._dashboard_auto_route_task(resume_payload))
        else:
            return {"ok": False, "error": f"Unsupported resume mode: {mode or 'unknown'}"}
        return {"ok": True, "task_id": task_id, "status": "running", "message": "Task approved and resumed"}

    async def _dashboard_reject_task(self, task_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._task_store:
            return {"ok": False, "error": "Task store not available"}
        task = await self._task_store.get(task_id)
        if not task:
            return {"ok": False, "error": "Task not found"}
        if task.status != "awaiting_approval":
            return {"ok": False, "error": f"Task is not awaiting approval (current status: {task.status})"}
        reason = str((payload or {}).get("reason", "")).strip()
        metadata = self._task_mark_rejected(dict(task.metadata or {}), reason=reason)
        await self._task_store.update(
            task_id,
            status="rejected",
            error=reason or "Rejected before execution",
            completed_at=time.time(),
            metadata=metadata,
        )
        return {"ok": True, "task_id": task_id, "status": "rejected", "message": "Task rejected"}

    async def _dashboard_list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self._task_store:
            return []
        tasks = await self._task_store.list_all(limit=limit)
        return [task.to_dict() for task in tasks if not task.parent_task_id]

    async def _dashboard_get_task(self, task_id: str) -> dict[str, Any] | None:
        if not self._task_store:
            return None
        task = await self._task_store.get(task_id)
        if not task:
            return None
        children = await self._task_store.list_children(task_id)
        payload = task.to_dict()
        payload["children"] = [child.to_dict() for child in children]
        return payload

    async def _dashboard_get_local_model_health(self) -> dict[str, Any]:
        registry = await self._get_local_model_registry(force=True)
        return registry

    async def _dashboard_create_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "error": "Adaptive control plane unavailable"}
        task_id = str(payload.get("task_id", "") or "").strip() or f"manual-{int(time.time())}"
        file_paths = [str(item).strip() for item in payload.get("file_paths", []) if str(item).strip()] if isinstance(payload.get("file_paths"), list) else []
        if not file_paths:
            return {"ok": False, "error": "file_paths required"}
        snapshot_id = await self._adaptive.create_snapshot(task_id, "manual", {"file_paths": file_paths, "metadata": payload.get("metadata", {})})
        await self._sync_task_receipt_snapshot_state(task_id, snapshot_id=snapshot_id, rollback_available=True)
        return {"ok": True, "snapshot_id": snapshot_id}

    async def _dashboard_execute_rollback(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "error": "Adaptive control plane unavailable"}
        snapshot_id = str(payload.get("snapshot_id", "") or "").strip()
        if snapshot_id:
            result = await self._adaptive.rollback_snapshot(snapshot_id)
            task_id = str(payload.get("task_id", "") or "").strip()
            if task_id:
                await self._sync_task_receipt_snapshot_state(task_id, rollback_token=str(result.get("rollback_id") or ""), rollback_available=False, snapshot_id=snapshot_id)
            return result
        receipt_id = str(payload.get("receipt_id", "") or "").strip()
        if not receipt_id:
            return {"ok": False, "error": "snapshot_id or receipt_id required"}
        result = await self._adaptive.execute_rollback(receipt_id)
        if result.get("ok"):
            task_id = str(result.get("task_id") or "").strip()
            if task_id:
                await self._sync_task_receipt_snapshot_state(
                    task_id,
                    rollback_token=str(result.get("rollback_id") or ""),
                    rollback_available=False,
                    snapshot_id=str(result.get("snapshot_id") or ""),
                )
        return result

    async def _dashboard_list_snapshots(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "snapshots": []}
        params = payload or {}
        return {"ok": True, "snapshots": await self._adaptive.list_snapshots(str(params.get("task_id", "") or "").strip() or None)}

    async def _dashboard_get_rollback_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "status": None}
        return {"ok": True, "status": await self._adaptive.get_rollback_status(str(payload.get("receipt_id", "") or "").strip())}

    async def _sync_task_receipt_snapshot_state(
        self,
        task_id: str,
        *,
        snapshot_id: str = "",
        rollback_token: str = "",
        rollback_available: bool | None = None,
    ) -> None:
        if not self._task_store or not task_id:
            return
        task = await self._task_store.get(task_id)
        if not task:
            return
        metadata = dict(task.metadata or {})
        receipt = dict(metadata.get("change_receipt") or {})
        if not receipt:
            return
        if snapshot_id:
            receipt["snapshot_id"] = snapshot_id
        if rollback_token:
            receipt["rollback_token"] = rollback_token
        if rollback_available is not None:
            receipt["rollback_available"] = rollback_available
        resource_entries = list(receipt.get("resource_entries") or []) if isinstance(receipt.get("resource_entries"), list) else []
        for entry in resource_entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("resource_type") or "") == "file":
                if snapshot_id:
                    entry["rollback_status"] = "ready"
                if rollback_token:
                    entry["rollback_status"] = "rolled_back"
        if resource_entries:
            receipt["resource_entries"] = resource_entries
            receipt["rollback_coverage"] = self._summarize_receipt_rollback_coverage(resource_entries)
        metadata["change_receipt"] = receipt
        metadata["receipt_refs"] = [receipt.get("receipt_id")] if receipt.get("receipt_id") else metadata.get("receipt_refs", [])
        metadata["rollback_refs"] = [rollback_token] if rollback_token else metadata.get("rollback_refs", [])
        await self._task_store.update(task_id, metadata=metadata)

    async def _dashboard_list_routines(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "routines": []}
        params = payload or {}
        status = str(params.get("status", "") or "").strip() or None
        return {"ok": True, "routines": await self._adaptive.list_routines(status=status)}

    async def _dashboard_review_routine(self, routine_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "error": "Adaptive control plane unavailable"}
        decision = str(payload.get("decision", "") or "").strip().lower()
        if not decision:
            return {"ok": False, "error": "decision required"}
        status = "promoted" if decision == "approve" else "quarantined" if decision == "reject" else "probation"
        routine = await self._adaptive.update_routine_status(routine_id, status, str(payload.get("reason", "") or ""))
        return {"ok": True, "routine": routine}

    async def _dashboard_review_learning_diff(self, cycle_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "error": "Adaptive control plane unavailable"}
        return await self._adaptive.review_learning_diff(
            cycle_id,
            str(payload.get("decision", "") or "").strip().lower(),
            reviewer=str(payload.get("reviewer", "desktop-user") or "desktop-user"),
            reason=str(payload.get("reason", "") or ""),
        )

    async def _dashboard_list_pending_learning_reviews(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "reviews": []}
        return {"ok": True, "reviews": await self._adaptive.list_pending_reviews()}

    async def _dashboard_activate_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "error": "Adaptive control plane unavailable"}
        project_id = str(payload.get("project_id", "") or "").strip()
        if not project_id:
            return {"ok": False, "error": "project_id required"}
        memory_snapshot = {
            "active_task_ids": [task.get("task_id") for task in await self._dashboard_list_tasks(limit=12)],
            "recent_channels": list(self._history.keys())[:6],
        }
        skill_snapshot = list(getattr(self._skills, "_skills", {}).keys())[:20]
        return await self._adaptive.activate_project(project_id, memory_snapshot=memory_snapshot, skill_snapshot=skill_snapshot)

    async def _dashboard_suspend_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "error": "Adaptive control plane unavailable"}
        project_id = str(payload.get("project_id", "") or "").strip()
        if not project_id:
            active = await self._adaptive.get_active_project()
            project_id = str((active or {}).get("project_id") or "")
        if not project_id:
            return {"ok": False, "error": "project_id required"}
        return await self._adaptive.suspend_project(project_id)

    async def _dashboard_get_active_project(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "project": None}
        return {"ok": True, "project": await self._adaptive.get_active_project()}

    async def _dashboard_list_project_sessions(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "sessions": [], "profiles": []}
        return {"ok": True, "sessions": await self._adaptive.list_project_sessions(), "profiles": await self._adaptive.list_project_profiles()}

    async def _dashboard_capture_teaching_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "error": "Adaptive control plane unavailable"}
        entry = await self._adaptive.record_teaching_artifact(
            source_id=str(payload.get("source_id", "") or f"manual-{int(time.time())}"),
            title=str(payload.get("title", "") or "Teaching artifact"),
            transcript=str(payload.get("transcript", "") or ""),
            task_prompt=str(payload.get("task_prompt", "") or ""),
            result_text=str(payload.get("result_text", "") or ""),
            tags=[str(item).strip() for item in payload.get("tags", []) if str(item).strip()] if isinstance(payload.get("tags"), list) else [],
        )
        return {"ok": True, "entry": entry}

    async def _dashboard_list_teaching_artifacts(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "entries": []}
        params = payload or {}
        limit = max(1, min(int(params.get("limit", 20) or 20), 100))
        return {"ok": True, "entries": await self._adaptive.list_playbook_entries(limit=limit)}

    async def _dashboard_get_skill_graph(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "graph": {"nodes": [], "edges": []}}
        manifests: list[dict[str, Any]] = []
        for manifest in list(getattr(self._skills, "_skills", {}).values()):
            manifests.append({
                "name": manifest.name,
                "dependencies": list(getattr(manifest, "dependencies", []) or []),
                "composition_metadata": dict(getattr(manifest, "composition_metadata", {}) or {}),
                "risk_level": str(getattr(manifest, "risk_level", "low") or "low"),
                "multimodal_capabilities": list(getattr(manifest, "multimodal_capabilities", []) or []),
                "tools": [tool.name for tool in manifest.tools],
            })
        return {"ok": True, "graph": self._adaptive.build_skill_graph(manifests)}

    async def _dashboard_export_distilled_patterns(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "error": "Adaptive control plane unavailable"}
        return await self._adaptive.export_distilled_patterns()

    async def _dashboard_import_distilled_patterns(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._adaptive:
            return {"ok": False, "error": "Adaptive control plane unavailable"}
        return await self._adaptive.import_distilled_patterns(payload if isinstance(payload, dict) else {})

    async def _dashboard_ingest_voice_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._adaptive.ingest_multimodal_artifact("voice", payload) if self._adaptive else {"ok": False, "error": "Adaptive control plane unavailable"}

    async def _dashboard_ingest_screenshot_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._adaptive.ingest_multimodal_artifact("screenshot", payload) if self._adaptive else {"ok": False, "error": "Adaptive control plane unavailable"}

    async def _dashboard_ingest_recording_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._adaptive.ingest_multimodal_artifact("recording", payload) if self._adaptive else {"ok": False, "error": "Adaptive control plane unavailable"}

    async def _dashboard_ingest_diagram_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._adaptive.ingest_multimodal_artifact("diagram", payload) if self._adaptive else {"ok": False, "error": "Adaptive control plane unavailable"}

    # ── wave-2 dashboard methods: intent ─────────────────────────────

    async def _dashboard_get_intent_predictions(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._intent_predictor:
            return {"ok": False, "predictions": []}
        params = payload or {}
        limit = int(params.get("limit", 10))
        return {"ok": True, "predictions": await self._intent_predictor.predict(limit=limit)}

    async def _dashboard_get_intent_stats(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._intent_predictor:
            return {"ok": False, "stats": {}}
        return {"ok": True, "stats": await self._intent_predictor.get_accuracy_stats()}

    async def _dashboard_observe_intent(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._intent_predictor:
            return {"ok": False}
        action = str(payload.get("action", "")).strip()
        context = payload.get("context", {})
        if not action:
            return {"ok": False, "error": "action required"}
        await self._intent_predictor.observe(action=action, context=context if isinstance(context, dict) else {})
        return {"ok": True}

    # ── wave-2 dashboard methods: style ──────────────────────────────

    async def _dashboard_get_style_profile(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._style_adapter:
            return {"ok": False, "profile": {}}
        params = payload or {}
        user_id = str(params.get("user_id", "default")).strip()
        modifier = await self._style_adapter.get_prompt_modifier(user_id=user_id)
        return {"ok": True, "profile": {"user_id": user_id, "modifier": modifier}}

    async def _dashboard_set_style_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._style_adapter:
            return {"ok": False}
        key = str(payload.get("key", "")).strip()
        value = str(payload.get("value", "")).strip()
        if not key:
            return {"ok": False, "error": "key required"}
        await self._style_adapter.set_custom_rule(key=key, value=value)
        return {"ok": True}

    # ── wave-2 dashboard methods: compensating ───────────────────────

    async def _dashboard_get_compensating_history(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._compensating_registry:
            return {"ok": False, "history": []}
        params = payload or {}
        limit = int(params.get("limit", 20))
        return {"ok": True, "history": await self._compensating_registry.get_compensation_history(limit=limit)}

    async def _dashboard_list_compensators(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._compensating_registry:
            return {"ok": False, "compensators": []}
        return {"ok": True, "compensators": self._compensating_registry.list_registered_compensators()}

    async def _dashboard_plan_compensation(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._compensating_registry:
            return {"ok": False}
        integration = str(payload.get("integration", "")).strip()
        action = str(payload.get("action", "")).strip()
        original_payload = payload.get("payload", {})
        if not integration or not action:
            return {"ok": False, "error": "integration and action required"}
        plan = await self._compensating_registry.plan_compensation(integration=integration, action=action, payload=original_payload)
        return {"ok": True, "plan": plan}

    async def _dashboard_execute_compensation(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._compensating_registry:
            return {"ok": False}
        compensation_id = str(payload.get("compensation_id", "")).strip()
        if not compensation_id:
            return {"ok": False, "error": "compensation_id required"}
        result = await self._compensating_registry.execute_compensation(compensation_id=compensation_id)
        return {"ok": True, "result": result}

    # ── wave-2 dashboard methods: federation ─────────────────────────

    async def _dashboard_list_federated_skills(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._skill_federation:
            return {"ok": False, "skills": []}
        return {"ok": True, "skills": await self._skill_federation.list_federated_skills()}

    async def _dashboard_get_federation_stats(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._skill_federation:
            return {"ok": False, "stats": {}}
        return {"ok": True, "stats": await self._skill_federation.get_federation_stats()}

    async def _dashboard_publish_federated_skill(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._skill_federation:
            return {"ok": False}
        skill_name = str(payload.get("skill_name", "")).strip()
        manifest = payload.get("manifest", {})
        if not skill_name:
            return {"ok": False, "error": "skill_name required"}
        await self._skill_federation.publish_skill(name=skill_name, manifest=manifest if isinstance(manifest, dict) else {})
        return {"ok": True}

    async def _dashboard_import_federated_skill(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._skill_federation:
            return {"ok": False}
        peer_id = str(payload.get("peer_id", "")).strip()
        skill_name = str(payload.get("skill_name", "")).strip()
        if not peer_id or not skill_name:
            return {"ok": False, "error": "peer_id and skill_name required"}
        await self._skill_federation.import_from_peer(peer_id=peer_id, skill_name=skill_name)
        return {"ok": True}

    # ── wave-2 dashboard methods: scheduler ──────────────────────────

    async def _dashboard_get_scheduler_status(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._routine_scheduler:
            return {"ok": False, "status": "stopped"}
        return {"ok": True, "status": "running" if self._routine_scheduler._running else "stopped"}

    async def _dashboard_force_run_routine(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._routine_scheduler:
            return {"ok": False}
        routine_id = str(payload.get("routine_id", "")).strip()
        if not routine_id:
            return {"ok": False, "error": "routine_id required"}
        await self._routine_scheduler.force_run(routine_id=routine_id)
        return {"ok": True}

    async def _dashboard_get_operator_brief(self) -> dict[str, Any]:
        memory = await self._get_dashboard_memory()
        tasks = await self._dashboard_list_tasks(limit=12)
        audit_payload = await self._dashboard_get_audit({"limit": 8})
        integrations_payload = await self._dashboard_list_integrations()
        integrations = integrations_payload.get("integrations", []) if isinstance(integrations_payload, dict) else []
        kb_docs = await self._dashboard_list_kb_documents() if self._knowledge_base else []
        running_agents = await self._dashboard_get_running_agents() if self._mesh else []
        audit_events = audit_payload.get("events", []) if isinstance(audit_payload, dict) else []
        audit_stats = audit_payload.get("stats", {}) if isinstance(audit_payload, dict) else {}
        evolution_initiatives = await self._evolution_orchestrator.list_initiatives() if self._evolution_orchestrator else []

        connected_integrations = [
            item for item in integrations
            if isinstance(item, dict) and item.get("connected")
        ]
        integration_context = self._build_operator_integration_context(
            integrations=connected_integrations,
            tasks=tasks,
            audit_events=audit_events,
        )
        failed_tasks = [task for task in tasks if str(task.get("status", "")).lower() in {"failed", "partial"}]
        pending_approvals = [task for task in tasks if str(task.get("status", "")).lower() == "awaiting_approval"]
        completed_tasks = [task for task in tasks if str(task.get("status", "")).lower() == "completed"]
        recent_task = tasks[0] if tasks else None
        kb_sources = len({str(doc.get("source", "")).strip() for doc in kb_docs if str(doc.get("source", "")).strip()})

        highlights: list[dict[str, Any]] = [
            {
                "id": "tasks",
                "label": "Recent Tasks",
                "value": len(tasks),
                "tone": "blue",
                "detail": f"{len(completed_tasks)} completed, {len(failed_tasks)} needing attention",
            },
            {
                "id": "approvals",
                "label": "Pending Approvals",
                "value": len(pending_approvals),
                "tone": "orange" if pending_approvals else "green",
                "detail": "Approval-gated work waiting for an operator decision" if pending_approvals else "No tasks are blocked on approvals",
            },
            {
                "id": "integrations",
                "label": "Connected Integrations",
                "value": len(connected_integrations),
                "tone": "green" if connected_integrations else "orange",
                "detail": ", ".join(str(item.get("label", "")) for item in connected_integrations[:4]) or "Connect GitHub, Slack, or Google to expand action surfaces",
            },
            {
                "id": "knowledge",
                "label": "Knowledge Base",
                "value": len(kb_docs),
                "tone": "purple",
                "detail": f"{kb_sources} distinct sources indexed for retrieval" if kb_docs else "No KB documents indexed yet",
            },
            {
                "id": "audit",
                "label": "Recent Actions",
                "value": len(audit_events),
                "tone": "green" if int(audit_stats.get("denied_records", 0) or 0) == 0 else "orange",
                "detail": (
                    f"{int(audit_stats.get('denied_records', 0) or 0)} denied out of "
                    f"{int(audit_stats.get('total_records', 0) or 0)} audited actions"
                ),
            },
        ]

        recommendations: list[dict[str, Any]] = []
        if pending_approvals:
            recommendations.append({
                "id": f"approve-{pending_approvals[0].get('task_id')}",
                "title": "Review approval-gated work",
                "summary": f"{len(pending_approvals)} task(s) are waiting for approval before execution.",
                "prompt": "Review the pending approval-gated tasks, summarize the risk, and tell me which one should be approved first.",
                "mode": "auto-route",
                "integration_targets": [],
                "tone": "orange",
            })
        if failed_tasks:
            failed = failed_tasks[0]
            recommendations.append({
                "id": f"recover-{failed.get('task_id')}",
                "title": "Recover the latest failed workflow",
                "summary": str(failed.get("title") or "A recent workflow failed or partially completed."),
                "prompt": f"Review the failed task '{str(failed.get('title') or failed.get('task_id'))}', identify the blocker, and propose the best next recovery step.",
                "mode": "auto-route",
                "integration_targets": list((failed.get("metadata") or {}).get("brief", {}).get("integration_targets", [])) if isinstance((failed.get("metadata") or {}).get("brief", {}), dict) else [],
                "tone": "red",
            })
        if any(str(item.get("id")) == "github" for item in connected_integrations):
            recommendations.append({
                "id": "github-daily",
                "title": "Run a GitHub ops sweep",
                "summary": "Ask the agents to inspect pull requests, CI failures, and issue activity.",
                "prompt": "Use the GitHub integration to summarize open pull requests, failing CI, and the highest-priority issues that need action today.",
                "mode": "auto-route",
                "integration_targets": ["github"],
                "tone": "blue",
            })
        if any(str(item.get("id")) == "slack" for item in connected_integrations):
            recommendations.append({
                "id": "slack-brief",
                "title": "Create a Slack operator brief",
                "summary": "Summarize important channel activity and prepare outbound updates.",
                "prompt": "Use Slack to summarize important channel activity, unanswered mentions, and draft the top update I should post next.",
                "mode": "auto-route",
                "integration_targets": ["slack"],
                "tone": "purple",
            })
        if any(str(item.get("id")) == "google_workspace" for item in connected_integrations):
            recommendations.append({
                "id": "google-followups",
                "title": "Check Google follow-ups",
                "summary": "Review recent mail/docs/calendar context and identify follow-up actions.",
                "prompt": "Use Google Workspace to review recent mail, docs, and calendar context and summarize the top follow-up actions for today.",
                "mode": "auto-route",
                "integration_targets": ["google_workspace"],
                "tone": "green",
            })
        database_integrations = [
            item for item in connected_integrations
            if str(item.get("category") or "").strip().lower() == "database"
        ]
        if database_integrations:
            primary_db = database_integrations[0]
            recommendations.append({
                "id": f"database-brief-{primary_db.get('id')}",
                "title": "Build a database operator brief",
                "summary": f"Use {primary_db.get('label') or 'the active database'} to surface schema context, recent questions, and the next analytical cut worth running.",
                "prompt": f"Use the database connection '{primary_db.get('label') or primary_db.get('id')}' to summarize the key tables, identify one high-signal query to run next, and recommend whether to explain, chart, or operationalize it.",
                "mode": "auto-route",
                "integration_targets": [str(primary_db.get("id") or "")],
                "tone": "blue",
            })
        if not recommendations and recent_task:
            recommendations.append({
                "id": "continue-last-task",
                "title": "Continue recent operator work",
                "summary": str(recent_task.get("title") or "Follow up on the latest task"),
                "prompt": f"Continue from the recent task '{str(recent_task.get('title') or recent_task.get('task_id'))}' and propose the strongest next step.",
                "mode": "auto-route",
                "integration_targets": [],
                "tone": "blue",
            })
        for context in integration_context:
            if context.get("health") in {"warning", "attention"} and context.get("next_prompt"):
                recommendations.append({
                    "id": f"integration-{context['id']}",
                    "title": f"Review {context['label']} activity",
                    "summary": str(context.get("detail") or ""),
                    "prompt": str(context.get("next_prompt") or ""),
                    "mode": "auto-route",
                    "integration_targets": [str(context["id"])],
                    "tone": "orange" if context.get("health") == "attention" else "red",
                })

        adaptive_snapshot = await self._adaptive.sync_snapshot(
            tasks=tasks,
            audit_events=audit_events,
            integrations=integrations,
            kb_docs=kb_docs,
            running_agents=running_agents,
            evolution_initiatives=evolution_initiatives,
            workspace_root=Path.cwd(),
        ) if self._adaptive else {
            "adaptive_suggestions": [],
            "next_actions": [],
            "project_brief": {},
            "learning_diffs": [],
            "recent_receipts": [],
            "proactive_routines": [],
            "active_project": None,
            "playbook_entries": [],
        }
        pending_reviews = await self._adaptive.list_pending_reviews() if self._adaptive else []
        ranked_actions = adaptive_snapshot.get("next_actions", [])
        for item in ranked_actions[:3]:
            if not isinstance(item, dict):
                continue
            recommendations.append({
                "id": f"adaptive-{item.get('suggestion_id')}",
                "title": str(item.get("title") or "Adaptive next action"),
                "summary": str(item.get("summary") or ""),
                "prompt": str(item.get("proposed_action") or item.get("summary") or ""),
                "mode": "adaptive-suggestion",
                "integration_targets": [],
                "tone": "orange" if bool(item.get("requires_approval")) else "blue",
            })

        return {
            "ok": True,
            "generated_at": time.time(),
            "summary": {
                "running_agents": len(running_agents),
                "connected_integrations": len(connected_integrations),
                "pending_approvals": len(pending_approvals),
                "failed_tasks": len(failed_tasks),
                "knowledge_documents": len(kb_docs),
                "episodic_memories": int(memory.get("episodic_count", 0)),
                "semantic_memories": int(memory.get("semantic_count", 0)),
                "recent_audit_events": len(audit_events),
                "denied_actions": int(audit_stats.get("denied_records", 0) or 0),
            },
            "highlights": highlights,
            "recent_task": recent_task,
            "recommended_actions": recommendations[:6],
            "integration_context": integration_context[:8],
            "connected_integrations": [
                {
                    "id": item.get("id"),
                    "label": item.get("label"),
                    "category": item.get("category"),
                    "summary": item.get("summary"),
                }
                for item in connected_integrations[:8]
            ],
            "recent_actions": audit_events,
            "adaptive_suggestions": adaptive_snapshot.get("adaptive_suggestions", []),
            "next_actions": ranked_actions,
            "project_brief": adaptive_snapshot.get("project_brief", {}),
            "learning_diffs": adaptive_snapshot.get("learning_diffs", []),
            "recent_receipts": adaptive_snapshot.get("recent_receipts", []),
            "proactive_routines": adaptive_snapshot.get("proactive_routines", []),
            "active_project": adaptive_snapshot.get("active_project"),
            "playbook_entries": adaptive_snapshot.get("playbook_entries", []),
            "pending_reviews": pending_reviews,
        }

    async def _dashboard_get_audit(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        params = filters if isinstance(filters, dict) else {}
        limit = max(1, min(100, int(params.get("limit", 20) or 20)))
        tool = str(params.get("tool", "") or "").strip() or None
        user_id = str(params.get("user_id", "") or "").strip() or None
        denied_only = str(params.get("denied_only", "false") or "").strip().lower() in {
            "1", "true", "yes", "on",
        }

        stats = await self._audit.stats()
        records = await self._audit.search(
            tool=tool,
            user_id=user_id,
            denied_only=denied_only,
            limit=limit,
        )
        events = [
            {
                "timestamp": record.timestamp,
                "request_id": record.request_id,
                "tool_name": record.skill_name,
                "action": record.action,
                "allowed": record.allowed,
                "success": record.success,
                "denied_reason": record.denied_reason,
                "result_preview": record.result_preview,
                "args_preview": record.args_preview,
                "execution_time_ms": record.execution_time_ms,
                "platform": record.platform,
                "channel_id": record.channel_id,
                "user_id": record.user_id,
                "capabilities_used": list(record.capabilities_used or []),
            }
            for record in records
        ]
        return {
            "ok": True,
            "events": events,
            "stats": stats,
        }

    def _integration_secret_json(self, key: str) -> dict[str, Any]:
        raw = str(_get_secret(key) or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _integration_save_secret_json(self, key: str, value: dict[str, Any]) -> None:
        _set_secret(key, json.dumps(value))

    def _integration_callback_url(self, provider: str) -> str:
        port = int(getattr(self._config, "dashboard_port", 8080) or 8080)
        return f"http://127.0.0.1:{port}/api/integrations/oauth/{provider}/callback"

    def _integration_oauth_cfg(self, provider: str) -> dict[str, Any]:
        api_configs = self._config.apis if isinstance(self._config.apis, dict) else {}
        cfg = api_configs.get(provider, {})
        return cfg if isinstance(cfg, dict) else {}

    def _integration_env(self, provider: str, suffix: str) -> str:
        names = {
            "github": "GITHUB",
            "google_workspace": "GOOGLE_WORKSPACE",
            "slack": "SLACK",
        }
        prefix = names.get(provider, provider.upper())
        return str(os.environ.get(f"NEURALCLAW_{prefix}_OAUTH_{suffix}", "") or "").strip()

    def _integration_identity(self, provider: str) -> dict[str, Any]:
        return self._integration_secret_json(f"{provider}_oauth_identity")

    def _integration_client_id(self, provider: str) -> str:
        cfg = self._integration_oauth_cfg(provider)
        return str(cfg.get("client_id") or self._integration_env(provider, "CLIENT_ID") or "").strip()

    def _integration_client_secret(self, provider: str) -> str:
        return str(
            _get_secret(f"{provider}_oauth_client_secret")
            or self._integration_env(provider, "CLIENT_SECRET")
            or ""
        ).strip()

    def _integration_default_scopes(self, provider: str) -> list[str]:
        if provider == "github":
            return ["read:user", "repo", "workflow"]
        if provider == "google_workspace":
            return list(self._config.google_workspace.scopes or [])
        if provider == "slack":
            return [
                "app_mentions:read",
                "channels:history",
                "channels:read",
                "chat:write",
                "groups:history",
                "groups:read",
                "im:history",
                "im:read",
                "mpim:history",
                "mpim:read",
                "users:read",
            ]
        return []

    def _integration_scopes(self, provider: str) -> list[str]:
        cfg = self._integration_oauth_cfg(provider)
        raw = cfg.get("scopes")
        if isinstance(raw, list):
            scopes = [str(item).strip() for item in raw if str(item).strip()]
            if scopes:
                return scopes
        if isinstance(raw, str) and raw.strip():
            return [part.strip() for part in raw.replace(",", " ").split() if part.strip()]
        return self._integration_default_scopes(provider)

    def _integration_connect_ready(self, provider: str) -> bool:
        return bool(self._integration_client_id(provider) and self._integration_client_secret(provider))

    def _prune_oauth_states(self) -> None:
        now = time.time()
        expired = [state for state, payload in self._oauth_states.items() if float(payload.get("expires_at", 0)) < now]
        for state in expired:
            self._oauth_states.pop(state, None)

    async def _dashboard_connect_integration(self, integration_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        integration = str(integration_id or "").strip().lower()
        if integration not in {"github", "slack"}:
            if integration == "google_workspace":
                pass
            else:
                return {"ok": False, "error": f"Integration '{integration}' does not support browser connect yet."}

        client_id = str(payload.get("client_id") or self._integration_client_id(integration) or "").strip()
        client_secret = str(payload.get("client_secret") or self._integration_client_secret(integration) or "").strip()
        if not client_id or not client_secret:
            return {"ok": False, "error": f"{integration.title()} connect needs both client ID and client secret."}

        if integration == "github":
            if payload.get("client_secret"):
                _set_secret("github_oauth_client_secret", client_secret)
            scopes = self._integration_scopes("github")
            redirect_uri = self._integration_callback_url("github")
            state = secrets.token_urlsafe(24)
            self._prune_oauth_states()
            self._oauth_states[state] = {
                "provider": "github",
                "expires_at": time.time() + 900,
            }
            auth_url = "https://github.com/login/oauth/authorize?" + urlencode({
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(scopes),
                "state": state,
            })
            return {
                "ok": True,
                "auth_url": auth_url,
                "message": "Opened GitHub sign-in. Complete the browser flow, then return to NeuralClaw.",
            }

        if integration == "slack":
            if payload.get("client_secret"):
                _set_secret("slack_oauth_client_secret", client_secret)
            scopes = self._integration_scopes("slack")
            redirect_uri = self._integration_callback_url("slack")
            state = secrets.token_urlsafe(24)
            self._prune_oauth_states()
            self._oauth_states[state] = {
                "provider": "slack",
                "expires_at": time.time() + 900,
            }
            auth_url = "https://slack.com/oauth/v2/authorize?" + urlencode({
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": ",".join(scopes),
                "state": state,
            })
            return {
                "ok": True,
                "auth_url": auth_url,
                "message": "Opened Slack install flow. Complete the browser flow, then return to NeuralClaw.",
            }

        if integration == "google_workspace":
            if payload.get("client_secret"):
                _set_secret("google_workspace_oauth_client_secret", client_secret)
            scopes = self._integration_scopes("google_workspace")
            redirect_uri = self._integration_callback_url("google_workspace")
            state = secrets.token_urlsafe(24)
            self._prune_oauth_states()
            self._oauth_states[state] = {
                "provider": "google_workspace",
                "expires_at": time.time() + 900,
            }
            auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "access_type": "offline",
                "prompt": "consent",
                "scope": " ".join(scopes),
                "state": state,
            })
            return {
                "ok": True,
                "auth_url": auth_url,
                "message": "Opened Google sign-in. Complete the browser flow, then return to NeuralClaw.",
            }

        return {"ok": False, "error": f"Integration '{integration}' connect is not implemented."}

    async def _dashboard_handle_integration_callback(self, provider: str, params: dict[str, Any]) -> dict[str, Any]:
        integration = str(provider or "").strip().lower()
        if integration not in {"github", "slack", "google_workspace"}:
            return {"ok": False, "error": f"Unsupported OAuth provider '{integration}'."}
        error = str(params.get("error") or "").strip()
        if error:
            return {"ok": False, "error": error.replace("_", " ")}
        state = str(params.get("state") or "").strip()
        if not state:
            return {"ok": False, "error": "Missing OAuth state."}
        self._prune_oauth_states()
        state_payload = self._oauth_states.pop(state, None)
        if not state_payload or state_payload.get("provider") != integration:
            return {"ok": False, "error": "OAuth state is invalid or expired."}

        client_id = self._integration_client_id(integration)
        client_secret = self._integration_client_secret(integration)
        if not client_id or not client_secret:
            return {"ok": False, "error": f"{integration.title()} client credentials are missing."}

        code = str(params.get("code") or "").strip()
        if not code:
            return {"ok": False, "error": "Missing authorization code."}

        timeout = aiohttp.ClientTimeout(total=20)
        if integration == "github":
            redirect_uri = self._integration_callback_url("github")
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    "https://github.com/login/oauth/access_token",
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                ) as response:
                    token_payload = await response.json()
                access_token = str(token_payload.get("access_token") or "").strip()
                if not access_token:
                    return {"ok": False, "error": str(token_payload.get("error_description") or token_payload.get("error") or "GitHub token exchange failed.")}
                set_api_key("github", access_token)
                async with session.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                    },
                ) as user_response:
                    user_payload = await user_response.json()
            self._integration_save_secret_json("github_oauth_identity", {
                "login": str(user_payload.get("login") or ""),
                "name": str(user_payload.get("name") or ""),
                "avatar_url": str(user_payload.get("avatar_url") or ""),
            })
            reloaded = load_config(Path(self._config_path) if self._config_path else None)
            self._refresh_runtime_config(reloaded)
            return {"ok": True, "message": f"GitHub connected as {user_payload.get('login', 'unknown')}."}

        if integration == "slack":
            redirect_uri = self._integration_callback_url("slack")
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    "https://slack.com/api/oauth.v2.access",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                ) as response:
                    token_payload = await response.json()
            if not bool(token_payload.get("ok")):
                return {"ok": False, "error": str(token_payload.get("error") or "Slack OAuth failed.")}
            bot_token = str(token_payload.get("access_token") or "").strip()
            if not bot_token:
                return {"ok": False, "error": "Slack did not return a bot token."}
            set_api_key("slack", bot_token)
            team = token_payload.get("team", {}) if isinstance(token_payload.get("team"), dict) else {}
            self._integration_save_secret_json("slack_oauth_identity", {
                "team": str(team.get("name") or ""),
                "team_id": str(team.get("id") or ""),
                "app_id": str(token_payload.get("app_id") or ""),
                "bot_user_id": str(token_payload.get("bot_user_id") or ""),
            })
            reloaded = load_config(Path(self._config_path) if self._config_path else None)
            self._refresh_runtime_config(reloaded)
            return {"ok": True, "message": f"Slack connected to {team.get('name', 'workspace')}."}

        if integration == "google_workspace":
            redirect_uri = self._integration_callback_url("google_workspace")
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": redirect_uri,
                    },
                ) as response:
                    token_payload = await response.json()
                access_token = str(token_payload.get("access_token") or "").strip()
                if not access_token:
                    return {"ok": False, "error": str(token_payload.get("error_description") or token_payload.get("error") or "Google token exchange failed.")}
                refresh_token = str(token_payload.get("refresh_token") or "").strip()
                _set_secret("google_oauth_access", access_token)
                if refresh_token:
                    _set_secret("google_oauth_refresh", refresh_token)
                async with session.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                ) as user_response:
                    user_payload = await user_response.json()
            self._integration_save_secret_json("google_workspace_oauth_identity", {
                "email": str(user_payload.get("email") or ""),
                "name": str(user_payload.get("name") or ""),
                "picture": str(user_payload.get("picture") or ""),
            })
            update_config(
                {"google_workspace": {"enabled": True}},
                Path(self._config_path) if self._config_path else None,
            )
            reloaded = load_config(Path(self._config_path) if self._config_path else None)
            self._refresh_runtime_config(reloaded)
            return {"ok": True, "message": f"Google Workspace connected as {user_payload.get('email', 'unknown')}."}

        return {"ok": False, "error": f"Callback for '{integration}' is not implemented."}

    async def _dashboard_disconnect_integration(self, integration_id: str) -> dict[str, Any]:
        integration = str(integration_id or "").strip().lower()
        if integration == "github":
            clear_secret("github_api_key")
            clear_secret("github_token")
            clear_secret("github_oauth_client_secret")
            clear_secret("github_oauth_identity")
            reloaded = load_config(Path(self._config_path) if self._config_path else None)
            self._refresh_runtime_config(reloaded)
            return {"ok": True, "message": "GitHub connection removed."}
        if integration == "slack":
            clear_secret("slack_api_key")
            clear_secret("slack_app_api_key")
            clear_secret("slack_oauth_client_secret")
            clear_secret("slack_oauth_identity")
            reloaded = load_config(Path(self._config_path) if self._config_path else None)
            self._refresh_runtime_config(reloaded)
            return {"ok": True, "message": "Slack connection removed."}
        if integration == "google_workspace":
            clear_secret("google_oauth_access")
            clear_secret("google_oauth_refresh")
            clear_secret("google_workspace_oauth_client_secret")
            clear_secret("google_workspace_oauth_identity")
            update_config(
                {"google_workspace": {"enabled": False}},
                Path(self._config_path) if self._config_path else None,
            )
            reloaded = load_config(Path(self._config_path) if self._config_path else None)
            self._refresh_runtime_config(reloaded)
            return {"ok": True, "message": "Google Workspace connection removed."}
        if integration == "supabase":
            clear_secret("supabase_api_key")
            clear_secret("supabase_identity")
            return {"ok": True, "message": "Supabase connection removed."}
        return {"ok": False, "error": f"Integration '{integration}' does not support disconnect yet."}

    async def _dashboard_list_integrations(self) -> dict[str, Any]:
        integrations: list[dict[str, Any]] = []
        api_configs = self._config.apis if isinstance(self._config.apis, dict) else {}

        def api_policy(name: str) -> dict[str, Any]:
            cfg = api_configs.get(name, {}) if isinstance(api_configs.get(name, {}), dict) else {}
            return {
                "agent_access": str(cfg.get("agent_access") or "enabled"),
                "requires_confirmation": bool(cfg.get("requires_confirmation", True)),
            }

        def append_api_integration(
            *,
            integration_id: str,
            label: str,
            category: str,
            summary: str,
            default_base_url: str,
            tools: list[str],
            secret_names: list[str],
        ) -> None:
            cfg = api_configs.get(integration_id, {}) if isinstance(api_configs.get(integration_id, {}), dict) else {}
            has_token = any(bool(_get_secret(secret_name)) for secret_name in secret_names)
            identity = self._integration_identity(integration_id)
            integrations.append({
                "id": integration_id,
                "label": label,
                "category": category,
                "enabled": bool(cfg),
                "connected": has_token,
                "summary": summary,
                "details": {
                    "base_url": str(cfg.get("base_url") or default_base_url),
                    "auth_type": str(cfg.get("auth_type") or "bearer"),
                    "has_token": has_token,
                    "tools": tools,
                    "connect_ready": self._integration_connect_ready(integration_id),
                    "client_id_configured": bool(str(cfg.get("client_id") or "").strip()),
                    "identity": identity,
                    "scopes": self._integration_scopes(integration_id),
                    **api_policy(integration_id),
                },
            })

        append_api_integration(
            integration_id="github",
            label="GitHub",
            category="developer",
            summary="Issues, pull requests, CI status, and code review comments.",
            default_base_url="https://api.github.com",
            tools=[
                "github_list_pull_requests",
                "github_get_pull_request",
                "github_list_issues",
                "github_get_issue",
                "github_get_ci_status",
                "github_comment_issue",
            ],
            secret_names=["github_api_key", "github_token"],
        )
        append_api_integration(
            integration_id="jira",
            label="Jira",
            category="delivery",
            summary="Issue lookup, status changes, planning context, and delivery tracking.",
            default_base_url="https://your-domain.atlassian.net/rest/api/3",
            tools=["api_request"],
            secret_names=["jira_api_key"],
        )
        append_api_integration(
            integration_id="notion",
            label="Notion",
            category="knowledge",
            summary="Workspace docs, specs, project context, and shared team notes.",
            default_base_url="https://api.notion.com/v1",
            tools=["api_request"],
            secret_names=["notion_api_key"],
        )
        append_api_integration(
            integration_id="supabase",
            label="Supabase",
            category="data",
            summary="Supabase project APIs, auth settings, storage, and database-backed product context.",
            default_base_url="https://your-project.supabase.co",
            tools=["api_request"],
            secret_names=["supabase_api_key"],
        )
        google_token = bool(_get_secret("google_oauth_access") or _get_secret("google_oauth_refresh"))
        integrations.append({
            "id": "google_workspace",
            "label": "Google Workspace",
            "category": "productivity",
            "enabled": bool(self._config.google_workspace.enabled),
            "connected": google_token,
            "summary": "Gmail, Calendar, Drive, Docs, Sheets, and Meet.",
            "details": {
                "scopes": list(self._config.google_workspace.scopes or [])[:6],
                "connect_ready": self._integration_connect_ready("google_workspace"),
                "client_id_configured": bool(str(self._integration_oauth_cfg("google_workspace").get("client_id") or "").strip()),
                "identity": self._integration_identity("google_workspace"),
                **api_policy("google_workspace"),
            },
        })
        microsoft_token = bool(_get_secret("microsoft_oauth_access") or _get_secret("microsoft_oauth_refresh"))
        integrations.append({
            "id": "microsoft365",
            "label": "Microsoft 365",
            "category": "productivity",
            "enabled": bool(self._config.microsoft365.enabled),
            "connected": microsoft_token,
            "summary": "Outlook, Calendar, Teams, OneDrive, and SharePoint.",
            "details": {"tenant_id": str(self._config.microsoft365.tenant_id or "")},
        })
        if self._config.channels:
            for channel in self._config.channels:
                extra = getattr(channel, "extra", {}) or {}
                integrations.append({
                    "id": f"channel:{channel.name}",
                    "label": channel.name.title(),
                    "category": "channel",
                    "enabled": bool(channel.enabled),
                    "connected": bool(channel.token or extra.get("paired") or extra.get("app_token_present")),
                    "summary": f"{channel.name.title()} channel bridge.",
                    "details": {
                        "trust_mode": getattr(channel, "trust_mode", ""),
                        "paired": bool(extra.get("paired")),
                        "identity": self._integration_identity(channel.name),
                        "connect_ready": self._integration_connect_ready(channel.name),
                        **api_policy(channel.name),
                    },
                })
        try:
            from neuralclaw.skills.builtins import database_bi as _database_bi

            for name, conn in _database_bi._connections.items():
                integrations.append({
                    "id": f"db:{name}",
                    "label": name,
                    "category": "database",
                    "enabled": True,
                    "connected": bool(getattr(conn, "_conn", None)),
                    "summary": f"{conn.driver} analytical connection.",
                    "details": {"driver": conn.driver, "read_only": conn.read_only},
                })
        except Exception:
            pass
        return {"integrations": integrations, "count": len(integrations)}

    async def _dashboard_test_integration(self, integration_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        integration = str(integration_id or "").strip().lower()
        api_configs = self._config.apis if isinstance(self._config.apis, dict) else {}

        async def fetch_json(url: str, *, headers: dict[str, str] | None = None) -> tuple[int, Any]:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers or {}) as response:
                    content_type = response.headers.get("Content-Type", "")
                    if "json" in content_type.lower():
                        body = await response.json()
                    else:
                        body = await response.text()
                    return response.status, body

        if integration == "github":
            cfg = api_configs.get("github", {}) if isinstance(api_configs.get("github", {}), dict) else {}
            base_url = str(payload.get("base_url") or cfg.get("base_url") or "https://api.github.com").rstrip("/")
            token = str(payload.get("secret") or get_api_key("github") or _get_secret("github_token") or "").strip()
            if not token:
                return {"ok": False, "error": "GitHub token not configured."}
            status, body = await fetch_json(
                f"{base_url}/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            if status >= 400:
                return {"ok": False, "error": f"GitHub test failed ({status}).", "details": body}
            return {"ok": True, "message": f"Connected to GitHub as {body.get('login', 'unknown')}.", "details": body}

        if integration == "jira":
            cfg = api_configs.get("jira", {}) if isinstance(api_configs.get("jira", {}), dict) else {}
            raw_base = str(payload.get("base_url") or cfg.get("base_url") or "").strip()
            token = str(payload.get("secret") or get_api_key("jira") or "").strip()
            if not raw_base:
                return {"ok": False, "error": "Jira base URL not configured."}
            if not token:
                return {"ok": False, "error": "Jira token not configured."}
            base_url = raw_base.rstrip("/")
            probe_url = f"{base_url}/myself" if "/rest/api/" in base_url else f"{base_url}/rest/api/3/myself"
            status, body = await fetch_json(
                probe_url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            if status >= 400:
                return {"ok": False, "error": f"Jira test failed ({status}).", "details": body}
            return {"ok": True, "message": f"Connected to Jira as {body.get('displayName', 'unknown')}.", "details": body}

        if integration == "notion":
            cfg = api_configs.get("notion", {}) if isinstance(api_configs.get("notion", {}), dict) else {}
            base_url = str(payload.get("base_url") or cfg.get("base_url") or "https://api.notion.com/v1").rstrip("/")
            token = str(payload.get("secret") or get_api_key("notion") or "").strip()
            if not token:
                return {"ok": False, "error": "Notion token not configured."}
            status, body = await fetch_json(
                f"{base_url}/users/me",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Notion-Version": "2022-06-28",
                },
            )
            if status >= 400:
                return {"ok": False, "error": f"Notion test failed ({status}).", "details": body}
            notion_user = body.get("name") or body.get("bot", {}).get("owner", {}).get("user", {}).get("name") or "workspace"
            return {"ok": True, "message": f"Connected to Notion as {notion_user}.", "details": body}

        if integration == "google_workspace":
            if not self._config.google_workspace.enabled:
                return {"ok": False, "error": "Google Workspace is disabled."}
            token = str(_get_secret("google_oauth_access") or "").strip()
            if not token:
                return {"ok": False, "error": "Google OAuth token not configured."}
            status, body = await fetch_json(
                "https://www.googleapis.com/drive/v3/about?fields=user",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            if status >= 400:
                return {"ok": False, "error": f"Google Workspace test failed ({status}).", "details": body}
            user = body.get("user", {}) if isinstance(body, dict) else {}
            return {"ok": True, "message": f"Connected to Google Workspace as {user.get('displayName', 'unknown')}.", "details": body}

        if integration == "supabase":
            cfg = api_configs.get("supabase", {}) if isinstance(api_configs.get("supabase", {}), dict) else {}
            base_url = str(payload.get("base_url") or cfg.get("base_url") or "").strip().rstrip("/")
            token = str(payload.get("secret") or get_api_key("supabase") or "").strip()
            if not base_url:
                return {"ok": False, "error": "Supabase project URL not configured."}
            if not token:
                return {"ok": False, "error": "Supabase API key not configured."}
            status, body = await fetch_json(
                f"{base_url}/auth/v1/settings",
                headers={
                    "apikey": token,
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
            if status >= 400:
                return {"ok": False, "error": f"Supabase test failed ({status}).", "details": body}
            project_ref = base_url.split("://", 1)[-1].split(".", 1)[0]
            self._integration_save_secret_json("supabase_identity", {"project_ref": project_ref, "base_url": base_url})
            return {"ok": True, "message": f"Connected to Supabase project {project_ref}.", "details": body}

        return {"ok": False, "error": f"Integration '{integration}' does not have a test action yet."}

    async def _dashboard_get_agent_memories(self, agent_name: str) -> dict:
        if not self._agent_store:
            return {"ok": False, "error": "Agent store not available"}
        defn = await self._agent_store.get_by_name(agent_name)
        if not defn:
            return {"ok": False, "error": "Agent definition not found"}

        namespace = defn.memory_namespace or f"agent:{defn.name}"
        episodic = await self._episodic.get_for_namespace(namespace, limit=10) if self._episodic else []

        semantic_triples: list[dict[str, Any]] = []
        if self._semantic:
            semantic_mem = SemanticMemory(
                db_path=self._semantic._db_path,
                db_pool=self._semantic._db_pool,
                namespace=namespace,
            )
            semantic_mem._db = self._semantic._db
            semantic_triples = [
                {
                    "subject": triple.subject,
                    "predicate": triple.predicate,
                    "object": triple.obj,
                    "confidence": triple.confidence,
                }
                for triple in await semantic_mem.get_all_triples(limit=12)
            ]

        procedures: list[dict[str, Any]] = []
        if self._procedural:
            procedural_mem = ProceduralMemory(
                db_path=self._procedural._db_path,
                bus=self._procedural._bus,
                db_pool=self._procedural._db_pool,
                namespace=namespace,
            )
            procedural_mem._db = self._procedural._db
            procedures = [
                {
                    "id": proc.id,
                    "name": proc.name,
                    "description": proc.description,
                    "success_rate": proc.success_rate,
                    "last_used": proc.last_used,
                }
                for proc in await procedural_mem.get_all(limit=8)
            ]

        return {
            "ok": True,
            "namespace": namespace,
            "episodic": [
                {
                    "id": ep.id,
                    "content": ep.content,
                    "timestamp": ep.timestamp,
                    "source": ep.source,
                    "importance": ep.importance,
                }
                for ep in episodic
            ],
            "semantic": semantic_triples,
            "procedural": procedures,
        }

    async def _resolve_agent_execution_profile(self, agent_name: str) -> dict[str, Any]:
        definition = await self._agent_store.get_by_name(agent_name) if self._agent_store else None
        runtime = self._spawner.get_runtime(agent_name) if self._spawner else None
        provider, default_model, default_base_url = self._provider_default_route(
            (definition.provider if definition else "")
            or (runtime.definition.provider if runtime else "")
            or ""
        )
        requested_model = str(
            (definition.model if definition else "")
            or (runtime.definition.model if runtime else "")
            or default_model
            or ""
        ).strip()
        base_url = str(
            (definition.base_url if definition else "")
            or (runtime.definition.base_url if runtime else "")
            or default_base_url
            or ""
        ).strip()
        effective_model = requested_model
        fallback_reason = None

        if provider in {"local", "meta", "ollama"}:
            effective_model, base_url, fallback_reason = await self._resolve_local_model_with_fallback(
                requested_model,
                base_url,
            )
            self._ensure_local_chat_model(effective_model, context=f"agent '{agent_name}'")
            if definition and (definition.model != effective_model or definition.base_url != base_url):
                await self._agent_store.update(
                    definition.agent_id,
                    model=effective_model,
                    base_url=base_url,
                )
            if self._spawner:
                self._spawner.update_runtime_context(
                    agent_name,
                    requested_model=requested_model,
                    effective_model=effective_model,
                    base_url=base_url,
                )

        return {
            "provider": provider,
            "requested_model": requested_model,
            "effective_model": effective_model,
            "base_url": base_url,
            "fallback_reason": fallback_reason,
        }

    @staticmethod
    def _order_delegation_targets(task: str, targets: list[str]) -> list[str]:
        lowered = task.lower()
        indexed = []
        for position, name in enumerate(targets):
            mention = lowered.find(name.lower())
            indexed.append((mention if mention >= 0 else 1_000_000 + position, position, name))
        indexed.sort()
        return [name for _, _, name in indexed]

    def _get_memory_retention_windows(self) -> dict[str, int]:
        memory_cfg = getattr(self._config, "memory", None)
        return {
            "episodic": max(1, int(getattr(memory_cfg, "episodic_retention_days", 90) or 90)),
            "semantic": max(1, int(getattr(memory_cfg, "semantic_retention_days", 180) or 180)),
            "procedural": max(1, int(getattr(memory_cfg, "procedural_retention_days", 365) or 365)),
            "vector": max(1, int(getattr(memory_cfg, "vector_retention_days", 90) or 90)),
            "identity": max(1, int(getattr(memory_cfg, "identity_retention_days", 365) or 365)),
        }

    def _get_retention_cleanup_interval(self) -> float:
        memory_cfg = getattr(self._config, "memory", None)
        return max(30.0, float(getattr(memory_cfg, "retention_cleanup_interval_seconds", 300) or 300.0))

    def _scope_from_tags(self, tags: list[str] | None) -> str:
        for tag in tags or []:
            if tag.startswith("scope:"):
                return tag.split(":", 1)[1]
        return "global"

    def _build_memory_scope_tags(
        self,
        *,
        user_id: str = "",
        channel_id: str = "",
        metadata: dict[str, Any] | None = None,
        target_agent: str = "",
    ) -> list[str]:
        meta = metadata or {}
        scopes = ["scope:global"]
        if user_id:
            scopes.append(f"scope:contact:{user_id}")
        if channel_id:
            scopes.append(f"scope:channel:{channel_id}")
        session_id = str(meta.get("session_id") or "").strip()
        if session_id:
            scopes.append(f"scope:session:{session_id}")
        workspace = str(meta.get("workspace") or meta.get("workspace_id") or "").strip()
        if workspace:
            scopes.append(f"scope:workspace:{workspace}")
        project = str(meta.get("project") or meta.get("project_id") or "").strip()
        if project:
            scopes.append(f"scope:project:{project}")
        contact = str(meta.get("contact_id") or "").strip()
        if contact:
            scopes.append(f"scope:contact:{contact}")
        agent = target_agent or str(meta.get("target_agent") or "").strip()
        if agent:
            scopes.append(f"scope:agent:{agent}")
        return list(dict.fromkeys([scope for scope in scopes if scope]))

    def _build_memory_response_payload(
        self,
        response: str,
        *,
        confidence: float | None = None,
        memory_ctx: Any = None,
        confidence_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "response": response,
            "confidence": confidence,
            "memory_provenance": list(getattr(memory_ctx, "provenance", []) or []),
            "memory_scopes": list(getattr(memory_ctx, "scopes", []) or []),
            "confidence_contract": confidence_contract or {},
        }

    async def _apply_memory_retention_if_due(self, force: bool = False) -> dict[str, int]:
        now = time.time()
        if (
            not force
            and self._memory_retention_last_run
            and now - self._memory_retention_last_run < self._get_retention_cleanup_interval()
        ):
            return {}

        retention = self._get_memory_retention_windows()
        deleted: dict[str, int] = {}
        if self._store_is_initialized(self._episodic):
            deleted["episodic"] = int(await self._episodic.prune(retention["episodic"]))
        if self._store_is_initialized(self._semantic):
            deleted["semantic"] = int(await self._semantic.prune(retention["semantic"]))
        if self._store_is_initialized(self._procedural):
            deleted["procedural"] = int(await self._procedural.prune(retention["procedural"]))
        if self._store_is_initialized(self._vector_memory):
            deleted["vector"] = int(await self._vector_memory.prune(retention["vector"]))
        if self._store_is_initialized(self._identity):
            deleted["identity"] = int(await self._identity.prune(retention["identity"]))
        self._memory_retention_last_run = now
        return deleted

    def _store_is_initialized(self, store: Any) -> bool:
        if store is None:
            return False
        if not hasattr(store, "prune"):
            return False
        has_db_attr = hasattr(store, "_db")
        has_pool_attr = hasattr(store, "_db_pool")
        if not has_db_attr and not has_pool_attr:
            return True
        db_obj = getattr(store, "_db", None)
        return db_obj is not None

    def _backup_keystream(self, passphrase: str, salt: bytes, length: int) -> bytes:
        key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 120_000, dklen=32)
        chunks: list[bytes] = []
        counter = 0
        total = 0
        while total < length:
            counter_bytes = counter.to_bytes(8, "big", signed=False)
            block = hashlib.sha256(key + salt + counter_bytes).digest()
            chunks.append(block)
            total += len(block)
            counter += 1
        return b"".join(chunks)[:length]

    def _encrypt_backup_blob(self, payload: bytes, passphrase: str) -> dict[str, Any]:
        salt = secrets.token_bytes(16)
        keystream = self._backup_keystream(passphrase, salt, len(payload))
        cipher = bytes(a ^ b for a, b in zip(payload, keystream, strict=False))
        return {
            "encrypted": True,
            "salt": base64.b64encode(salt).decode("utf-8"),
            "digest": hashlib.sha256(payload).hexdigest(),
            "payload": base64.b64encode(cipher).decode("utf-8"),
        }

    def _decrypt_backup_blob(self, payload: str, salt: str, digest: str, passphrase: str) -> bytes:
        cipher = base64.b64decode(payload.encode("utf-8"))
        salt_bytes = base64.b64decode(salt.encode("utf-8"))
        keystream = self._backup_keystream(passphrase, salt_bytes, len(cipher))
        plain = bytes(a ^ b for a, b in zip(cipher, keystream, strict=False))
        if hashlib.sha256(plain).hexdigest() != digest:
            raise ValueError("Backup passphrase is invalid or backup is corrupted")
        return plain

    def _enrich_memory_item_metadata(self, item: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(item.get("metadata") or {})
        retention = self._get_memory_retention_windows()
        store = str(item.get("store", "") or "")
        if store == "episodic":
            metadata.setdefault("scope", self._scope_from_tags(metadata.get("tags")))
        elif store == "semantic":
            metadata.setdefault("scope", metadata.get("namespace") or "global")
        elif store == "procedural":
            metadata.setdefault("scope", metadata.get("namespace") or "global")
        elif store == "vector":
            metadata.setdefault("scope", "global")
        elif store == "identity":
            metadata.setdefault("scope", f"contact:{metadata.get('user_id')}" if metadata.get("user_id") else "global")
        metadata.setdefault("retention_days", retention.get(store, retention.get("episodic", 90)))
        item["metadata"] = metadata
        return item

    async def _dashboard_chat_with_agent(
        self,
        *,
        agent_name: str,
        content: str,
        media: list[dict[str, Any]] | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._mesh or not self._mesh.get_agent(agent_name):
            return {"ok": False, "error": f"Agent '{agent_name}' is not running"}

        profile = await self._resolve_agent_execution_profile(agent_name)
        timeout_seconds = 300.0 if profile.get("provider") in {"local", "meta", "ollama"} else 180.0
        request_id = self._mesh.record_message(
            from_agent="dashboard",
            to_agent=agent_name,
            content=content,
            message_type="chat",
            payload={
                "media": media or [],
                "metadata": metadata,
                "session_id": metadata.get("session_id"),
            },
        ).id
        response = await self._mesh.send(
            from_agent="dashboard",
            to_agent=agent_name,
            content=content,
            message_type="chat",
            payload={
                "media": media or [],
                "metadata": metadata,
                "session_id": metadata.get("session_id"),
            },
            timeout=timeout_seconds,
        )
        if not response or response.message_type == "error":
            return {
                "ok": False,
                "error": response.content if response else f"Agent '{agent_name}' did not respond",
                "requested_model": profile.get("requested_model"),
                "effective_model": profile.get("effective_model"),
            }

        effective_model = str(response.payload.get("model") or profile.get("effective_model") or "")
        self._mesh.record_message(
            from_agent=agent_name,
            to_agent="dashboard",
            content=response.content,
            message_type="chat_response",
            correlation_id=request_id,
            payload={
                "requested_model": profile.get("requested_model"),
                "effective_model": effective_model,
            },
        )
        return {
            "ok": True,
            "response": response.content,
            "routed_to": agent_name,
            "requested_model": profile.get("requested_model"),
            "effective_model": effective_model or profile.get("effective_model"),
            "fallback_reason": profile.get("fallback_reason"),
            "memory_provenance": [],
            "memory_scopes": [f"agent:{agent_name}"],
        }

    async def _dashboard_delegate_task(self, payload: dict[str, Any]) -> dict:
        if not self._delegation:
            return {"ok": False, "error": "Delegation not available"}
        from neuralclaw.swarm.delegation import DelegationContext, DelegationStatus

        task = str(payload.get("task", "")).strip()
        agent_name = str(payload.get("agent_name", "")).strip()
        agent_names = [
            str(name).strip()
            for name in payload.get("agent_names", [])
            if str(name).strip()
        ]
        shared_task_id = str(payload.get("shared_task_id", "")).strip()

        targets = agent_names or ([agent_name] if agent_name else [])
        if not task or not targets:
            return {"ok": False, "error": "task and target agent required"}
        dry_run = self._task_mark_dry_run(payload, mode="delegation", target_agents=targets)
        if dry_run:
            return dry_run
        targets = self._order_delegation_targets(task, targets)
        task_memory_ctx = await self._retriever.retrieve(task)
        task_provenance = list(getattr(task_memory_ctx, "provenance", []) or [])
        task_scopes = list(getattr(task_memory_ctx, "scopes", []) or [])

        profiles: dict[str, dict[str, Any]] = {}
        for target in targets:
            profiles[target] = await self._resolve_agent_execution_profile(target)

        timeout_seconds = max(
            180.0,
            float(payload.get("timeout_seconds") or 0.0),
            *(300.0 if profiles[target].get("provider") in {"local", "meta", "ollama"} else 180.0 for target in targets),
        )
        if self._task_requires_approval(payload):
            parent_profile = profiles[targets[0]]
            pending = await self._task_create_pending_approval(
                payload,
                orchestration_mode="manual" if len(targets) == 1 else "fanout",
                title=str(payload.get("title", "")).strip() or task.strip().splitlines()[0][:72] or "Delegated task",
                prompt=task,
                target_agents=targets,
                timeout_seconds=timeout_seconds,
                requested_model=str(parent_profile.get("requested_model", "")),
                effective_model=str(parent_profile.get("effective_model", "")),
                provider=str(parent_profile.get("provider", "")),
                base_url=str(parent_profile.get("base_url", "")),
                memory_provenance=task_provenance,
                memory_scopes=task_scopes,
                extra_metadata={"multi_agent": len(targets) > 1},
            )
            pending["requested_model"] = parent_profile.get("requested_model")
            pending["effective_model"] = parent_profile.get("effective_model")
            return pending
        ctx = DelegationContext(
            task_description=task,
            constraints={"shared_task_id": shared_task_id} if shared_task_id else {},
            timeout_seconds=timeout_seconds,
        )

        def log_activity(
            from_agent: str,
            to_agent: str,
            content: str,
            message_type: str,
            correlation_id: str | None = None,
            extra_payload: dict[str, Any] | None = None,
        ) -> str | None:
            if not self._mesh:
                return None
            event = self._mesh.record_message(
                from_agent=from_agent,
                to_agent=to_agent,
                content=content,
                message_type=message_type,
                payload={
                    **({"shared_task_id": shared_task_id} if shared_task_id else {}),
                    **(extra_payload or {}),
                },
                correlation_id=correlation_id,
            )
            return event.id

        try:
            from neuralclaw.swarm.task_store import TaskRecord
            task_id = ""
            child_task_ids: list[str] = []
            started_at = time.time()
            parent_metadata: dict[str, Any] = {}
            child_metadata: dict[str, dict[str, Any]] = {}
            if self._task_store:
                parent_profile = profiles[targets[0]]
                existing_task_id = str(payload.get("__task_id", "")).strip()
                parent_metadata = self._build_task_metadata(
                    payload,
                    orchestration_mode="manual" if len(targets) == 1 else "fanout",
                    target_agents=targets,
                    timeout_seconds=timeout_seconds,
                    memory_provenance=task_provenance,
                    memory_scopes=task_scopes,
                    fallback_reason=parent_profile.get("fallback_reason"),
                )
                parent_metadata["multi_agent"] = len(targets) > 1
                if existing_task_id:
                    task_id = existing_task_id
                    existing = await self._task_store.get(task_id)
                    if existing:
                        parent_metadata = {
                            **dict(existing.metadata or {}),
                            **parent_metadata,
                            "approval": self._task_mark_approved(dict(existing.metadata or {})).get("approval"),
                        }
                    parent_metadata["execution_log"].append(
                        self._task_log_entry("delegated", f"Dispatched to {', '.join(targets)}", status="running")
                    )
                    await self._task_store.update(
                        task_id,
                        status="running",
                        provider=str(parent_profile.get("provider", "")),
                        requested_model=str(parent_profile.get("requested_model", "")),
                        effective_model=str(parent_profile.get("effective_model", "")),
                        base_url=str(parent_profile.get("base_url", "")),
                        target_agents=targets,
                        shared_task_id=shared_task_id,
                        started_at=started_at,
                        metadata=parent_metadata,
                    )
                else:
                    parent_task = TaskRecord(
                        task_id="",
                        title=(str(parent_metadata.get("brief", {}).get("title_override", "")).strip() or task.strip().splitlines()[0][:72] or "Delegated task"),
                        prompt=task,
                        status="running",
                        provider=str(parent_profile.get("provider", "")),
                        requested_model=str(parent_profile.get("requested_model", "")),
                        effective_model=str(parent_profile.get("effective_model", "")),
                        base_url=str(parent_profile.get("base_url", "")),
                        target_agents=targets,
                        shared_task_id=shared_task_id,
                        started_at=started_at,
                        metadata=parent_metadata,
                    )
                    task_id = await self._task_store.create(parent_task)
                for target in targets:
                    profile = profiles[target]
                    child_meta = self._build_task_metadata(
                        payload,
                        orchestration_mode="delegated-child",
                        target_agents=[target],
                        timeout_seconds=timeout_seconds,
                        memory_provenance=task_provenance,
                        memory_scopes=task_scopes,
                        fallback_reason=profile.get("fallback_reason"),
                    )
                    child_meta["execution_log"].append(
                        self._task_log_entry("delegated", f"Task assigned to {target}", agent=target, status="running")
                    )
                    child_metadata[target] = child_meta
                    child_id = await self._task_store.create(
                        TaskRecord(
                            task_id="",
                            title=f"{target}: {task.strip().splitlines()[0][:56] or 'Delegated task'}",
                            prompt=task,
                            status="running",
                            provider=str(profile.get("provider", "")),
                            requested_model=str(profile.get("requested_model", "")),
                            effective_model=str(profile.get("effective_model", "")),
                            base_url=str(profile.get("base_url", "")),
                            target_agents=[target],
                            shared_task_id=shared_task_id,
                            parent_task_id=task_id,
                            started_at=started_at,
                            metadata=child_meta,
                        )
                    )
                    child_task_ids.append(child_id)
                await self._task_store.update(task_id, child_task_ids=child_task_ids, metadata=parent_metadata)

            if len(targets) == 1:
                request_id = log_activity(
                    from_agent="dashboard",
                    to_agent=targets[0],
                    content=task,
                    message_type="delegation",
                )
                result = await self._delegation.delegate(targets[0], ctx)
                profile = profiles[targets[0]]
                completed_at = time.time()
                log_activity(
                    from_agent=targets[0],
                    to_agent="dashboard",
                    content=result.result or result.error or result.status.name.lower(),
                    message_type="delegation_result",
                    correlation_id=request_id,
                    extra_payload={
                        "status": result.status.name.lower(),
                        "confidence": result.confidence,
                        "error": result.error,
                        "task_id": child_task_ids[0] if child_task_ids else None,
                    },
                )
                completed = result.status == DelegationStatus.COMPLETED
                if self._task_store:
                    teaching_artifacts = await self._capture_teaching_artifact_if_needed(
                        source_id=task_id or child_task_ids[0],
                        payload=payload,
                        result_text=result.result or result.error or "",
                    )
                    child_status = result.status.name.lower()
                    result_text = result.result or ""
                    error_text = result.error or ""
                    final_child_meta = {
                        **child_metadata.get(targets[0], {}),
                        "confidence": result.confidence,
                        "teaching_artifacts": teaching_artifacts,
                        "confidence_contract": self._task_confidence_contract(
                            confidence=result.confidence,
                            source="delegation",
                            evidence_sources=["delegated_agent", "task_result"],
                            escalation_recommendation="operator_review_recommended" if not completed else "none",
                        ),
                        "effective_model": str(profile.get("effective_model", "")),
                        "artifacts": self._extract_result_artifacts(result_text, agent=targets[0]),
                        "followups": self._build_task_followups(
                            status=child_status,
                            result_text=result_text,
                            error_text=error_text,
                        ),
                        "execution_log": [
                            *(child_metadata.get(targets[0], {}).get("execution_log", [])),
                            self._task_log_entry(
                                "completed" if completed else "failed",
                                result_text[:200] or error_text[:200] or child_status,
                                agent=targets[0],
                                status=child_status,
                            ),
                        ],
                    }
                    final_child_meta["change_receipt"] = self._task_change_receipt(
                        task_id=child_task_ids[0],
                        metadata=final_child_meta,
                        operations=["delegated", child_status],
                    )
                    final_child_meta["receipt_refs"] = [final_child_meta["change_receipt"]["receipt_id"]]
                    await self._task_store.update(
                        child_task_ids[0],
                        status=child_status,
                        result=result_text,
                        error=error_text,
                        completed_at=completed_at,
                        started_at=started_at,
                        effective_model=str(profile.get("effective_model", "")),
                        metadata=final_child_meta,
                    )
                    parent_metadata = {
                        **parent_metadata,
                        "confidence": result.confidence,
                        "teaching_artifacts": teaching_artifacts,
                        "confidence_contract": self._task_confidence_contract(
                            confidence=result.confidence,
                            source="delegation_parent",
                            evidence_sources=["delegated_agent", "aggregated_result"],
                            escalation_recommendation="operator_review_recommended" if not completed else "none",
                        ),
                        "effective_model": str(profile.get("effective_model", "")),
                        "artifacts": self._extract_result_artifacts(result_text, agent=targets[0]),
                        "followups": self._build_task_followups(
                            status=child_status,
                            result_text=result_text,
                            error_text=error_text,
                        ),
                        "execution_log": [
                            *(parent_metadata.get("execution_log", [])),
                            self._task_log_entry(
                                "completed" if completed else "failed",
                                f"{targets[0]} returned {child_status}",
                                agent=targets[0],
                                status=child_status,
                            ),
                        ],
                    }
                    parent_metadata["change_receipt"] = self._task_change_receipt(
                        task_id=task_id,
                        metadata=parent_metadata,
                        operations=["delegated", child_status],
                    )
                    parent_metadata["receipt_refs"] = [parent_metadata["change_receipt"]["receipt_id"]]
                    await self._task_store.update(
                        task_id,
                        status=child_status,
                        result=result_text,
                        error=error_text,
                        completed_at=completed_at,
                        started_at=started_at,
                        effective_model=str(profile.get("effective_model", "")),
                        metadata=parent_metadata,
                    )
                return {
                    "ok": completed,
                    "task_id": task_id or None,
                    "child_task_ids": child_task_ids,
                    "status": result.status.name.lower(),
                    "result": result.result or result.error or "",
                    "confidence": result.confidence,
                    "requested_model": profile.get("requested_model"),
                    "effective_model": profile.get("effective_model"),
                    "memory_provenance": task_provenance,
                    "memory_scopes": task_scopes,
                    "results": [
                        {
                            "agent": targets[0],
                            "status": result.status.name.lower(),
                            "result": result.result or "",
                            "confidence": result.confidence,
                            "error": result.error,
                            "requested_model": profile.get("requested_model"),
                            "effective_model": profile.get("effective_model"),
                        }
                    ],
                    "error": None if completed else (result.error or "Delegation failed"),
                    "shared_task_id": shared_task_id or None,
                }

            request_ids: dict[str, str | None] = {}
            results = []
            parent_memories: list[dict[str, Any]] = []
            for name in targets:
                request_ids[name] = log_activity(
                    from_agent="dashboard",
                    to_agent=name,
                    content=task,
                    message_type="delegation",
                )
                step_ctx = DelegationContext(
                    task_description=task,
                    parent_memories=list(parent_memories),
                    constraints={"shared_task_id": shared_task_id} if shared_task_id else {},
                    timeout_seconds=timeout_seconds,
                )
                res = await self._delegation.delegate(name, step_ctx)
                results.append(res)
                if res.result:
                    parent_memories.append({
                        "agent": name,
                        "result": res.result,
                    })
                elif res.error:
                    parent_memories.append({
                        "agent": name,
                        "error": res.error,
                    })
            for agent, res in zip(targets, results, strict=False):
                profile = profiles[agent]
                log_activity(
                    from_agent=agent,
                    to_agent="dashboard",
                    content=res.result or res.error or res.status.name.lower(),
                    message_type="delegation_result",
                    correlation_id=request_ids.get(agent),
                    extra_payload={
                        "status": res.status.name.lower(),
                        "confidence": res.confidence,
                        "error": res.error,
                        "task_id": child_task_ids[targets.index(agent)] if child_task_ids else None,
                    },
                )
            completed_count = sum(1 for res in results if res.status == DelegationStatus.COMPLETED)
            completed_at = time.time()
            aggregate_status = (
                "completed" if completed_count == len(results)
                else "partial" if completed_count > 0
                else "failed"
            )
            aggregate_result = "\n\n".join(
                (
                    f"[{agent}] {res.result}".strip()
                    if res.result
                    else f"[{agent}] {res.error or res.status.name.lower()}"
                )
                for agent, res in zip(targets, results, strict=False)
            ).strip()
            if self._task_store:
                teaching_artifacts = await self._capture_teaching_artifact_if_needed(
                    source_id=task_id or f"fanout-{int(time.time())}",
                    payload=payload,
                    result_text=aggregate_result,
                )
                for agent, child_id, res in zip(targets, child_task_ids, results, strict=False):
                    profile = profiles[agent]
                    result_text = res.result or ""
                    error_text = res.error or ""
                    child_status = res.status.name.lower()
                    child_meta = {
                        **child_metadata.get(agent, {}),
                        "confidence": res.confidence,
                        "confidence_contract": self._task_confidence_contract(
                            confidence=res.confidence,
                            source="delegation",
                            evidence_sources=["delegated_agent", "task_result"],
                            escalation_recommendation="operator_review_recommended" if child_status != "completed" else "none",
                        ),
                        "effective_model": str(profile.get("effective_model", "")),
                        "artifacts": self._extract_result_artifacts(result_text, agent=agent),
                        "followups": self._build_task_followups(
                            status=child_status,
                            result_text=result_text,
                            error_text=error_text,
                        ),
                        "execution_log": [
                            *(child_metadata.get(agent, {}).get("execution_log", [])),
                            self._task_log_entry(
                                "completed" if child_status == "completed" else "failed",
                                result_text[:200] or error_text[:200] or child_status,
                                agent=agent,
                                status=child_status,
                            ),
                        ],
                    }
                    child_meta["change_receipt"] = self._task_change_receipt(
                        task_id=child_id,
                        metadata=child_meta,
                        operations=["delegated", child_status],
                    )
                    child_meta["receipt_refs"] = [child_meta["change_receipt"]["receipt_id"]]
                    await self._task_store.update(
                        child_id,
                        status=child_status,
                        result=result_text,
                        error=error_text,
                        completed_at=completed_at,
                        started_at=started_at,
                        effective_model=str(profile.get("effective_model", "")),
                        metadata=child_meta,
                    )
                aggregate_artifacts = []
                for agent, res in zip(targets, results, strict=False):
                    aggregate_artifacts.extend(self._extract_result_artifacts(res.result or "", agent=agent, limit=3))
                parent_metadata = {
                    **parent_metadata,
                    "teaching_artifacts": teaching_artifacts,
                    "confidence_contract": self._task_confidence_contract(
                        confidence=(sum(float(res.confidence or 0.0) for res in results) / len(results)) if results else None,
                        source="delegation_fanout",
                        evidence_sources=["delegated_agents", "aggregated_result"],
                        escalation_recommendation="operator_review_recommended" if aggregate_status != "completed" else "none",
                    ),
                    "fallback_reasons": {
                        agent: profile.get("fallback_reason")
                        for agent, profile in profiles.items()
                        if profile.get("fallback_reason")
                    },
                    "artifacts": aggregate_artifacts[:12],
                    "followups": self._build_task_followups(
                        status=aggregate_status,
                        result_text=aggregate_result,
                        error_text="" if completed_count > 0 else "Delegation failed for all selected agents",
                    ),
                    "execution_log": [
                        *(parent_metadata.get("execution_log", [])),
                        *[
                            self._task_log_entry(
                                "agent_result",
                                f"{agent}: {res.status.name.lower()}",
                                agent=agent,
                                status=res.status.name.lower(),
                            )
                            for agent, res in zip(targets, results, strict=False)
                        ],
                        self._task_log_entry(
                            "completed" if aggregate_status == "completed" else "partial",
                            f"Fan-out run finished with {completed_count}/{len(results)} successful agents",
                            status=aggregate_status,
                        ),
                    ],
                }
                parent_metadata["change_receipt"] = self._task_change_receipt(
                    task_id=task_id,
                    metadata=parent_metadata,
                    operations=["fanout_delegation", aggregate_status],
                )
                parent_metadata["receipt_refs"] = [parent_metadata["change_receipt"]["receipt_id"]]
                await self._task_store.update(
                    task_id,
                    status=aggregate_status,
                    result=aggregate_result,
                    error="" if completed_count > 0 else "Delegation failed for all selected agents",
                    completed_at=completed_at,
                    started_at=started_at,
                    metadata=parent_metadata,
                )
            return {
                "ok": completed_count > 0,
                "task_id": task_id or None,
                "child_task_ids": child_task_ids,
                "status": aggregate_status,
                "result": aggregate_result,
                "results": [
                    {
                        "agent": agent,
                        "status": res.status.name.lower(),
                        "result": res.result or "",
                        "confidence": res.confidence,
                        "error": res.error,
                        "requested_model": profiles[agent].get("requested_model"),
                        "effective_model": profiles[agent].get("effective_model"),
                    }
                    for agent, res in zip(targets, results, strict=False)
                ],
                "requested_model": profiles[targets[0]].get("requested_model"),
                "effective_model": profiles[targets[0]].get("effective_model"),
                "memory_provenance": task_provenance,
                "memory_scopes": task_scopes,
                "error": None if completed_count > 0 else "Delegation failed for all selected agents",
                "shared_task_id": shared_task_id or None,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _dashboard_auto_route_task(self, payload: dict[str, Any]) -> dict:
        """Pick the best running agent(s) for a task and delegate automatically."""
        task = str(payload.get("task", "")).strip()
        max_agents = int(payload.get("max_agents", 1))
        if not task:
            return {"ok": False, "error": "task is required"}
        if not self._mesh:
            return {"ok": False, "error": "Agent mesh not available"}

        running_agents = list(self._mesh._agents.keys()) if hasattr(self._mesh, "_agents") else []
        if not running_agents:
            return {"ok": False, "error": "No running agents available"}

        # Score agents by capability match
        task_lower = task.lower()
        scored: list[tuple[int, str]] = []
        for name in running_agents:
            agent_obj = self._mesh._agents.get(name)
            caps: list[str] = []
            if agent_obj:
                caps = list(getattr(agent_obj, "capabilities", None) or [])
            score = sum(
                1
                for cap in caps
                if any(word in cap.lower() for word in task_lower.split() if len(word) > 3)
            )
            scored.append((score, name))

        scored.sort(key=lambda x: -x[0])
        selected = [name for _, name in scored[:max_agents]]
        if not selected:
            selected = running_agents[:max_agents]
        if self._task_requires_approval(payload):
            task_memory_ctx = await self._retriever.retrieve(task)
            pending = await self._task_create_pending_approval(
                payload,
                orchestration_mode="auto-route",
                title=str(payload.get("title", "")).strip() or task.strip().splitlines()[0][:72] or "Auto-route task",
                prompt=task,
                target_agents=selected,
                timeout_seconds=max(180.0, float(payload.get("timeout_seconds", 180.0))),
                memory_provenance=list(getattr(task_memory_ctx, "provenance", []) or []),
                memory_scopes=list(getattr(task_memory_ctx, "scopes", []) or []),
                extra_metadata={"routed_preview": selected},
            )
            pending["routed_to"] = selected
            return pending

        shared_task_id: str | None = None
        if len(selected) > 1 and self._shared_bridge:
            shared_task = await self._shared_bridge.create_shared_task(selected)
            shared_task_id = shared_task.task_id

        delegate_payload: dict[str, Any] = {
            "task": task,
            "agent_names": selected,
        }
        for key in ("title", "success_criteria", "deliverables", "workspace_path", "integration_targets", "execution_mode"):
            if key in payload:
                delegate_payload[key] = payload.get(key)
        if shared_task_id:
            delegate_payload["shared_task_id"] = shared_task_id

        result = await self._dashboard_delegate_task(delegate_payload)
        result["routed_to"] = selected
        return result

    async def _dashboard_pipeline_task(self, payload: dict[str, Any]) -> dict:
        """
        Run agents sequentially — each agent's output is fed as input to the next.
        Planner → Coder → Reviewer, etc.
        """
        if not self._delegation:
            return {"ok": False, "error": "Delegation not available"}
        from neuralclaw.swarm.delegation import DelegationContext, DelegationStatus
        from neuralclaw.swarm.task_store import TaskRecord

        task = str(payload.get("task", "")).strip()
        agents: list[str] = [str(n).strip() for n in payload.get("agent_names", []) if str(n).strip()]
        if not task or not agents:
            return {"ok": False, "error": "task and agent_names required"}
        dry_run = self._task_mark_dry_run(payload, mode="pipeline", target_agents=agents, extra={"agent_order": agents})
        if dry_run:
            return dry_run

        timeout = max(180.0, float(payload.get("timeout_seconds", 300.0)))
        task_memory_ctx = await self._retriever.retrieve(task)
        if self._task_requires_approval(payload):
            return await self._task_create_pending_approval(
                payload,
                orchestration_mode="pipeline",
                title=str(payload.get("title", "")).strip() or task.strip().splitlines()[0][:72] or "Pipeline task",
                prompt=task,
                target_agents=agents,
                timeout_seconds=timeout,
                memory_provenance=list(getattr(task_memory_ctx, "provenance", []) or []),
                memory_scopes=list(getattr(task_memory_ctx, "scopes", []) or []),
                extra_metadata={"agent_order": agents},
            )

        # Create a shared task so all results are stored together
        shared_task_id = ""
        if self._shared_bridge and len(agents) > 1:
            shared_task = await self._shared_bridge.create_shared_task(agents)
            shared_task_id = shared_task.task_id

        # Create parent task record
        task_id = ""
        started_at = time.time()
        pipeline_metadata = self._build_task_metadata(
            payload,
            orchestration_mode="pipeline",
            target_agents=agents,
            timeout_seconds=timeout,
            memory_provenance=list(getattr(task_memory_ctx, "provenance", []) or []),
            memory_scopes=list(getattr(task_memory_ctx, "scopes", []) or []),
        )
        pipeline_metadata["agent_order"] = agents
        pipeline_metadata["plan"] = self._build_pipeline_plan(payload, task, agents)
        pipeline_metadata["why_trace"] = self._build_pipeline_why_trace(agents=agents, step_results=[])
        if self._task_store:
            existing_task_id = str(payload.get("__task_id", "")).strip()
            parent = TaskRecord(
                task_id="",
                title=(str(pipeline_metadata.get("brief", {}).get("title_override", "")).strip() or task.strip().splitlines()[0][:72] or "Pipeline task"),
                prompt=task,
                status="running",
                provider="",
                requested_model="",
                effective_model="",
                base_url="",
                target_agents=agents,
                shared_task_id=shared_task_id or None,
                started_at=started_at,
                metadata=pipeline_metadata,
            )
            if existing_task_id:
                task_id = existing_task_id
                existing = await self._task_store.get(task_id)
                if existing:
                    pipeline_metadata = {
                        **dict(existing.metadata or {}),
                        **pipeline_metadata,
                    }
                    if existing.shared_task_id:
                        shared_task_id = existing.shared_task_id
                pipeline_metadata["execution_log"] = [
                    *(pipeline_metadata.get("execution_log", [])),
                    self._task_log_entry(
                        "resumed",
                        "Resuming pipeline from the latest checkpoint.",
                        status="running",
                    ),
                ]
                await self._task_store.update(
                    task_id,
                    status="running",
                    target_agents=agents,
                    shared_task_id=shared_task_id or None,
                    started_at=started_at,
                    metadata=pipeline_metadata,
                )
            else:
                task_id = await self._task_store.create(parent)

        try:
            checkpoints = list(pipeline_metadata.get("checkpoints", []) or [])
            resume_index = self._pipeline_resume_index(checkpoints, len(agents))
            step_results: list[dict[str, Any]] = []
            parent_memories: list[dict[str, Any]] = []

            for checkpoint in sorted(checkpoints, key=lambda item: int(item.get("stage_index", 0))):
                if int(checkpoint.get("stage_index", -1)) >= resume_index:
                    continue
                restored = {
                    "stage_index": int(checkpoint.get("stage_index", 0)),
                    "stage_role": str(checkpoint.get("stage_role") or self._pipeline_stage_role(int(checkpoint.get("stage_index", 0)), len(agents))),
                    "agent": str(checkpoint.get("agent") or ""),
                    "status": str(checkpoint.get("status") or "completed"),
                    "result": str(checkpoint.get("result") or ""),
                    "confidence": float(checkpoint.get("confidence") or 0.0),
                    "elapsed_seconds": float(checkpoint.get("elapsed_seconds") or 0.0),
                    "error": checkpoint.get("error"),
                    "artifact_handoff": list(checkpoint.get("artifact_handoff") or []),
                }
                step_results.append(restored)
                if restored["result"]:
                    parent_memories.append({"agent": restored["agent"], "result": restored["result"]})
                elif restored.get("error"):
                    parent_memories.append({"agent": restored["agent"], "error": restored["error"]})

            results = []
            for stage_index in range(resume_index, len(agents)):
                agent = agents[stage_index]
                role = self._pipeline_stage_role(stage_index, len(agents))
                stage_prompt = self._build_pipeline_stage_prompt(
                    task=task,
                    payload=payload,
                    agents=agents,
                    stage_index=stage_index,
                    prior_steps=step_results,
                )
                stage_ctx = DelegationContext(
                    task_description=stage_prompt,
                    parent_memories=list(parent_memories),
                    constraints={
                        "pipeline_stage_index": stage_index,
                        "pipeline_stage_role": role,
                        "pipeline_total": len(agents),
                        **({"shared_task_id": shared_task_id} if shared_task_id else {}),
                    },
                    timeout_seconds=timeout,
                )
                res = await self._delegation.delegate(agent, stage_ctx)
                results.append(res)
                stage_result = {
                    "stage_index": stage_index,
                    "stage_role": role,
                    "agent": agent,
                    "status": res.status.name.lower(),
                    "result": res.result,
                    "confidence": res.confidence,
                    "elapsed_seconds": round(res.elapsed_seconds, 2),
                    "error": res.error,
                    "artifact_handoff": self._extract_result_artifacts(res.result or "", agent=agent, limit=6),
                }
                step_results.append(stage_result)
                checkpoints = [
                    item for item in checkpoints
                    if int(item.get("stage_index", -1)) != stage_index
                ]
                checkpoints.append(
                    self._build_pipeline_checkpoint(
                        stage_index=stage_index,
                        total_stages=len(agents),
                        agent=agent,
                        result=stage_result,
                    )
                )
                checkpoints.sort(key=lambda item: int(item.get("stage_index", 0)))
                if stage_result["result"]:
                    parent_memories.append({"agent": agent, "result": stage_result["result"]})
                elif stage_result.get("error"):
                    parent_memories.append({"agent": agent, "error": stage_result["error"]})

                pipeline_metadata = {
                    **pipeline_metadata,
                    "checkpoints": checkpoints,
                    "steps": step_results,
                    "confidence_contract": self._task_confidence_contract(
                        confidence=stage_result.get("confidence"),
                        source="pipeline_stage",
                        evidence_sources=["pipeline_stage", "checkpoint"],
                        escalation_recommendation="operator_review_recommended" if stage_result["status"] != "completed" else "none",
                    ),
                    "why_trace": self._build_pipeline_why_trace(agents=agents, step_results=step_results),
                    "execution_log": [
                        *(pipeline_metadata.get("execution_log", [])),
                        self._task_log_entry(
                            "pipeline_stage",
                            f"{role} stage completed by {agent}" if stage_result["status"] == "completed" else f"{role} stage failed in {agent}",
                            agent=agent,
                            status=stage_result["status"],
                        ),
                    ],
                }
                if task_id:
                    pipeline_metadata["change_receipt"] = self._task_change_receipt(
                        task_id=task_id,
                        metadata=pipeline_metadata,
                        operations=[f"pipeline_stage:{role}", stage_result["status"]],
                    )
                    pipeline_metadata["receipt_refs"] = [pipeline_metadata["change_receipt"]["receipt_id"]]
                if self._task_store and task_id:
                    await self._task_store.update(
                        task_id,
                        status="running" if stage_result["status"] == "completed" and stage_index < len(agents) - 1 else stage_result["status"],
                        result=stage_result["result"] if stage_result["status"] == "completed" else "",
                        error=stage_result["error"] or "",
                        metadata=pipeline_metadata,
                    )
                if res.status != DelegationStatus.COMPLETED:
                    break
        except Exception as e:
            if self._task_store and task_id:
                pipeline_metadata = {
                    **pipeline_metadata,
                    "confidence_contract": self._task_confidence_contract(
                        confidence=0.0,
                        source="pipeline_error",
                        uncertainty_factors=["execution_error"],
                        evidence_sources=["pipeline_runtime"],
                        escalation_recommendation="operator_review_recommended",
                        retry_rationale=str(e),
                    ),
                    "change_receipt": self._task_change_receipt(
                        task_id=task_id,
                        metadata=pipeline_metadata,
                        operations=["pipeline_failed"],
                    ),
                    "receipt_refs": [f"receipt-{task_id}"],
                }
                await self._task_store.update(task_id, status="failed", error=str(e),
                                              completed_at=time.time(),
                                              duration_ms=int((time.time() - started_at) * 1000),
                                              metadata=pipeline_metadata)
            return {"ok": False, "error": str(e)}

        # Build response
        final_result = ""
        all_completed = bool(step_results) and len(step_results) == len(agents) and all(step.get("status") == "completed" for step in step_results)
        completed_steps = sum(1 for step in step_results if step.get("status") == "completed")
        final_status = (
            "completed"
            if all_completed
            else "partial" if completed_steps > 0
            else "failed"
        )
        if step_results:
            reviewer_step = next((step for step in reversed(step_results) if step.get("stage_role") == "reviewer"), step_results[-1])
            final_result = str(reviewer_step.get("result") or step_results[-1].get("result") or "")

        if self._task_store and task_id:
            teaching_artifacts = await self._capture_teaching_artifact_if_needed(
                source_id=task_id,
                payload=payload,
                result_text=final_result,
            )
            aggregate_artifacts: list[dict[str, Any]] = []
            for step in step_results:
                aggregate_artifacts.extend(list(step.get("artifact_handoff") or []))
            pipeline_metadata = {
                **pipeline_metadata,
                "artifacts": aggregate_artifacts[:12] or self._extract_result_artifacts(final_result),
                "teaching_artifacts": teaching_artifacts,
                "followups": self._build_task_followups(
                    status=final_status,
                    result_text=final_result,
                ),
                "steps": step_results,
                "confidence_contract": self._task_confidence_contract(
                    confidence=(reviewer_step.get("confidence") if step_results else None),
                    source="pipeline_final",
                    evidence_sources=["pipeline_steps", "review_output"],
                    escalation_recommendation="operator_review_recommended" if final_status != "completed" else "none",
                ),
                "review": self._build_pipeline_review(
                    task=task,
                    agents=agents,
                    step_results=step_results,
                    final_result=final_result,
                ),
                "why_trace": self._build_pipeline_why_trace(agents=agents, step_results=step_results),
                "execution_log": [
                    *(pipeline_metadata.get("execution_log", [])),
                    *[
                        self._task_log_entry(
                            "pipeline_step",
                            f"{step['stage_role']}:{step['agent']} -> {step['status']}",
                            agent=step["agent"],
                            status=step["status"],
                        )
                        for step in step_results
                    ],
                    self._task_log_entry(
                        "review_complete",
                        "Pipeline review completed and final output assembled." if all_completed else "Pipeline ended with partial progress and preserved checkpoints.",
                        status=final_status,
                    ),
                ],
            }
            pipeline_metadata["change_receipt"] = self._task_change_receipt(
                task_id=task_id,
                metadata=pipeline_metadata,
                operations=["pipeline_complete", final_status],
            )
            pipeline_metadata["receipt_refs"] = [pipeline_metadata["change_receipt"]["receipt_id"]]
            await self._task_store.update(
                task_id,
                status=final_status,
                result=final_result,
                completed_at=time.time(),
                duration_ms=int((time.time() - started_at) * 1000),
                metadata=pipeline_metadata,
            )

        return {
            "ok": bool(step_results),
            "status": final_status,
            "pipeline_results": step_results,
            "final_result": final_result,
            "shared_task_id": shared_task_id or None,
            "task_id": task_id or None,
            "error": None if final_status != "failed" else "Pipeline did not complete any stage.",
        }

    async def _dashboard_seek_consensus(self, payload: dict[str, Any]) -> dict:
        """Run ConsensusProtocol across selected agents and return the agreed result."""
        if not self._consensus:
            return {"ok": False, "error": "Consensus not available (swarm feature disabled)"}
        from neuralclaw.swarm.consensus import ConsensusStrategy

        task = str(payload.get("task", "")).strip()
        agent_names: list[str] = [str(n).strip() for n in payload.get("agent_names", []) if str(n).strip()]
        strategy_name = str(payload.get("strategy", "majority_vote") or "majority_vote").strip().lower()
        strategy_map = {
            "majority_vote": ConsensusStrategy.MAJORITY_VOTE,
            "weighted_confidence": ConsensusStrategy.WEIGHTED_CONFIDENCE,
            "best_confidence": ConsensusStrategy.BEST_CONFIDENCE,
            "unanimous": ConsensusStrategy.UNANIMOUS,
            "deliberation": ConsensusStrategy.DELIBERATION,
        }
        strategy = strategy_map.get(strategy_name, ConsensusStrategy.MAJORITY_VOTE)
        if not task or not agent_names:
            return {"ok": False, "error": "task and agent_names required"}
        dry_run = self._task_mark_dry_run(payload, mode="consensus", target_agents=agent_names, extra={"strategy": strategy_name})
        if dry_run:
            return dry_run

        timeout = max(120.0, float(payload.get("timeout_seconds", 180.0)))
        if self._task_requires_approval(payload):
            return await self._task_create_pending_approval(
                payload,
                orchestration_mode="consensus",
                title=str(payload.get("title", "")).strip() or task.strip().splitlines()[0][:72] or "Consensus task",
                prompt=task,
                target_agents=agent_names,
                timeout_seconds=timeout,
                extra_metadata={"strategy": strategy_name},
            )
        task_id = ""
        started_at = time.time()
        consensus_metadata = self._build_task_metadata(
            payload,
            orchestration_mode="consensus",
            target_agents=agent_names,
            timeout_seconds=timeout,
            memory_provenance=[],
            memory_scopes=[],
        )
        consensus_metadata["strategy"] = strategy_name
        if self._task_store:
            from neuralclaw.swarm.task_store import TaskRecord

            existing_task_id = str(payload.get("__task_id", "")).strip()
            if existing_task_id:
                task_id = existing_task_id
                existing = await self._task_store.get(task_id)
                if existing:
                    consensus_metadata = {
                        **dict(existing.metadata or {}),
                        **consensus_metadata,
                    }
                await self._task_store.update(
                    task_id,
                    status="running",
                    target_agents=agent_names,
                    started_at=started_at,
                    metadata=consensus_metadata,
                )
            else:
                task_id = await self._task_store.create(
                    TaskRecord(
                        task_id="",
                        title=(str(consensus_metadata.get("brief", {}).get("title_override", "")).strip() or task.strip().splitlines()[0][:72] or "Consensus task"),
                        prompt=task,
                        status="running",
                        target_agents=agent_names,
                        started_at=started_at,
                        metadata=consensus_metadata,
                    )
                )
        try:
            result = await self._consensus.seek_consensus(
                task=task,
                strategy=strategy,
                agent_names=agent_names,
                timeout=timeout,
            )
            response = {
                "ok": True,
                "result": getattr(result, "final_response", ""),
                "confidence": getattr(result, "final_confidence", None),
                "agent_responses": [
                    {"agent": v.agent_name, "response": v.response, "confidence": v.confidence}
                    for v in getattr(result, "votes", [])
                ],
                "strategy": getattr(getattr(result, "strategy", None), "name", strategy.name).lower(),
            }
            if self._task_store and task_id:
                final_result = str(response.get("result") or "")
                teaching_artifacts = await self._capture_teaching_artifact_if_needed(
                    source_id=task_id,
                    payload=payload,
                    result_text=final_result,
                )
                consensus_metadata = {
                    **consensus_metadata,
                    "teaching_artifacts": teaching_artifacts,
                    "confidence": response.get("confidence"),
                    "confidence_contract": self._task_confidence_contract(
                        confidence=response.get("confidence"),
                        source="consensus",
                        evidence_sources=["agent_votes", "consensus_result"],
                    ),
                    "votes": response.get("agent_responses", []),
                    "artifacts": self._extract_result_artifacts(final_result),
                    "followups": self._build_task_followups(status="completed", result_text=final_result),
                    "execution_log": [
                        *(consensus_metadata.get("execution_log", [])),
                        *[
                            self._task_log_entry(
                                "vote",
                                f"{vote['agent']} confidence {vote['confidence']}",
                                agent=vote["agent"],
                                status="completed",
                            )
                            for vote in response.get("agent_responses", [])
                        ],
                        self._task_log_entry("completed", f"Consensus reached with strategy {response['strategy']}", status="completed"),
                    ],
                }
                consensus_metadata["change_receipt"] = self._task_change_receipt(
                    task_id=task_id,
                    metadata=consensus_metadata,
                    operations=["consensus_complete", str(response["strategy"])],
                )
                consensus_metadata["receipt_refs"] = [consensus_metadata["change_receipt"]["receipt_id"]]
                await self._task_store.update(
                    task_id,
                    status="completed",
                    result=final_result,
                    completed_at=time.time(),
                    duration_ms=int((time.time() - started_at) * 1000),
                    metadata=consensus_metadata,
                )
                response["task_id"] = task_id
            return response
        except Exception as e:
            if self._task_store and task_id:
                consensus_metadata = {
                    **consensus_metadata,
                    "confidence_contract": self._task_confidence_contract(
                        confidence=0.0,
                        source="consensus_error",
                        uncertainty_factors=["execution_error"],
                        evidence_sources=["consensus_runtime"],
                        escalation_recommendation="operator_review_recommended",
                        retry_rationale=str(e),
                    ),
                    "followups": self._build_task_followups(status="failed", result_text="", error_text=str(e)),
                    "execution_log": [
                        *(consensus_metadata.get("execution_log", [])),
                        self._task_log_entry("failed", str(e), status="failed"),
                    ],
                }
                consensus_metadata["change_receipt"] = self._task_change_receipt(
                    task_id=task_id,
                    metadata=consensus_metadata,
                    operations=["consensus_failed"],
                )
                consensus_metadata["receipt_refs"] = [consensus_metadata["change_receipt"]["receipt_id"]]
                await self._task_store.update(
                    task_id,
                    status="failed",
                    error=str(e),
                    completed_at=time.time(),
                    duration_ms=int((time.time() - started_at) * 1000),
                    metadata=consensus_metadata,
                )
            return {"ok": False, "error": str(e)}

    async def _dashboard_create_shared_task(self, agent_names: list[str]) -> dict:
        if not self._shared_bridge:
            return {"ok": False, "error": "Shared memory not available"}
        task = await self._shared_bridge.create_shared_task(agent_names)
        return {"ok": True, "task_id": task.task_id}

    async def _dashboard_get_shared_task(self, task_id: str) -> dict:
        if not self._shared_bridge:
            return {"ok": False, "error": "Shared memory not available"}
        task = await self._shared_bridge.get_task(task_id)
        if not task:
            return {"ok": False, "error": "Task not found"}
        memories = await self._shared_bridge.get_shared_memories(task_id)
        return {
            "ok": True,
            "task": {
                "task_id": task.task_id,
                "agents": task.agents,
                "status": task.status,
                "created_at": task.created_at,
            },
            "memories": [
                {
                    "id": m.id,
                    "from_agent": m.from_agent,
                    "content": m.content,
                    "memory_type": m.memory_type,
                    "timestamp": m.timestamp,
                }
                for m in memories
            ],
        }

    async def _dashboard_send_message(self, payload: str | dict[str, Any]) -> dict[str, Any]:
        """Send a dashboard/desktop chat message through the cognitive pipeline."""
        if isinstance(payload, str):
            data: dict[str, Any] = {"content": payload}
        elif isinstance(payload, dict):
            data = dict(payload)
        else:
            return {"ok": False, "error": "message payload must be a string or object"}

        content = str(data.get("content", "")).strip()
        documents = data.get("documents", [])
        if not isinstance(documents, list):
            documents = []
        media = data.get("media", [])
        if not isinstance(media, list):
            media = []
        if not content and not documents and not media:
            return {"ok": False, "error": "content or attachments required"}

        if documents:
            rendered_docs: list[str] = []
            for item in documents:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "Document")).strip() or "Document"
                text = str(item.get("content", "")).strip()
                if text:
                    rendered_docs.append(f"### {name}\n{text[:12000]}")
            if rendered_docs:
                content = (
                    f"{content}\n\n## Attached Documents\n"
                    + "\n\n".join(rendered_docs)
                ).strip()

        metadata = {
            "platform": "web",
            "source": "dashboard",
            "is_private": True,
            "is_shared": False,
        }
        if data.get("session_id"):
            metadata["session_id"] = str(data["session_id"])
        if data.get("teaching_mode") is not None:
            metadata["teaching_mode"] = bool(data.get("teaching_mode"))
        metadata["autonomy_mode"] = self._default_autonomy_mode(str(data.get("autonomy_mode", "") or ""))
        if data.get("project_context_id"):
            metadata["project_context_id"] = str(data.get("project_context_id"))
        if isinstance(data.get("channel_style_profile"), dict):
            metadata["channel_style_profile"] = data.get("channel_style_profile")

        target_agent = str(data.get("target_agent", "") or "").strip()
        if target_agent:
            return await self._dashboard_chat_with_agent(
                agent_name=target_agent,
                content=content,
                media=media,
                metadata=metadata,
            )

        provider_name = str(data.get("provider", "") or "").strip().lower()
        requested_model = str(data.get("model", "") or "").strip()
        base_url = str(data.get("base_url", "") or "").strip()

        response = await self._process_dashboard_message_with_override(
            content=content,
            media=media,
            metadata=metadata,
            provider_name=provider_name,
            model_name=requested_model,
            base_url=base_url,
        )
        response_text = response["response"] if isinstance(response, dict) else response
        memory_provenance = response.get("memory_provenance", []) if isinstance(response, dict) else []
        memory_scopes = response.get("memory_scopes", []) if isinstance(response, dict) else []
        teaching_artifacts = await self._capture_teaching_artifact_if_needed(
            source_id=str(data.get("session_id", "") or f"chat-{int(time.time())}"),
            metadata=metadata,
            result_text=response_text,
        )
        return {
            "ok": True,
            "response": response_text,
            "model": response.get("effective_model") if isinstance(response, dict) else (requested_model or None),
            "requested_model": requested_model or None,
            "effective_model": response.get("effective_model") if isinstance(response, dict) else (requested_model or None),
            "fallback_reason": response.get("fallback_reason") if isinstance(response, dict) else None,
            "memory_provenance": memory_provenance,
            "memory_scopes": memory_scopes,
            "confidence_contract": response.get("confidence_contract", {}) if isinstance(response, dict) else {},
            "teaching_artifacts": teaching_artifacts,
        }

    async def _dashboard_clear_memory(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Clear selected memory stores and return deleted counts."""
        requested = payload or {}
        stores = {
            str(store).strip().lower()
            for store in (requested.get("stores") or ["episodic", "semantic", "procedural", "vector", "identity"])
            if str(store).strip()
        }
        clear_history = bool(requested.get("clear_history", True))

        episodic_deleted = await self._episodic.clear() if self._episodic and "episodic" in stores else 0
        semantic_deleted = await self._semantic.clear() if self._semantic and "semantic" in stores else 0
        procedural_deleted = await self._procedural.clear() if self._procedural and "procedural" in stores else 0
        vector_deleted = await self._vector_memory.clear() if self._vector_memory and "vector" in stores else 0
        identity_deleted = await self._identity.clear() if self._identity and "identity" in stores else 0
        if clear_history:
            self._history.clear()
        return {
            "episodic_deleted": episodic_deleted,
            "semantic_deleted": semantic_deleted,
            "procedural_deleted": procedural_deleted,
            "vector_deleted": vector_deleted,
            "identity_deleted": identity_deleted,
            "history_cleared": clear_history,
        }

    async def _dashboard_list_memory_items(self, store: str, query: str, limit: int) -> dict[str, Any]:
        """List normalized memory items for desktop inspection."""
        store_key = (store or "episodic").strip().lower()
        safe_limit = max(1, min(int(limit or 50), 200))
        query = (query or "").strip()

        if store_key == "all":
            per_store_limit = max(5, safe_limit // 5)
            collected: list[dict[str, Any]] = []
            for name in ("episodic", "semantic", "procedural", "vector", "identity"):
                result = await self._dashboard_list_memory_items(name, query, per_store_limit)
                collected.extend(result.get("items", []))
            collected.sort(
                key=lambda item: item.get("updated_at") or item.get("timestamp") or 0,
                reverse=True,
            )
            return {"items": collected[:safe_limit], "store": "all"}

        if store_key == "episodic":
            items: list[dict[str, Any]] = []
            if self._episodic:
                episodes = await (self._episodic.search(query, limit=safe_limit) if query else self._episodic.get_recent(limit=safe_limit))
                if query:
                    items = [
                        {
                            "id": result.episode.id,
                            "store": "episodic",
                            "title": result.episode.author or result.episode.source or "Episode",
                            "preview": result.episode.content[:240],
                            "content": result.episode.content,
                            "timestamp": result.episode.timestamp,
                            "updated_at": result.episode.last_accessed or result.episode.timestamp,
                            "pinned": result.episode.importance >= 0.95,
                            "score": result.relevance,
                            "can_edit": True,
                            "can_pin": True,
                            "can_delete": True,
                            "metadata": {
                                "source": result.episode.source,
                                "author": result.episode.author,
                                "importance": result.episode.importance,
                                "emotional_valence": result.episode.emotional_valence,
                                "tags": result.episode.tags,
                                "access_count": result.episode.access_count,
                            },
                        }
                        for result in episodes
                    ]
                else:
                    items = [
                        {
                            "id": episode.id,
                            "store": "episodic",
                            "title": episode.author or episode.source or "Episode",
                            "preview": episode.content[:240],
                            "content": episode.content,
                            "timestamp": episode.timestamp,
                            "updated_at": episode.last_accessed or episode.timestamp,
                            "pinned": episode.importance >= 0.95,
                            "score": None,
                            "can_edit": True,
                            "can_pin": True,
                            "can_delete": True,
                            "metadata": {
                                "source": episode.source,
                                "author": episode.author,
                                "importance": episode.importance,
                                "emotional_valence": episode.emotional_valence,
                                "tags": episode.tags,
                                "access_count": episode.access_count,
                            },
                        }
                        for episode in episodes
                    ]
            return {"items": [self._enrich_memory_item_metadata(item) for item in items], "store": "episodic"}

        if store_key == "semantic":
            items = []
            if self._semantic:
                for entity in await self._semantic.list_entities(query=query, limit=safe_limit):
                    items.append(
                        {
                            "id": entity.id,
                            "store": "semantic",
                            "title": entity.name,
                            "preview": json.dumps(entity.attributes, ensure_ascii=False)[:240] or entity.entity_type,
                            "content": json.dumps(entity.attributes, ensure_ascii=False, indent=2),
                            "timestamp": entity.created_at,
                            "updated_at": entity.updated_at,
                            "pinned": bool(entity.attributes.get("pinned")),
                            "score": None,
                            "can_edit": True,
                            "can_pin": True,
                            "can_delete": True,
                            "metadata": {
                                "entity_type": entity.entity_type,
                                "attributes": entity.attributes,
                                "namespace": getattr(self._semantic, "_namespace", "global"),
                            },
                        }
                    )
            return {"items": [self._enrich_memory_item_metadata(item) for item in items], "store": "semantic"}

        if store_key == "procedural":
            items = []
            if self._procedural:
                procedures = await self._procedural.get_all(limit=safe_limit * 2)
                if query:
                    query_lower = query.lower()
                    procedures = [
                        proc for proc in procedures
                        if query_lower in proc.name.lower() or query_lower in proc.description.lower()
                    ]
                for procedure in procedures[:safe_limit]:
                    items.append(
                        {
                            "id": procedure.id,
                            "store": "procedural",
                            "title": procedure.name,
                            "preview": procedure.description[:240],
                            "content": "\n".join(
                                f"{index + 1}. {step.action}: {step.description}"
                                for index, step in enumerate(procedure.steps)
                            ),
                            "timestamp": procedure.created_at,
                            "updated_at": procedure.last_used or procedure.created_at,
                            "pinned": False,
                            "score": procedure.success_rate,
                            "can_edit": True,
                            "can_pin": False,
                            "can_delete": True,
                            "metadata": {
                                "trigger_patterns": procedure.trigger_patterns,
                                "success_rate": procedure.success_rate,
                                "success_count": procedure.success_count,
                                "failure_count": procedure.failure_count,
                                "namespace": getattr(self._procedural, "_namespace", "global"),
                                "steps": [
                                    {
                                        "action": step.action,
                                        "description": step.description,
                                        "parameters": step.parameters,
                                        "expected_output": step.expected_output,
                                    }
                                    for step in procedure.steps
                                ],
                            },
                        }
                    )
            return {"items": [self._enrich_memory_item_metadata(item) for item in items], "store": "procedural"}

        if store_key == "vector":
            items = []
            if self._vector_memory:
                for entry in await self._vector_memory.list_entries(query=query, limit=safe_limit):
                    items.append(
                        {
                            "id": entry.id,
                            "store": "vector",
                            "title": entry.ref_id,
                            "preview": entry.content_preview[:240],
                            "content": entry.content_preview,
                            "timestamp": entry.created_at,
                            "updated_at": entry.created_at,
                            "pinned": False,
                            "score": None,
                            "can_edit": False,
                            "can_pin": False,
                            "can_delete": True,
                            "metadata": {
                                "ref_id": entry.ref_id,
                                "source": entry.source,
                            },
                        }
                    )
            return {"items": [self._enrich_memory_item_metadata(item) for item in items], "store": "vector"}

        if store_key == "identity":
            items = []
            if self._identity:
                for model in await self._identity.list_models(query=query, limit=safe_limit):
                    items.append(
                        {
                            "id": model.user_id,
                            "store": "identity",
                            "title": model.display_name,
                            "preview": model.notes[:240] or ", ".join(model.active_projects[:3]) or ", ".join(model.expertise_domains[:3]),
                            "content": model.notes or "",
                            "timestamp": model.first_seen,
                            "updated_at": model.last_seen,
                            "pinned": False,
                            "score": None,
                            "can_edit": True,
                            "can_pin": False,
                            "can_delete": True,
                            "metadata": {
                                "user_id": model.user_id,
                                "platform_aliases": model.platform_aliases,
                                "communication_style": model.communication_style,
                                "active_projects": model.active_projects,
                                "expertise_domains": model.expertise_domains,
                                "language": model.language,
                                "timezone": model.timezone,
                                "preferences": model.preferences,
                                "session_count": model.session_count,
                                "message_count": model.message_count,
                            },
                        }
                    )
            return {"items": [self._enrich_memory_item_metadata(item) for item in items], "store": "identity"}

        return {"items": [], "store": store_key}

    async def _dashboard_update_memory_item(self, store: str, item_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a memory item by store."""
        store_key = (store or "").strip().lower()
        if store_key == "episodic" and self._episodic:
            item = await self._episodic.update_episode(
                item_id,
                content=str(updates.get("content", "")).strip() or None,
                importance=float(updates["importance"]) if updates.get("importance") is not None else None,
                tags=[str(tag) for tag in updates.get("tags", [])] if isinstance(updates.get("tags"), list) else None,
            )
            return {"ok": item is not None, "item_id": item_id, "store": store_key, "error": None if item else "Episode not found"}
        if store_key == "semantic" and self._semantic:
            attrs = updates.get("attributes")
            item = await self._semantic.update_entity(
                item_id,
                name=str(updates.get("name", "")).strip() or None,
                entity_type=str(updates.get("entity_type", "")).strip() or None,
                attributes=attrs if isinstance(attrs, dict) else None,
            )
            return {"ok": item is not None, "item_id": item_id, "store": store_key, "error": None if item else "Entity not found"}
        if store_key == "procedural" and self._procedural:
            patterns = updates.get("trigger_patterns")
            item = await self._procedural.update_procedure(
                item_id,
                name=str(updates.get("name", "")).strip() or None,
                description=str(updates.get("description", "")) if "description" in updates else None,
                trigger_patterns=[str(pattern) for pattern in patterns] if isinstance(patterns, list) else None,
            )
            return {"ok": item is not None, "item_id": item_id, "store": store_key, "error": None if item else "Procedure not found"}
        if store_key == "identity" and self._identity:
            await self._identity.update(
                item_id,
                {
                    key: value
                    for key, value in updates.items()
                    if key in {"display_name", "notes", "timezone", "language", "preferences", "communication_style", "active_projects", "expertise_domains"}
                },
            )
            return {"ok": True, "item_id": item_id, "store": store_key}
        return {"ok": False, "error": f"Unsupported memory store '{store_key}'"}

    async def _dashboard_delete_memory_item(self, store: str, item_id: str) -> dict[str, Any]:
        """Delete a memory item by store."""
        store_key = (store or "").strip().lower()
        if store_key == "episodic" and self._episodic:
            await self._episodic.delete_episode(item_id)
            return {"ok": True, "item_id": item_id, "store": store_key}
        if store_key == "semantic" and self._semantic:
            await self._semantic.delete_entity(item_id)
            return {"ok": True, "item_id": item_id, "store": store_key}
        if store_key == "procedural" and self._procedural:
            await self._procedural.delete(item_id)
            return {"ok": True, "item_id": item_id, "store": store_key}
        if store_key == "vector" and self._vector_memory:
            await self._vector_memory.delete(item_id)
            return {"ok": True, "item_id": item_id, "store": store_key}
        if store_key == "identity" and self._identity:
            ok = await self._identity.delete_user(item_id)
            return {"ok": ok, "item_id": item_id, "store": store_key}
        return {"ok": False, "error": f"Unsupported memory store '{store_key}'"}

    async def _dashboard_pin_memory_item(self, store: str, item_id: str) -> dict[str, Any]:
        """Pin a memory item where supported."""
        store_key = (store or "").strip().lower()
        if store_key == "episodic" and self._episodic:
            item = await self._episodic.pin_episode(item_id)
            return {"ok": item is not None, "item_id": item_id, "store": store_key, "error": None if item else "Episode not found"}
        if store_key == "semantic" and self._semantic:
            item = await self._semantic.pin_entity(item_id)
            return {"ok": item is not None, "item_id": item_id, "store": store_key, "error": None if item else "Entity not found"}
        return {"ok": False, "error": f"Pin is not supported for '{store_key}'"}

    async def _dashboard_export_memory(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        requested = payload or {}
        stores = {
            str(store).strip().lower()
            for store in (requested.get("stores") or ["episodic", "semantic", "procedural", "vector", "identity"])
            if str(store).strip()
        }
        backup: dict[str, Any] = {
            "version": 1,
            "exported_at": time.time(),
            "retention_days": self._get_memory_retention_windows(),
            "stores": {},
        }

        if self._episodic and "episodic" in stores:
            backup["stores"]["episodic"] = [
                {
                    "id": episode.id,
                    "timestamp": episode.timestamp,
                    "source": episode.source,
                    "author": episode.author,
                    "content": episode.content,
                    "importance": episode.importance,
                    "emotional_valence": episode.emotional_valence,
                    "tags": episode.tags,
                }
                for episode in await self._episodic.get_recent(limit=10_000)
            ]
        if self._semantic and "semantic" in stores:
            backup["stores"]["semantic"] = [
                {
                    "id": entity.id,
                    "name": entity.name,
                    "entity_type": entity.entity_type,
                    "attributes": entity.attributes,
                    "created_at": entity.created_at,
                    "updated_at": entity.updated_at,
                }
                for entity in await self._semantic.list_entities(limit=10_000)
            ]
        if self._procedural and "procedural" in stores:
            backup["stores"]["procedural"] = [
                {
                    "id": procedure.id,
                    "name": procedure.name,
                    "description": procedure.description,
                    "trigger_patterns": procedure.trigger_patterns,
                    "steps": [
                        {
                            "action": step.action,
                            "description": step.description,
                            "parameters": step.parameters,
                            "expected_output": step.expected_output,
                        }
                        for step in procedure.steps
                    ],
                    "success_count": procedure.success_count,
                    "failure_count": procedure.failure_count,
                    "last_used": procedure.last_used,
                    "created_at": procedure.created_at,
                }
                for procedure in await self._procedural.get_all(limit=10_000)
            ]
        if self._vector_memory and "vector" in stores:
            backup["stores"]["vector"] = [
                {
                    "id": entry.id,
                    "source": entry.source,
                    "ref_id": entry.ref_id,
                    "content_preview": entry.content_preview,
                    "created_at": entry.created_at,
                }
                for entry in await self._vector_memory.list_entries(limit=10_000)
            ]
        if self._identity and "identity" in stores:
            backup["stores"]["identity"] = [
                {
                    "user_id": model.user_id,
                    "display_name": model.display_name,
                    "platform_aliases": model.platform_aliases,
                    "communication_style": model.communication_style,
                    "active_projects": model.active_projects,
                    "expertise_domains": model.expertise_domains,
                    "language": model.language,
                    "timezone": model.timezone,
                    "preferences": model.preferences,
                    "last_seen": model.last_seen,
                    "first_seen": model.first_seen,
                    "session_count": model.session_count,
                    "message_count": model.message_count,
                    "notes": model.notes,
                }
                for model in await self._identity.list_models(limit=10_000)
            ]

        serialized = json.dumps(backup, ensure_ascii=False).encode("utf-8")
        passphrase = str(requested.get("passphrase", "") or "")
        if passphrase:
            return {"ok": True, **self._encrypt_backup_blob(serialized, passphrase)}
        return {
            "ok": True,
            "encrypted": False,
            "payload": base64.b64encode(serialized).decode("utf-8"),
        }

    async def _dashboard_import_memory(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = payload or {}
        raw_payload = str(data.get("payload", "") or "").strip()
        if not raw_payload:
            return {"ok": False, "error": "payload required"}
        try:
            if data.get("encrypted"):
                decoded = self._decrypt_backup_blob(
                    raw_payload,
                    str(data.get("salt", "") or ""),
                    str(data.get("digest", "") or ""),
                    str(data.get("passphrase", "") or ""),
                )
            else:
                decoded = base64.b64decode(raw_payload.encode("utf-8"))
            backup = json.loads(decoded.decode("utf-8"))
        except Exception as exc:
            return {"ok": False, "error": f"Failed to decode backup: {exc}"}

        imported = {"episodic": 0, "semantic": 0, "procedural": 0, "vector": 0, "identity": 0}
        stores = backup.get("stores") or {}
        try:
            if self._episodic:
                for item in stores.get("episodic", []):
                    await self._episodic.store(
                        content=str(item.get("content", "") or ""),
                        source=str(item.get("source", "conversation") or "conversation"),
                        author=str(item.get("author", "user") or "user"),
                        importance=float(item.get("importance", 0.5) or 0.5),
                        emotional_valence=float(item.get("emotional_valence", 0.0) or 0.0),
                        tags=[str(tag) for tag in item.get("tags", []) if str(tag).strip()],
                    )
                    imported["episodic"] += 1
            if self._semantic:
                for item in stores.get("semantic", []):
                    await self._semantic.upsert_entity(
                        name=str(item.get("name", "") or "Entity"),
                        entity_type=str(item.get("entity_type", "unknown") or "unknown"),
                        attributes=dict(item.get("attributes") or {}),
                    )
                    imported["semantic"] += 1
            if self._procedural:
                from neuralclaw.cortex.memory.procedural import ProcedureStep
                for item in stores.get("procedural", []):
                    await self._procedural.store_procedure(
                        name=str(item.get("name", "") or "Procedure"),
                        description=str(item.get("description", "") or ""),
                        trigger_patterns=[str(pattern) for pattern in item.get("trigger_patterns", []) if str(pattern).strip()],
                        steps=[
                            ProcedureStep(
                                action=str(step.get("action", "") or ""),
                                description=str(step.get("description", "") or ""),
                                parameters=dict(step.get("parameters") or {}),
                                expected_output=str(step.get("expected_output", "") or ""),
                            )
                            for step in item.get("steps", [])
                        ],
                    )
                    imported["procedural"] += 1
            if self._vector_memory:
                for item in stores.get("vector", []):
                    preview = str(item.get("content_preview", "") or "").strip()
                    ref_id = str(item.get("ref_id", "") or "").strip()
                    if not preview or not ref_id:
                        continue
                    await self._vector_memory.embed_and_store(
                        preview,
                        ref_id,
                        str(item.get("source", "episodic") or "episodic"),
                    )
                    imported["vector"] += 1
            if self._identity:
                for item in stores.get("identity", []):
                    user_id = str(item.get("user_id", "") or "").strip()
                    if not user_id:
                        continue
                    existing = await self._identity.get(user_id)
                    if not existing:
                        platform_aliases = dict(item.get("platform_aliases") or {})
                        platform = next(iter(platform_aliases.keys()), "import")
                        platform_user_id = str(platform_aliases.get(platform) or user_id)
                        await self._identity.get_or_create(
                            platform=platform,
                            platform_user_id=platform_user_id,
                            display_name=str(item.get("display_name", user_id) or user_id),
                        )
                    await self._identity.update(
                        user_id,
                        {
                            "display_name": str(item.get("display_name", "") or ""),
                            "platform_aliases": dict(item.get("platform_aliases") or {}),
                            "communication_style": dict(item.get("communication_style") or {}),
                            "active_projects": list(item.get("active_projects") or []),
                            "expertise_domains": list(item.get("expertise_domains") or []),
                            "language": str(item.get("language", "en") or "en"),
                            "timezone": str(item.get("timezone", "") or ""),
                            "preferences": dict(item.get("preferences") or {}),
                            "last_seen": float(item.get("last_seen", 0.0) or 0.0),
                            "first_seen": float(item.get("first_seen", 0.0) or 0.0),
                            "session_count": int(item.get("session_count", 0) or 0),
                            "message_count": int(item.get("message_count", 0) or 0),
                            "notes": str(item.get("notes", "") or ""),
                        },
                    )
                    imported["identity"] += 1
        except Exception as exc:
            return {"ok": False, "error": f"Failed to import backup: {exc}"}

        return {"ok": True, "imported": imported}

    async def _dashboard_run_memory_retention(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        deleted = await self._apply_memory_retention_if_due(force=True)
        return {"ok": True, "deleted": deleted, "retention_days": self._get_memory_retention_windows()}

    def _dashboard_get_features(self) -> dict[str, Any]:
        """Return feature toggle states with live-effect metadata."""
        feat = self._config.features
        labels = {
            "reflective_reasoning": "Reflective Reasoning",
            "swarm": "Swarm Agents",
            "evolution": "Evolution Cortex",
            "vector_memory": "Vector Memory",
            "identity": "Identity Memory",
            "procedural_memory": "Procedural Memory",
            "semantic_memory": "Semantic Memory",
            "voice": "Voice Assistant",
            "browser": "Browser Automation",
            "desktop": "Desktop Control",
            "vision": "Vision",
            "structured_output": "Structured Output",
            "streaming_responses": "Streaming Responses",
            "traceline": "Trace Logging",
            "dashboard": "Dashboard Server",
            "a2a_federation": "A2A Federation",
            "database_bi": "Database BI",
            "clipboard_intel": "Clipboard Intelligence",
            "kpi_monitor": "KPI Monitor",
            "scheduler": "Scheduler",
            "context_aware": "Context Awareness",
            "digest": "Digest Summaries",
            "offline_fallback": "Offline Fallback",
            "skill_forge": "Skill Forge",
            "rag": "Knowledge Base",
            "workflow_engine": "Workflow Engine",
            "mcp_server": "MCP Server",
        }
        live_features = {"reflective_reasoning"}
        feature_payload: dict[str, Any] = {}
        for key, value in vars(feat).items():
            if isinstance(value, bool):
                feature_payload[key] = {
                    "value": value,
                    "live": key in live_features,
                    "label": labels.get(key, key.replace("_", " ").title()),
                }
        return feature_payload

    async def _dashboard_set_feature(self, feature: str, value: bool) -> dict[str, Any]:
        """Persist a feature toggle and report whether a restart is required."""
        feat = self._config.features
        if not hasattr(feat, feature):
            return {"ok": False, "error": f"Unknown feature '{feature}'"}

        update_config(
            {"features": {feature: value}},
            Path(self._config_path) if self._config_path else None,
        )
        reloaded = load_config(Path(self._config_path) if self._config_path else None)
        self._refresh_runtime_config(reloaded)
        return {
            "ok": True,
            "restart_required": feature != "reflective_reasoning",
        }

    def _candidate_local_base_urls(self, base_url: str = "") -> list[str]:
        requested_base_url = str(base_url or "").strip()
        configured_candidates = [
            str(self._get_provider_config("local").base_url or "").strip(),
            str(getattr(self._config.model_roles, "base_url", "") or "").strip(),
        ]
        if self._config.primary_provider and self._config.primary_provider.name in {"local", "meta"}:
            configured_candidates.append(str(self._config.primary_provider.base_url or "").strip())

        default_local_candidates = {
            "",
            "http://localhost:11434",
            "http://localhost:11434/v1",
            "http://127.0.0.1:11434",
            "http://127.0.0.1:11434/v1",
        }
        if requested_base_url and requested_base_url not in default_local_candidates:
            candidates = [requested_base_url, *configured_candidates]
        else:
            candidates = [*configured_candidates, requested_base_url]
        candidates.append("http://localhost:11434/v1")

        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            ordered.append(candidate)
            seen.add(candidate)
        return ordered

    async def _discover_local_models(self, base_url: str = "") -> tuple[list[str], str]:
        # Remote Ollama endpoints (Tailscale, LAN, etc.) regularly take more
        # than 5 seconds to answer /api/tags when they're busy loading a
        # multi-GB model. Use a more forgiving budget so we don't silently
        # fall back to localhost.
        timeout = aiohttp.ClientTimeout(total=15)
        last_error: Exception | None = None

        requested = str(base_url or "").strip()
        explicit_remote = bool(requested) and not self._is_localhost_url(requested)
        if explicit_remote:
            # User explicitly named an endpoint — trust it and only probe
            # that one. Falling back to localhost when a remote URL was
            # given silently misroutes the chat.
            candidates = [requested]
        else:
            candidates = self._candidate_local_base_urls(base_url)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for raw_base in candidates:
                base = raw_base[:-3] if raw_base.endswith("/v1") else raw_base
                try:
                    async with session.get(f"{base}/api/tags") as response:
                        response.raise_for_status()
                        payload = await response.json()
                except Exception as exc:
                    last_error = exc
                    continue

                models = payload.get("models", []) if isinstance(payload, dict) else []
                names = [
                    str(model.get("name", "")).strip()
                    for model in models
                    if isinstance(model, dict) and str(model.get("name", "")).strip()
                ]
                return sorted(set(names)), raw_base

        if explicit_remote:
            detail = f": {last_error}" if last_error else ""
            raise ProviderError(
                f"Local model endpoint '{requested}' is not reachable{detail}. "
                "Check the URL, that Ollama is running on that host, and that the "
                "port is exposed (e.g. OLLAMA_HOST=0.0.0.0:11434)."
            )

        if last_error:
            self._logger.debug("Local model discovery failed for all configured endpoints: %s", last_error)
        fallback = candidates[0] if candidates else "http://localhost:11434/v1"
        return [], fallback

    @staticmethod
    def _is_localhost_url(url: str) -> bool:
        lowered = (url or "").lower()
        return any(host in lowered for host in ("localhost", "127.0.0.1", "0.0.0.0"))

    @staticmethod
    def _is_embedding_model_name(model_name: str) -> bool:
        lowered = str(model_name or "").strip().lower()
        if not lowered:
            return False
        return any(token in lowered for token in ("embed", "embedding", "nomic"))

    def _ensure_local_chat_model(self, model_name: str, *, context: str = "chat") -> None:
        if not self._is_embedding_model_name(model_name):
            return
        raise ValueError(
            f"Local model '{model_name}' cannot be used for {context}. "
            "It appears to be an embedding-only model. Use it under the embedding model setting instead."
        )

    def _configured_local_role_models(self) -> list[tuple[str, str]]:
        configured = [
            ("primary", str(getattr(self._config.model_roles, "primary", "") or "").strip()),
            ("fast", str(getattr(self._config.model_roles, "fast", "") or "").strip()),
            ("micro", str(getattr(self._config.model_roles, "micro", "") or "").strip()),
            ("embed", str(getattr(self._config.model_roles, "embed", "") or "").strip()),
            ("default", str(self._get_provider_config("local").model or "").strip()),
        ]
        seen: set[str] = set()
        ordered: list[tuple[str, str]] = []
        for label, model in configured:
            if not model or model in seen:
                continue
            ordered.append((label, model))
            seen.add(model)
        return ordered

    async def _get_local_model_registry(self, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if (
            not force
            and self._local_model_registry_cache.get("models")
            and (now - self._local_model_registry_at) < 10
        ):
            return self._local_model_registry_cache

        available, resolved_base_url = await self._discover_local_models("")
        available_set = set(available)
        configured = self._configured_local_role_models()
        badges = [
            {
                "label": label,
                "model": model,
                "available": model in available_set,
                "status": "available" if model in available_set else "missing",
            }
            for label, model in configured
        ]
        payload = {
            "models": available,
            "resolved_base_url": resolved_base_url,
            "available_count": len(available),
            "last_seen": now if available else None,
            "badges": badges,
            "fallback_chain": [model for label, model in configured if label in {"primary", "fast", "micro"}],
        }
        self._local_model_registry_cache = payload
        self._local_model_registry_at = now
        return payload

    @staticmethod
    def _extract_model_size(model_name: str) -> float | None:
        match = re.search(r":([0-9]+(?:\.[0-9]+)?)b$", model_name.strip().lower())
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _resolve_local_model_alias(self, model: str, available: list[str]) -> str | None:
        requested = model.strip()
        if not requested:
            return None
        if requested in available:
            return requested

        available_map = {candidate.lower(): candidate for candidate in available}
        if requested.lower() in available_map:
            return available_map[requested.lower()]

        family = requested.split(":", 1)[0].strip().lower()
        family_matches = [
            candidate
            for candidate in available
            if candidate.split(":", 1)[0].strip().lower() == family
        ]
        if not family_matches:
            return None
        if len(family_matches) == 1:
            return family_matches[0]

        requested_size = self._extract_model_size(requested)
        if requested_size is not None:
            scored = []
            for candidate in family_matches:
                candidate_size = self._extract_model_size(candidate)
                if candidate_size is None:
                    continue
                scored.append((abs(candidate_size - requested_size), -candidate_size, candidate))
            if scored:
                scored.sort()
                return scored[0][2]

        family_matches.sort(key=lambda candidate: self._extract_model_size(candidate) or 0.0, reverse=True)
        return family_matches[0]

    async def _resolve_local_model_with_fallback(
        self,
        model: str,
        base_url: str,
    ) -> tuple[str, str, str | None]:
        available, resolved_base_url = await self._discover_local_models(base_url)
        if not available:
            return model, resolved_base_url, None

        requested = model.strip() or str(self._get_provider_config("local").model or "").strip()
        candidates = [requested]
        candidates.extend(
            role_model
            for role_label, role_model in self._configured_local_role_models()
            if role_label in {"primary", "fast", "micro"} and role_model != requested
        )

        for candidate in candidates:
            resolved = self._resolve_local_model_alias(candidate, available)
            if resolved:
                if requested and resolved != requested:
                    return resolved, resolved_base_url, f"Requested model '{requested}' unavailable. Fell back to '{resolved}'."
                return resolved, resolved_base_url, None

        preview = ", ".join(available[:8])
        suffix = "..." if len(available) > 8 else ""
        raise ValueError(
            f"Local model '{requested or model}' not found at {resolved_base_url}. Available models: {preview}{suffix}"
        )

    async def _validate_local_model(
        self,
        model: str,
        base_url: str,
        *,
        allow_embedding: bool = False,
        context: str = "chat",
    ) -> tuple[str, str]:
        resolved, resolved_base_url, fallback_reason = await self._resolve_local_model_with_fallback(model, base_url)
        if not allow_embedding:
            self._ensure_local_chat_model(resolved, context=context)
        if fallback_reason:
            self._logger.warning("%s", fallback_reason)
        elif resolved != model:
            self._logger.info("Resolved local model alias '%s' -> '%s'", model, resolved)
        return resolved, resolved_base_url

    async def _process_dashboard_message_with_override(
        self,
        *,
        content: str,
        media: list[dict[str, Any]] | None,
        metadata: dict[str, Any],
        provider_name: str = "",
        model_name: str = "",
        base_url: str = "",
    ) -> str | dict[str, Any]:
        if not provider_name:
            return await self.process_message(
                content=content,
                author_id="dashboard",
                author_name="Dashboard",
                channel_id="dashboard",
                channel_type_name="CLI",
                media=media,
                message_metadata=metadata,
                include_details=True,
            )

        temp_provider, resolved_model, resolved_base_url, fallback_reason = await self._build_dashboard_override_provider(
            provider_name=provider_name,
            model_name=model_name,
            base_url=base_url,
        )
        if not temp_provider:
            raise ProviderError(f"Unable to create provider override for '{provider_name}'")

        original_provider = self._provider
        original_vision = self._vision
        original_role_router = getattr(self._deliberate, "_role_router", None)
        original_classifier_router = getattr(self._classifier, "_role_router", None)
        self._provider = temp_provider
        self._deliberate.set_provider(temp_provider)
        # Per-message provider override must also bypass the role router,
        # otherwise DeliberateReasoner._complete() short-circuits to the
        # role router's pinned LocalProviders (wrong base_url and model)
        # and the temp provider is silently ignored.
        self._deliberate.set_role_router(None)
        if hasattr(self._classifier, "set_role_router"):
            self._classifier.set_role_router(None)
        if self._config.features.vision:
            self._vision = VisionPerception(temp_provider, self._bus)
        try:
            response = await self.process_message(
                content=content,
                author_id="dashboard",
                author_name="Dashboard",
                channel_id="dashboard",
                channel_type_name="CLI",
                media=media,
                message_metadata=metadata,
                include_details=True,
            )
            if isinstance(response, dict):
                response.setdefault("effective_model", resolved_model)
                response.setdefault("fallback_reason", fallback_reason)
                if resolved_base_url:
                    response.setdefault("base_url", resolved_base_url)
            return response
        finally:
            self._provider = original_provider
            if original_provider:
                self._deliberate.set_provider(original_provider)
            self._deliberate.set_role_router(original_role_router)
            if hasattr(self._classifier, "set_role_router"):
                self._classifier.set_role_router(original_classifier_router)
            self._vision = original_vision

    async def _dashboard_list_kb_documents(self) -> list[dict[str, Any]]:
        if not self._knowledge_base:
            return []
        docs = await self._knowledge_base.list_documents()
        return [
            {
                "id": doc.id,
                "filename": doc.filename,
                "source": doc.source,
                "doc_type": doc.doc_type,
                "ingested_at": doc.ingested_at,
                "chunk_count": doc.chunk_count,
                "metadata": doc.metadata,
            }
            for doc in docs
        ]

    async def _dashboard_ingest_kb_document(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self._knowledge_base:
            return {"ok": False, "error": "Knowledge base not available"}
        file_path = str(data.get("file_path", "") or "").strip()
        if not file_path:
            return {"ok": False, "error": "file_path required"}
        result = await self._knowledge_base.ingest(file_path=file_path, source="desktop_upload")
        if result.get("error"):
            return {"ok": False, "error": result["error"]}
        return {"ok": True, **result}

    async def _auto_index_knowledge_base(self) -> None:
        if not self._knowledge_base or not self._config.features.rag or not self._config.rag.enabled:
            return

        roots = [str(path).strip() for path in (self._config.rag.auto_index_paths or []) if str(path).strip()]
        if not roots:
            return

        await asyncio.sleep(2)
        try:
            existing_by_path: dict[str, list[Any]] = {}
            for doc in await self._knowledge_base.list_documents():
                doc_path = str((doc.metadata or {}).get("path") or "").strip()
                if doc_path:
                    existing_by_path.setdefault(doc_path, []).append(doc)

            indexed = 0
            skipped = 0
            replaced = 0
            failed = 0

            for file_path in self._iter_auto_index_files(roots):
                stat = file_path.stat()
                doc_key = str(file_path)
                existing_docs = existing_by_path.get(doc_key, [])
                latest = existing_docs[0] if existing_docs else None
                latest_meta = getattr(latest, "metadata", {}) or {}
                if latest and int(latest_meta.get("size_bytes", -1)) == stat.st_size and int(latest_meta.get("mtime_ns", -1)) == stat.st_mtime_ns:
                    skipped += 1
                    continue

                for stale_doc in existing_docs:
                    await self._knowledge_base.delete_document(stale_doc.id)
                    replaced += 1

                result = await self._knowledge_base.ingest(str(file_path), source="auto_index")
                if result.get("error"):
                    failed += 1
                    self._logger.debug("KB auto-index skipped %s: %s", file_path, result["error"])
                    continue

                indexed += 1

            self._logger.info(
                "KB auto-index finished: indexed=%s replaced=%s skipped=%s failed=%s",
                indexed,
                replaced,
                skipped,
                failed,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.warning("KB auto-index failed: %s", exc)

    def _iter_auto_index_files(self, roots: list[str]):
        allowed_exts = {
            ".c", ".cc", ".cpp", ".css", ".go", ".h", ".hpp", ".html", ".htm",
            ".java", ".js", ".json", ".jsx", ".md", ".markdown", ".mjs", ".pdf",
            ".py", ".rb", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".txt",
            ".yaml", ".yml",
        }
        skip_dirs = {
            ".git", ".hg", ".idea", ".next", ".venv", "__pycache__", "build",
            "coverage", "dist", "node_modules", "target", "venv",
        }

        for raw_root in roots:
            root = Path(raw_root).expanduser()
            if not root.exists() or not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if any(part in skip_dirs for part in path.parts):
                    continue
                if path.suffix.lower() not in allowed_exts:
                    continue
                yield path

    async def _dashboard_ingest_kb_text(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self._knowledge_base:
            return {"ok": False, "error": "Knowledge base not available"}

        title = str(data.get("title", "") or "").strip()
        source = str(data.get("source", "") or "").strip()
        mime_type = str(data.get("mime_type", "") or "").strip().lower()
        text = str(data.get("text", "") or "").strip()

        if not text and mime_type.startswith("image/"):
            image_value = str(data.get("content", "") or "").strip()
            if image_value.startswith("data:") and "," in image_value:
                image_value = image_value.split(",", 1)[1]
            if not image_value:
                return {"ok": False, "error": "image content required"}
            if not self._vision:
                return {"ok": False, "error": "Vision is not enabled for image ingestion"}
            ocr = (await self._vision.extract_text(image_value)).strip()
            desc = (await self._vision.describe(image_value, context="Knowledge base ingestion")).strip()
            text = "\n\n".join(
                part for part in (
                    f"Image OCR\n{ocr}" if ocr else "",
                    f"Image Description\n{desc}" if desc else "",
                ) if part
            ).strip()

        if not text:
            return {"ok": False, "error": "text required"}

        result = await self._knowledge_base.ingest_text(
            text=text,
            source=source or "desktop_upload",
            title=title or "Uploaded document",
        )
        if result.get("error"):
            return {"ok": False, "error": result["error"]}
        return {"ok": True, **result}

    async def _dashboard_search_kb(self, query: str) -> list[dict[str, Any]]:
        if not self._knowledge_base or not query:
            return []
        results = await self._knowledge_base.search(query)
        return [
            {
                "content": item.chunk.content,
                "document": item.document.filename if item.document else "",
                "score": item.score,
                "chunk_index": item.chunk.chunk_index,
            }
            for item in results
        ]

    async def _dashboard_delete_kb_document(self, document_id: str) -> dict[str, Any]:
        if not self._knowledge_base:
            return {"ok": False, "error": "Knowledge base not available"}
        ok = await self._knowledge_base.delete_document(document_id)
        return {"ok": bool(ok)}

    async def _dashboard_capture_screen_preview(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._desktop or not self._config.desktop.enabled or not self._config.features.desktop:
            return {
                "ok": False,
                "error": "Desktop assistant is disabled. Enable Desktop Control in the Computer + Voice Assistant tab first.",
            }

        payload = payload if isinstance(payload, dict) else {}
        monitor = int(payload.get("monitor", 0) or 0)
        result = await self._desktop.screenshot(monitor=monitor)
        if result.get("error"):
            return {"ok": False, "error": str(result.get("error"))}

        screenshot_b64 = str(result.get("screenshot_b64", "") or "")
        return {
            "ok": True,
            "monitor": int(result.get("monitor", monitor)),
            "width": int(result.get("width", 0) or 0),
            "height": int(result.get("height", 0) or 0),
            "screenshot_b64": screenshot_b64,
            "data_url": f"data:image/png;base64,{screenshot_b64}" if screenshot_b64 else "",
        }

    def _dashboard_reset_provider_circuit(self, name: str) -> bool:
        if not self._provider:
            return False
        return self._provider.reset_circuit(name)

    async def _handle_federation_message(self, content: str, from_name: str) -> str:
        """Process an incoming federation message through the cognitive pipeline."""
        return await self.process_message(
            content=content,
            author_id=f"fed:{from_name}",
            author_name=f"fed:{from_name}",
            channel_id=f"federation:{from_name}",
            channel_type_name="CLI",
        )

    def _get_a2a_skills(self) -> list[dict[str, Any]]:
        """Return JSON-safe skill metadata for the A2A agent card."""
        skills: list[dict[str, Any]] = []
        for manifest in self._skills.list_skills():
            skills.append(
                {
                    "name": manifest.name,
                    "description": manifest.description,
                    "version": manifest.version,
                    "capabilities": [cap.name for cap in manifest.capabilities],
                    "tools": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.to_json_schema(),
                        }
                        for tool in manifest.tools
                    ],
                }
            )
        return skills

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

    def _setup_signal_handlers(self) -> None:
        """Catch SIGTERM / SIGINT for clean shutdown."""
        loop = asyncio.get_running_loop()

        def _handle_signal(sig: int) -> None:
            self._logger.info("Received signal %s - initiating graceful shutdown", sig)
            if not self._shutdown_task or self._shutdown_task.done():
                self._shutdown_task = asyncio.create_task(self._graceful_shutdown())

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _handle_signal, sig)
            except NotImplementedError:
                pass

    async def _forge_skill_tool(self, source: str, use_case: str = "") -> dict:
        """Tool handler: forge a new skill from inside the agent."""
        if not self._forge:
            return {"error": "SkillForge not enabled"}
        result = await self._forge.steal(source, use_case=use_case)
        if result.success:
            # Add forged tools to the policy allowlist so they can be invoked
            if result.manifest:
                for tool in result.manifest.tools:
                    if tool.name not in self._config.policy.allowed_tools:
                        self._config.policy.allowed_tools.append(tool.name)
            return {
                "ok": True,
                "skill_name": result.skill_name,
                "tools": [t.name for t in result.manifest.tools] if result.manifest else [],
                "message": f"Skill '{result.skill_name}' is now active with {result.tools_generated} tools.",
            }
        return {"ok": False, "error": result.error, "clarifications": result.clarifications_needed}

    async def _scout_skill_tool(self, query: str) -> dict:
        """Tool handler: scout for the best package/API and forge it."""
        if not self._scout:
            return {"error": "SkillScout not enabled"}
        result = await self._scout.scout(query)
        if result.success:
            # Allowlist the forged tools
            if result.forge_result and result.forge_result.manifest:
                for tool in result.forge_result.manifest.tools:
                    if tool.name not in self._config.policy.allowed_tools:
                        self._config.policy.allowed_tools.append(tool.name)
            candidates_summary = [
                {"name": c.name, "registry": c.registry.value, "stars": c.stars}
                for c in result.candidates[:5]
            ]
            return {
                "ok": True,
                "skill_name": result.skill_name,
                "tools": result.tools,
                "candidates_searched": len(result.candidates),
                "top_candidates": candidates_summary,
                "chosen": result.chosen.name if result.chosen else "",
                "elapsed": result.elapsed_seconds,
                "message": (
                    f"Scouted {len(result.candidates)} candidates, "
                    f"forged '{result.skill_name}' with {len(result.tools)} tools."
                ),
            }
        return {
            "ok": False,
            "error": result.error,
            "candidates_searched": len(result.candidates),
        }

    async def _list_active_user_skills_tool(self) -> dict:
        """Tool handler: return the live runtime view of user skill registrations."""
        skills_dir = resolve_user_skills_dir(self._config.forge.user_skills_dir)
        skills = []
        missing_files = []
        for manifest in self._skills.list_user_skills():
            file_path = skills_dir / f"{manifest.name}.py"
            file_exists = file_path.exists()
            if not file_exists:
                missing_files.append(manifest.name)
            skills.append({
                "name": manifest.name,
                "description": manifest.description,
                "tools": [tool.name for tool in manifest.tools],
                "file_path": str(file_path),
                "file_exists": file_exists,
            })
        return {
            "ok": True,
            "count": len(skills),
            "skills_dir": str(skills_dir),
            "skills": skills,
            "ghost_skills": missing_files,
            "active_tool_names": sorted(
                tool_name
                for skill in skills
                for tool_name in skill["tools"]
            ),
        }

    async def _graceful_shutdown(self) -> None:
        """Ordered shutdown for in-flight requests and adapters."""
        if not self._running:
            return
        try:
            await asyncio.wait_for(self.stop(), timeout=30.0)
        except asyncio.TimeoutError:
            self._logger.warning("Graceful shutdown timed out after 30s")

    async def _gc_loop(self) -> None:
        """Periodic GC to guard memory growth on long-lived deployments."""
        while self._running:
            await asyncio.sleep(600)
            pruned_windows = self._rate_limiter.prune_windows() if self._rate_limiter else 0
            collected = gc.collect()
            # Expire stale workspace claims
            if self._workspace_coordinator:
                try:
                    await self._workspace_coordinator.cleanup_expired()
                except Exception:
                    pass
            rss_bytes = self._traceline._get_process_rss_bytes() if self._traceline else 0
            await self._bus.publish(
                EventType.INFO,
                {
                    "event": "gc_collect",
                    "collected": collected,
                    "pruned_rate_limit_windows": pruned_windows,
                    "rss_bytes": rss_bytes,
                },
                source="gateway",
            )

    async def _watch_config(self) -> None:
        """Hot-reload non-destructive config changes in dev mode."""
        if not self._config_path:
            return
        try:
            from pathlib import Path

            path = Path(self._config_path)
            try:
                from watchfiles import awatch

                async for _changes in awatch(path):
                    if not self._running:
                        break
                    self._logger.info("Config changed - reloading non-secret settings")
                    try:
                        new_config = load_config(path)
                        self._apply_hot_config(new_config)
                        self._logger.info("Config reloaded successfully")
                    except Exception as exc:
                        self._logger.error("Config reload failed: %s - keeping current config", exc)
            except ImportError:
                last_mtime = path.stat().st_mtime if path.exists() else 0.0
                while self._running:
                    await asyncio.sleep(1.0)
                    if not path.exists():
                        continue
                    mtime = path.stat().st_mtime
                    if mtime <= last_mtime:
                        continue
                    last_mtime = mtime
                    self._logger.info("Config changed - reloading non-secret settings")
                    try:
                        new_config = load_config(path)
                        self._apply_hot_config(new_config)
                        self._logger.info("Config reloaded successfully")
                    except Exception as exc:
                        self._logger.error("Config reload failed: %s - keeping current config", exc)
        except Exception as exc:
            self._logger.error("Config watch loop failed: %s", exc)

    def _apply_hot_config(self, new_config: NeuralClawConfig) -> None:
        """Apply non-destructive config changes without restart."""
        previous_allowed_tools = set(self._config.policy.allowed_tools or [])
        self._config.log_level = new_config.log_level
        self._config.persona = new_config.persona
        self._config.policy.allowed_tools = list(new_config.policy.allowed_tools)
        self._config.policy.mutating_tools = list(new_config.policy.mutating_tools)
        self._config.policy.allowed_filesystem_roots = list(new_config.policy.allowed_filesystem_roots)
        self._config.security.threat_threshold = new_config.security.threat_threshold
        self._config.apis = dict(new_config.apis or {})
        try:
            from neuralclaw.skills.builtins import api_client as _api_client
            from neuralclaw.skills.builtins import github_ops as _github_ops

            _api_client.set_api_configs(self._config.apis)
            _github_ops.set_api_configs(self._config.apis)
        except Exception:
            self._logger.debug("API-backed skill hot config refresh skipped", exc_info=True)
        self._reconcile_runtime_tool_policy(previous_allowed_tools)

    def _reconcile_runtime_tool_policy(self, previous_allowed_tools: set[str] | None = None) -> None:
        """Re-apply runtime tool allowlist entries after config reloads."""
        runtime_tools = {
            "list_active_user_skills",
            "list_features",
            "set_feature",
            "list_skills",
            "set_skill_enabled",
            "get_config",
            "list_available_models",
            "set_model_role",
            "list_workspace_structure",
            "list_available_skills",
            "get_skill_template",
            "get_active_agents",
            "claim_workspace_dir",
            "release_workspace_dir",
            "scaffold_project",
            "list_projects",
            "get_project_info",
            "add_to_project",
            "github_list_pull_requests",
            "github_get_pull_request",
            "github_list_issues",
            "github_get_issue",
            "github_get_ci_status",
            "github_comment_issue",
        }
        if self._config.features.skill_forge:
            runtime_tools.update({"forge_skill", "scout_skill"})
        if self._config.features.vision:
            runtime_tools.update({
                "analyze_image",
                "extract_text_from_image",
                "describe_screenshot",
                "compare_images",
                "detect_vision_capability",
            })
        for manifest in self._skills.list_user_skills():
            runtime_tools.update(tool.name for tool in manifest.tools)
        if previous_allowed_tools:
            runtime_tools.update(
                tool_name
                for tool_name in previous_allowed_tools
                if tool_name in {"forge_skill", "scout_skill", "list_active_user_skills"}
            )
        for tool_name in sorted(runtime_tools):
            if tool_name not in self._config.policy.allowed_tools:
                self._config.policy.allowed_tools.append(tool_name)

    async def _run_startup_readiness(self) -> None:
        state = await self._health.run_readiness_check()
        self._startup_readiness = state
        for result in self._health.get_readiness_results():
            self._logger.info(
                "Readiness probe %s required=%s ok=%s %s",
                result.name,
                result.required,
                result.ok,
                result.detail,
            )
        if state not in (ReadinessState.READY, ReadinessState.DEGRADED):
            raise ProviderError(
                "Gateway readiness checks failed.\n\n"
                "Required subsystems did not initialize cleanly.\n"
                "Run neuralclaw doctor for a full diagnostic."
            )
        self._ready_at = time.time()

    def _get_health_payload(self) -> dict[str, Any]:
        probes = {
            item.name: {
                "required": item.required,
                "ok": item.ok,
                "detail": item.detail,
            }
            for item in self._health.get_readiness_results()
        }
        status = "healthy" if self._startup_readiness in (ReadinessState.READY, ReadinessState.DEGRADED) else "unhealthy"
        return {
            "status": status,
            "readiness": self._startup_readiness.value,
            "runtime": {
                "process_state": "running" if status == "healthy" else "degraded",
                "readiness_phase": self._startup_readiness.value,
                "dashboard_bound": True,
                "adaptive_ready": bool(self._adaptive),
                "operator_api_ready": bool(self._adaptive),
            },
            "probes": probes,
            "version": __version__,
            "ready_at": self._ready_at,
        }

    def _get_ready_payload(self) -> dict[str, Any]:
        return {"status": self._startup_readiness.value}

    async def _get_metrics_payload(self) -> str:
        lines: list[str] = []
        if self._traceline:
            lines.append(await self._traceline.export_prometheus())
        if self._episodic:
            lines.append(
                "# HELP neuralclaw_memory_episodes_total Episodes in episodic memory\n"
                "# TYPE neuralclaw_memory_episodes_total gauge\n"
                f"neuralclaw_memory_episodes_total {await self._episodic.count()}\n"
            )
        return "".join(lines).strip() + "\n"

    async def _on_adaptive_bus_event(self, event) -> None:
        if not getattr(self, "_adaptive", None):
            return
        try:
            from neuralclaw.bus.neural_bus import EventType
            if event.type == EventType.ACTION_EXECUTING:
                if getattr(self, "_intent_predictor", None):
                    tool = event.data.get("tool_name", "unknown")
                    kwargs = event.data.get("tool_kwargs", {})
                    detail = str(kwargs)
                    asyncio.create_task(self._intent_predictor.observe(tool, detail))
                if getattr(self, "_routine_scheduler", None):
                    asyncio.create_task(self._routine_scheduler.observe_event("on_action_executing", dict(event.data or {})))
            elif event.type == EventType.SIGNAL_RECEIVED:
                if getattr(self, "_style_adapter", None):
                    msg = event.data.get("message")
                    channel = event.data.get("channel", "default")
                    if isinstance(msg, str) and msg:
                        asyncio.create_task(self._style_adapter.observe_message("channel", channel, msg))
                if getattr(self, "_routine_scheduler", None):
                    asyncio.create_task(self._routine_scheduler.observe_event("on_signal_received", dict(event.data or {})))
            elif event.type == EventType.ACTION_DENIED and getattr(self, "_routine_scheduler", None):
                asyncio.create_task(self._routine_scheduler.observe_event("on_approval_pending", dict(event.data or {})))
        except Exception:
            pass

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


# ---------------------------------------------------------------------------
# AGENTS.md orientation files
# ---------------------------------------------------------------------------

def _ensure_agents_md(config: "NeuralClawConfig") -> None:
    """
    Write AGENTS.md orientation files to key NeuralClaw directories.

    Idempotent — skips any file that already exists. These files tell agents
    (and human developers) what each directory contains and how to work with it.
    """
    from neuralclaw.config import CONFIG_DIR, DATA_DIR, LOG_DIR
    from neuralclaw.skills.paths import resolve_user_skills_dir

    skills_dir = resolve_user_skills_dir(getattr(config.forge, "user_skills_dir", None))
    repos_dir = Path(config.workspace.repos_dir).expanduser()
    apps_dir = Path(config.workspace.apps_dir).expanduser()

    files: dict[Path, str] = {
        CONFIG_DIR / "AGENTS.md": f"""\
# NeuralClaw Home Directory

This is the NeuralClaw runtime home (`{CONFIG_DIR}`).

## Key locations
- `config.toml` — main configuration: providers, features, channels, policy
- `data/`       — SQLite databases (memory, agents, tasks, workspace coordinator)
- `logs/`       — application and audit logs
- `sessions/`   — browser session profiles
- `skills/`     — user-installed skill plugins (hot-reloaded)
- `workspace/`  — repos and app projects

## Quick actions
- Edit config:         Open `config.toml` in any editor
- Add a skill:         Drop a .py file in `skills/`, it loads in ~3 s
- See diagnostics:     Run `neuralclaw doctor`
- Create a project:    Use the `scaffold_project` tool
""",
        skills_dir / "AGENTS.md": f"""\
# User Skills Directory

Drop Python skill files here (`{skills_dir}`).
They are hot-reloaded within ~3 seconds — no gateway restart needed.

## Required structure for every skill file

```python
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter
from neuralclaw.cortex.action.capabilities import Capability

async def my_tool(param: str, **kwargs) -> dict:
    \"\"\"Always async. kwargs absorbs extra args passed by the framework.\"\"\"
    return {{"result": param}}

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="my_skill",           # unique, snake_case
        description="What it does",
        capabilities=[Capability.NETWORK_HTTP],  # declare what the skill needs
        tools=[
            ToolDefinition(
                name="my_tool",
                description="Shown to the LLM — be precise",
                parameters=[
                    ToolParameter(name="param", type="string", description="...", required=True),
                    ToolParameter(name="count", type="integer", description="...", required=False, default=5),
                ],
                handler=my_tool,
            )
        ],
    )
```

## ToolParameter types
`string` | `integer` | `number` | `boolean` | `array` | `object`

For arrays, set `items_type` to the element type (default: `"string"`).
For enums, set `enum=["a", "b", "c"]`.

## Capability flags (import from neuralclaw.cortex.action.capabilities)
`FILESYSTEM_READ` | `FILESYSTEM_WRITE` | `NETWORK_HTTP` | `CODE_EXECUTION`
`MEMORY_READ` | `MEMORY_WRITE` | `CALENDAR_READ` | `CALENDAR_WRITE` | etc.

## Tips
- Use `get_skill_template` tool to get a ready-to-paste template
- Module-level state is fine for config (set by gateway via setter functions)
- Always handle exceptions and return a dict with an `"error"` key on failure
""",
        repos_dir / "AGENTS.md": f"""\
# Workspace Repos Directory (`{repos_dir}`)

This directory holds git repositories cloned via the `github_repos` skill.

## Working with repos
- Clone:   Use `clone_repo` tool from `github_repos` skill
- Run:     Use `repo_exec` skill tools to run commands inside a repo
- Code:    Use `code_exec` skill for sandboxed Python execution

## Multi-agent safety
Before writing to a repo directory, call `claim_workspace_dir(path)` to
prevent another agent from modifying the same files simultaneously.
Release with `release_workspace_dir(path)` when done.

## Blocked commands
`rm -rf`, `sudo`, `ssh`, `curl` are blocked by the security policy.
Use the appropriate skill tools instead.
""",
        apps_dir / "AGENTS.md": f"""\
# App Projects Directory (`{apps_dir}`)

This directory holds projects scaffolded by the `project_scaffold` skill.

## Creating a project
Use the `scaffold_project` tool. Available templates:
- `python-service` — production Python service with src/, tests/, Dockerfile
- `python-lib`     — Python library with typed stubs
- `fastapi`        — FastAPI app with routers and models
- `cli-tool`       — argparse CLI tool
- `data-pipeline`  — data processing with notebooks/
- `agent-skill`    — NeuralClaw skill with tests
- `generic`        — simple flat structure

Each created project has its own `AGENTS.md` describing its layout.

## Listing projects
Use the `list_projects` tool to see what exists here.
""",
        DATA_DIR / "AGENTS.md": """\
# NeuralClaw Data Directory

SQLite databases — **do not edit directly**.

| File                  | Contents                                  |
|-----------------------|-------------------------------------------|
| `memory.db`           | Episodic + semantic memory                |
| `memory-agents.db`    | Spawned agent definitions                 |
| `memory-tasks.db`     | Swarm task records                        |
| `memory-shared.db`    | Cross-agent shared memory bridge          |
| `memory-workspace.db` | Workspace directory claim/release state   |
| `traces.db`           | Reasoning traces (read-only observability)|
| `knowledge.db`        | RAG document chunks                       |
| `workflows.db`        | Workflow engine state                     |
| `channel_bindings.json` | Active channel connection metadata      |

Use the `recall_memory`, `store_memory`, and knowledge-base tools to interact
with memory programmatically. Direct SQLite edits may corrupt internal state.
""",
    }

    for path, content in files.items():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(content, encoding="utf-8")
        except Exception:
            pass  # Non-fatal — best effort
