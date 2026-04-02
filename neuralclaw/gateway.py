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
import io
import inspect
import logging
import re
import secrets
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any

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
    ensure_dirs,
    get_api_key,
    load_config,
    set_api_key,
    update_config,
)
from neuralclaw.cortex.action.audit import AuditLogger
from neuralclaw.cortex.action.capabilities import CapabilityVerifier
from neuralclaw.cortex.action.idempotency import IdempotencyStore
from neuralclaw.cortex.action.policy import PolicyEngine
from neuralclaw.cortex.memory.db import DBPool
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.identity import UserIdentityStore
from neuralclaw.cortex.memory.metabolism import MemoryMetabolism
from neuralclaw.cortex.memory.procedural import ProceduralMemory
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
from neuralclaw.cortex.reasoning.reflective import ReflectiveReasoner
from neuralclaw.cortex.reasoning.meta import MetaCognitive
from neuralclaw.cortex.reasoning.structured import StructuredReasoner
from neuralclaw.cortex.observability.traceline import Traceline
from neuralclaw.cortex.evolution.calibrator import BehavioralCalibrator
from neuralclaw.cortex.evolution.distiller import ExperienceDistiller
from neuralclaw.cortex.evolution.orchestrator import EvolutionOrchestrator
from neuralclaw.cortex.evolution.synthesizer import SkillSynthesizer
from neuralclaw.errors import ChannelError, ConfigurationError, ProviderError, SecurityError
from neuralclaw.health import HealthChecker, ReadinessProbe, ReadinessState
from neuralclaw.providers.circuit_breaker import CircuitBreakerConfig
from neuralclaw.providers.router import LLMProvider, ProviderRouter
from neuralclaw.skills.registry import SkillRegistry
from neuralclaw.skills.paths import resolve_user_skills_dir
from neuralclaw.swarm.delegation import DelegationChain, DelegationPolicy
from neuralclaw.swarm.consensus import ConsensusProtocol
from neuralclaw.swarm.mesh import AgentMesh
from neuralclaw.swarm.federation import FederationProtocol, FederationBridge
from neuralclaw.swarm.spawn import AgentSpawner
from neuralclaw.swarm.agent_store import AgentStore
from neuralclaw.swarm.task_store import TaskRecord, TaskStore
from neuralclaw.cortex.memory.shared import SharedMemoryBridge


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
        self._channel_pairing_adapters: dict[str, ChannelAdapter] = {}
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
        # Use role-based embed model if model_roles is enabled
        _embed_model = self._config.memory.embedding_model
        _embed_base_url = ""
        if self._config.model_roles.enabled:
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
        self._audit = AuditLogger(config=self._config.audit, bus=self._bus)
        self._deliberate = DeliberativeReasoner(
            self._bus,
            self._config.persona,
            policy=self._policy,
            idempotency=self._idempotency,
            audit=self._audit,
        )
        self._structured = StructuredReasoner(self._deliberate, self._bus) if feat.structured_output else None
        self._reflective = ReflectiveReasoner(self._bus, self._deliberate, structured=self._structured)

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

        # Phase 2: Procedural memory + metabolism
        self._procedural = ProceduralMemory(
            self._config.memory.db_path,
            self._bus,
            db_pool=self._memory_db_pool,
        ) if feat.procedural_memory else None
        self._metabolism = MemoryMetabolism(
            self._episodic, self._semantic if feat.semantic_memory else None, self._bus,
            vector_memory=self._vector_memory,
        ) if feat.evolution else None

        # Phase 2: Evolution cortex
        self._calibrator = BehavioralCalibrator(bus=self._bus) if feat.evolution else None
        self._distiller = ExperienceDistiller(
            self._episodic, self._semantic, self._procedural, self._bus,
            structured=self._structured,
        ) if feat.evolution else None
        self._synthesizer = SkillSynthesizer(bus=self._bus, structured=self._structured) if feat.evolution else None
        self._evolution_orchestrator = None

        # Phase 3: Meta-cognitive reasoning
        self._meta_cognitive = MetaCognitive(bus=self._bus) if feat.evolution else None
        self._traceline = Traceline(
            self._config.traceline.db_path,
            self._bus,
            config=self._config.traceline,
            db_pool=self._trace_db_pool,
        ) if feat.traceline and self._config.traceline.enabled else None

        if self._identity and self._calibrator:
            self._identity.set_calibrator(self._calibrator)

        # Phase 3: Swarm
        self._delegation = DelegationChain(bus=self._bus) if feat.swarm else None
        self._consensus = ConsensusProtocol(self._delegation, bus=self._bus) if feat.swarm else None
        self._mesh = AgentMesh(bus=self._bus) if feat.swarm else None

        # Phase 4: Spawner + Federation
        self._spawner: AgentSpawner | None = None
        self._federation: FederationProtocol | None = None
        self._federation_bridge: FederationBridge | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

        # Agent persistence + shared memory
        self._agent_store: AgentStore | None = None
        self._task_store: TaskStore | None = None
        self._shared_bridge: SharedMemoryBridge | None = None
        self._local_model_registry_cache: dict[str, Any] = {"models": [], "resolved_base_url": "", "badges": []}
        self._local_model_registry_at: float = 0.0

        if feat.swarm and self._mesh and self._delegation:
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
            self._dashboard = Dashboard(port=self._config.dashboard_port)
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
                required=True,
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
        if self._workflow_engine:
            await self._workflow_engine.initialize()

        # Initialize agent store + shared memory bridge
        if self._agent_store:
            await self._agent_store.initialize()
        if self._task_store:
            await self._task_store.initialize()
        if self._shared_bridge:
            await self._shared_bridge.initialize()

        # Initialize idempotency store
        await self._idempotency.initialize()

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

        if self._provider:
            self._deliberate.set_provider(self._provider)
            # Inject role router into deliberative reasoner and classifier
            if self._role_router:
                self._deliberate.set_role_router(self._role_router)
                self._classifier.set_role_router(self._role_router)
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
            )
            self._dashboard.set_skills_provider(self._get_dashboard_skills)
            self._dashboard.set_swarm_provider(self._get_dashboard_agents)
            self._dashboard.set_task_providers(
                self._dashboard_list_tasks,
                self._dashboard_get_task,
            )
            self._dashboard.set_local_models_provider(self._dashboard_get_local_model_health)
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
                )
            if self._federation:
                self._dashboard.set_join_federation_action(self._federation.join_federation)
                self._dashboard.set_message_peer_action(self._dashboard_message_peer)
            self._dashboard.set_send_message_action(self._dashboard_send_message)
            self._dashboard.set_clear_memory_action(self._dashboard_clear_memory)
            self._dashboard.set_knowledge_base_actions(
                list_action=self._dashboard_list_kb_documents,
                ingest_action=self._dashboard_ingest_kb_document,
                ingest_text_action=self._dashboard_ingest_kb_text,
                search_action=self._dashboard_search_kb,
                delete_action=self._dashboard_delete_kb_document,
            )
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

    def _build_local(
        self,
        cfg: Any,
        request_timeout_seconds: float | None = None,
    ) -> LLMProvider | None:
        from neuralclaw.providers.local import LocalProvider
        return LocalProvider(
            model=cfg.model or "qwen3.5:35b",
            base_url=cfg.base_url or self._candidate_local_base_urls("")[0],
            request_timeout_seconds=request_timeout_seconds or 120.0,
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
    ) -> ChannelAdapter | None:
        import logging as _log
        _logger = _log.getLogger("neuralclaw.gateway")

        def _log_qr(data: str) -> None:
            _logger.info("[WhatsApp] QR code received — pair via neuralclaw channels connect whatsapp")

        from neuralclaw.channels.whatsapp_baileys import BaileysWhatsAppAdapter
        return BaileysWhatsAppAdapter(auth_dir=cfg.token, on_qr=on_qr or _log_qr)

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

        if not self._dev_mode:
            cooldown_until = self._security_cooldowns.get(author_id, 0.0)
            now = time.monotonic()
            if cooldown_until > now:
                retry_after = cooldown_until - now
                return f"Access temporarily blocked for safety. Retry in {retry_after:.0f}s."

            allowed, retry_after = self._rate_limiter.check(author_id)
            if not allowed:
                return (
                    "You're sending messages too quickly. "
                    f"Please wait {retry_after:.0f}s and try again."
                )

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
    ) -> None:
        """Store the interaction in episodic memory with smart importance scoring."""
        try:
            user_importance = self._score_importance(user_msg)
            # Agent replies inherit slightly less importance than the user message
            agent_importance = max(0.3, user_importance - 0.1)

            user_tags = [tag for tag in (
                f"user_id:{user_id}" if user_id else "",
                f"channel:{channel_id}" if channel_id else "",
            ) if tag]

            await self._episodic.store(
                content=f"{author}: {user_msg}",
                source="conversation",
                author=author,
                importance=user_importance,
                tags=user_tags,
            )
            await self._episodic.store(
                content=f"NeuralClaw: {agent_msg}",
                source="conversation",
                author="NeuralClaw",
                importance=agent_importance,
                tags=[tag for tag in (
                    f"reply_to_user:{user_id}" if user_id else "",
                    f"channel:{channel_id}" if channel_id else "",
                ) if tag],
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
        if self._config.google_workspace.enabled:
            caps.append("You have Google Workspace access (Gmail, Calendar, Drive, Docs, Sheets).")
        if self._config.microsoft365.enabled:
            caps.append("You have Microsoft 365 access (Outlook, Calendar, Teams, OneDrive).")
        if self._config.tts.enabled:
            caps.append("You can generate voice/speech audio responses.")
        if feat.reflective_reasoning:
            caps.append("For complex multi-step problems, you use reflective reasoning (think step-by-step, critique, and refine).")

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
            "- Reference your memory when relevant to the conversation.\n"
            "- If uncertain, say so. If a tool can verify, use it first.\n"
            "- Be concise but thorough. Adapt your style to the user.\n"
        )
        return fragments

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
        await self._memory_db_pool.close()
        if self._traceline:
            await self._trace_db_pool.close()
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
            "readiness": self._startup_readiness.value,
            "circuits": self._provider.get_circuit_states() if self._provider else {},
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

    async def _get_dashboard_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._traceline:
            return []
        traces = await self._traceline.query_traces(limit=limit)
        return [self._trace_to_dict(trace) for trace in traces]

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
            snapshots.append({
                "name": name,
                "label": labels[name],
                "description": descriptions[name],
                "enabled": bool(cfg.enabled) if cfg else bool(raw.get("enabled", False)),
                "configured": self._channel_configured(name, cfg, extra),
                "running": name in self._channels,
                "trust_mode": str((cfg.trust_mode if cfg else raw.get("trust_mode", "")) or ""),
                "token_present": bool(cfg.token) if cfg else self._channel_has_secret(name),
                "restart_required": True,
                "extra": self._channel_extra_snapshot(name, extra),
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

    def _channel_extra_snapshot(self, channel_name: str, extra: dict[str, Any]) -> dict[str, Any]:
        if channel_name == "discord":
            return {
                "voice_responses": bool(extra.get("voice_responses", False)),
                "auto_disconnect_empty_vc": bool(extra.get("auto_disconnect_empty_vc", True)),
                "voice_channel_id": str(extra.get("voice_channel_id", "") or ""),
            }
        if channel_name == "slack":
            return {
                "app_token_present": bool(extra.get("slack_app") or get_api_key("slack_app")),
            }
        if channel_name == "whatsapp":
            auth_dir = str(extra.get("auth_dir", "") or "")
            return {
                "auth_dir": auth_dir,
                "auth_dir_present": bool(auth_dir),
            }
        return {}

    def _channel_configured(self, channel_name: str, cfg: Any, extra: dict[str, Any]) -> bool:
        token = bool(cfg.token) if cfg else self._channel_has_secret(channel_name)
        if channel_name == "slack":
            return token and bool(extra.get("slack_app") or get_api_key("slack_app"))
        return token

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
        self._apply_hot_config(reloaded)

    async def _dashboard_update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(updates, dict):
            return {"ok": False, "error": "config payload must be an object"}

        provider_secrets = updates.pop("provider_secrets", {})
        if provider_secrets and not isinstance(provider_secrets, dict):
            return {"ok": False, "error": "provider_secrets must be an object"}

        for provider_name, secret in provider_secrets.items():
            if str(secret).strip():
                set_api_key(str(provider_name), str(secret).strip())

        if updates:
            update_config(updates, Path(self._config_path) if self._config_path else None)

        reloaded = load_config(Path(self._config_path) if self._config_path else None)
        self._refresh_runtime_config(reloaded)
        restart_required = bool(
            {
                "providers",
                "channels",
                "model_roles",
                "google_workspace",
                "microsoft365",
                "desktop",
                "browser",
                "security",
                "policy",
                "tts",
                "features",
            }
            & set(updates.keys())
        ) or bool(provider_secrets)
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

        if channel_name == "discord":
            channel_update["voice_responses"] = bool(extra.get("voice_responses", False))
            channel_update["auto_disconnect_empty_vc"] = bool(extra.get("auto_disconnect_empty_vc", True))
            channel_update["voice_channel_id"] = str(extra.get("voice_channel_id", "") or "")
        elif channel_name == "whatsapp":
            channel_update["auth_dir"] = str(extra.get("auth_dir", "") or "")

        secret = str(data.get("secret", "") or "").strip()
        if secret:
            set_api_key(channel_name, secret)

        if channel_name == "slack":
            app_token = str(extra.get("slack_app", "") or "").strip()
            if app_token:
                set_api_key("slack_app", app_token)

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
            auth_dir = str(extra.get("auth_dir", "") or token).strip()
            if not auth_dir:
                return {"ok": False, "error": "WhatsApp requires an auth directory"}
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
            auth_dir = str((Path.home() / ".neuralclaw" / "sessions" / "whatsapp").resolve())
        Path(auth_dir).mkdir(parents=True, exist_ok=True)

        creds_path = Path(auth_dir) / "creds.json"
        if creds_path.exists():
            return {
                "ok": True,
                "paired": True,
                "auth_dir": auth_dir,
                "message": f"WhatsApp is already paired using {auth_dir}.",
            }

        from neuralclaw.config import ChannelConfig

        qr_event = asyncio.Event()
        qr_payload: dict[str, str] = {}

        def _capture_qr(qr_data: str) -> None:
            qr_payload["raw"] = qr_data
            qr_event.set()

        cfg = ChannelConfig(
            name="whatsapp",
            enabled=True,
            token=auth_dir,
            extra={"auth_dir": auth_dir},
        )

        await self._stop_channel_pairing("whatsapp")
        try:
            adapter = self._build_whatsapp_channel(cfg, on_qr=_capture_qr)
            if not adapter:
                return {"ok": False, "error": "Unable to initialize WhatsApp adapter"}

            self._channel_pairing_adapters["whatsapp"] = adapter
            await adapter.start()
            await asyncio.wait_for(qr_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            ok, message = await adapter.test_connection()
            if ok:
                return {
                    "ok": True,
                    "paired": True,
                    "auth_dir": auth_dir,
                    "message": message,
                }
            await self._stop_channel_pairing("whatsapp")
            return {
                "ok": False,
                "error": "Timed out waiting for a WhatsApp QR code. Verify Node.js is installed and try again.",
            }
        except Exception as exc:
            await self._stop_channel_pairing("whatsapp")
            return {"ok": False, "error": str(exc)}

        qr_raw = qr_payload.get("raw", "")
        if not qr_raw:
            await self._stop_channel_pairing("whatsapp")
            return {"ok": False, "error": "WhatsApp pairing did not provide a QR code"}

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
        return self._spawner.despawn(name)

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

        provider = str(data.get("provider", "local") or "local").strip() or "local"
        model = str(data.get("model", "") or "").strip()
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
            "base_url": str(data.get("base_url", "") or "").strip(),
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
            if payload["provider"] in {"local", "meta"}:
                payload["model"], payload["base_url"] = await self._validate_local_model(
                    payload["model"],
                    payload["base_url"],
                )
            existing = await self._agent_store.get_by_name(payload["name"])
            if existing:
                return {"ok": False, "error": f"Agent '{payload['name']}' already exists"}
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
            provider_name = str(payload.get("provider") or existing.provider or "local")
            model_name = str(payload.get("model") or existing.model or "")
            base_url = str(payload.get("base_url") or existing.base_url or "")
            if provider_name in {"local", "meta"} and model_name:
                payload["model"], payload["base_url"] = await self._validate_local_model(
                    model_name,
                    base_url,
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
                resolved_model, resolved_base_url = await self._validate_local_model(defn.model, defn.base_url)
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
        provider = str(
            (definition.provider if definition else "")
            or (runtime.definition.provider if runtime else "")
            or "local"
        ).strip().lower()
        requested_model = str(
            (definition.model if definition else "")
            or (runtime.definition.model if runtime else "")
            or getattr(self._config.model_roles, "primary", "")
            or self._get_provider_config("local").model
            or ""
        ).strip()
        base_url = str(
            (definition.base_url if definition else "")
            or (runtime.definition.base_url if runtime else "")
            or self._get_provider_config("local").base_url
            or getattr(self._config.model_roles, "base_url", "")
            or ""
        ).strip()
        effective_model = requested_model
        fallback_reason = None

        if provider in {"local", "meta", "ollama"}:
            effective_model, base_url, fallback_reason = await self._resolve_local_model_with_fallback(
                requested_model,
                base_url,
            )
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

        profiles: dict[str, dict[str, Any]] = {}
        for target in targets:
            profiles[target] = await self._resolve_agent_execution_profile(target)

        ctx = DelegationContext(
            task_description=task,
            constraints={"shared_task_id": shared_task_id} if shared_task_id else {},
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
            task_id = ""
            child_task_ids: list[str] = []
            started_at = time.time()
            if self._task_store:
                parent_profile = profiles[targets[0]]
                parent_task = TaskRecord(
                    task_id="",
                    title=(task.strip().splitlines()[0][:72] or "Delegated task"),
                    prompt=task,
                    status="running",
                    provider=str(parent_profile.get("provider", "")),
                    requested_model=str(parent_profile.get("requested_model", "")),
                    effective_model=str(parent_profile.get("effective_model", "")),
                    base_url=str(parent_profile.get("base_url", "")),
                    target_agents=targets,
                    shared_task_id=shared_task_id,
                    started_at=started_at,
                    metadata={
                        "fallback_reason": parent_profile.get("fallback_reason"),
                        "multi_agent": len(targets) > 1,
                    },
                )
                task_id = await self._task_store.create(parent_task)
                for target in targets:
                    profile = profiles[target]
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
                            metadata={
                                "fallback_reason": profile.get("fallback_reason"),
                            },
                        )
                    )
                    child_task_ids.append(child_id)
                await self._task_store.update(task_id, child_task_ids=child_task_ids)

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
                    child_status = result.status.name.lower()
                    await self._task_store.update(
                        child_task_ids[0],
                        status=child_status,
                        result=result.result or "",
                        error=result.error or "",
                        completed_at=completed_at,
                        started_at=started_at,
                        effective_model=str(profile.get("effective_model", "")),
                        metadata={
                            "confidence": result.confidence,
                            "fallback_reason": profile.get("fallback_reason"),
                        },
                    )
                    await self._task_store.update(
                        task_id,
                        status=child_status,
                        result=result.result or "",
                        error=result.error or "",
                        completed_at=completed_at,
                        started_at=started_at,
                        effective_model=str(profile.get("effective_model", "")),
                        metadata={
                            "confidence": result.confidence,
                            "fallback_reason": profile.get("fallback_reason"),
                        },
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

            request_ids = {
                name: log_activity(
                    from_agent="dashboard",
                    to_agent=name,
                    content=task,
                    message_type="delegation",
                )
                for name in targets
            }
            results = await self._delegation.delegate_parallel([(name, ctx) for name in targets])
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
                for agent, child_id, res in zip(targets, child_task_ids, results, strict=False):
                    profile = profiles[agent]
                    await self._task_store.update(
                        child_id,
                        status=res.status.name.lower(),
                        result=res.result or "",
                        error=res.error or "",
                        completed_at=completed_at,
                        started_at=started_at,
                        effective_model=str(profile.get("effective_model", "")),
                        metadata={
                            "confidence": res.confidence,
                            "fallback_reason": profile.get("fallback_reason"),
                        },
                    )
                await self._task_store.update(
                    task_id,
                    status=aggregate_status,
                    result=aggregate_result,
                    error="" if completed_count > 0 else "Delegation failed for all selected agents",
                    completed_at=completed_at,
                    started_at=started_at,
                    metadata={
                        "fallback_reasons": {
                            agent: profile.get("fallback_reason")
                            for agent, profile in profiles.items()
                            if profile.get("fallback_reason")
                        },
                    },
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
                "error": None if completed_count > 0 else "Delegation failed for all selected agents",
                "shared_task_id": shared_task_id or None,
            }
        except Exception as e:
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

        target_agent = str(data.get("target_agent", "") or "").strip()
        if target_agent:
            delegated = await self._dashboard_delegate_task(
                {
                    "task": content,
                    "agent_name": target_agent,
                }
            )
            if not delegated.get("ok"):
                return delegated
            response_text = (
                delegated.get("result")
                or "\n\n".join(
                    f"[{entry.get('agent', target_agent)}] {entry.get('result') or entry.get('status', '')}"
                    for entry in delegated.get("results", [])
                ).strip()
                or "Task completed."
            )
            return {
                "ok": True,
                "response": response_text,
                "routed_to": target_agent,
                "task_id": delegated.get("task_id"),
                "requested_model": delegated.get("requested_model"),
                "effective_model": delegated.get("effective_model"),
            }

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

        provider_name = str(data.get("provider", "") or "").strip().lower()
        requested_model = str(data.get("model", "") or "").strip()
        model_name = requested_model
        base_url = str(data.get("base_url", "") or "").strip()
        fallback_reason = None
        effective_model = requested_model or None
        if provider_name in {"local", "meta"} and requested_model:
            model_name, base_url, fallback_reason = await self._resolve_local_model_with_fallback(
                requested_model,
                base_url,
            )
            effective_model = model_name

        response = await self._process_dashboard_message_with_override(
            content=content,
            media=media,
            metadata=metadata,
            provider_name=provider_name,
            model_name=model_name,
            base_url=base_url,
        )
        return {
            "ok": True,
            "response": response,
            "model": effective_model or None,
            "requested_model": requested_model or None,
            "effective_model": effective_model or None,
            "fallback_reason": fallback_reason,
        }

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
        timeout = aiohttp.ClientTimeout(total=5)
        last_error: Exception | None = None

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for raw_base in self._candidate_local_base_urls(base_url):
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

        if last_error:
            self._logger.debug("Local model discovery failed for all configured endpoints: %s", last_error)
        fallback = self._candidate_local_base_urls(base_url)[0] if self._candidate_local_base_urls(base_url) else "http://localhost:11434/v1"
        return [], fallback

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

    async def _validate_local_model(self, model: str, base_url: str) -> tuple[str, str]:
        resolved, resolved_base_url, fallback_reason = await self._resolve_local_model_with_fallback(model, base_url)
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
    ) -> str:
        if provider_name not in {"local", "meta"} or not model_name:
            return await self.process_message(
                content=content,
                author_id="dashboard",
                author_name="Dashboard",
                channel_id="dashboard",
                channel_type_name="CLI",
                media=media,
                message_metadata=metadata,
            )

        resolved_model, resolved_base_url = await self._validate_local_model(model_name, base_url)
        temp_provider = self._build_local(
            ProviderConfig(
                name="local",
                model=resolved_model,
                base_url=resolved_base_url,
            )
        )
        if not temp_provider:
            raise ProviderError("Unable to create local provider override")

        original_provider = self._provider
        original_vision = self._vision
        self._provider = temp_provider
        self._deliberate.set_provider(temp_provider)
        if self._config.features.vision:
            self._vision = VisionPerception(temp_provider, self._bus)
        try:
            return await self.process_message(
                content=content,
                author_id="dashboard",
                author_name="Dashboard",
                channel_id="dashboard",
                channel_type_name="CLI",
                media=media,
                message_metadata=metadata,
            )
        finally:
            self._provider = original_provider
            if original_provider:
                self._deliberate.set_provider(original_provider)
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
        self._config.log_level = new_config.log_level
        self._config.persona = new_config.persona
        self._config.policy.allowed_tools = list(new_config.policy.allowed_tools)
        self._config.security.threat_threshold = new_config.security.threat_threshold

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
            "probes": probes,
            "version": __version__,
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
