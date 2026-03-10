import pytest
from pathlib import Path

from neuralclaw.config import PolicyConfig
from neuralclaw.cortex.action.policy import resolve_and_validate_path, PolicyEngine, RequestContext
from neuralclaw.cortex.action.sandbox import Sandbox, SandboxPathDenied

def test_resolve_and_validate_path_allowed(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    
    file_path = root / "test.txt"
    resolved, result = resolve_and_validate_path(str(file_path), [root])
    assert result.allowed
    assert resolved == file_path.resolve()

def test_resolve_and_validate_path_denied_traversal(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    
    # Try to access parent directory
    file_path = root / ".." / "secret.txt"
    resolved, result = resolve_and_validate_path(str(file_path), [root])
    assert not result.allowed
    assert "outside" in result.reason

def test_sandbox_working_dir_validation(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    
    sandbox = Sandbox(allowed_dirs=[str(root)])
    
    # Should work
    assert sandbox._validate_working_dir(str(root))
    
    # Should fail due to being outside allowed dirs
    with pytest.raises(SandboxPathDenied):
        sandbox._validate_working_dir(str(tmp_path))

def test_policy_engine_shell_execution():
    config = PolicyConfig(deny_shell_execution=True)
    engine = PolicyEngine(config)
    
    result = engine.check_tool_call("shell_exec", {"command": "ls"})
    assert not result.allowed
    assert "shell" in result.reason

def test_policy_engine_tool_limit():
    config = PolicyConfig(max_tool_calls_per_request=2)
    engine = PolicyEngine(config)
    ctx = RequestContext()
    
    # 1. Allowed
    res1 = engine.check_tool_call("any_tool", {}, ctx)
    assert res1.allowed
    assert ctx.tool_calls == 1
    
    # 2. Allowed
    res2 = engine.check_tool_call("any_tool", {}, ctx)
    assert res2.allowed
    assert ctx.tool_calls == 2
    
    # 3. Denied
    res3 = engine.check_tool_call("any_tool", {}, ctx)
    assert not res3.allowed
    assert "limit" in res3.reason
