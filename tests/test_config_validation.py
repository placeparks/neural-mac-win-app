"""Tests for config validation."""

import toml

from neuralclaw.config import (
    NeuralClawConfig,
    ProviderConfig,
    SecurityConfig,
    ChannelConfig,
    validate_config,
    ConfigValidationResult,
    load_config,
)


class TestConfigValidation:
    def test_valid_config(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="openai", model="gpt-4o", base_url="", api_key="sk-test"),
        )
        result = validate_config(config)
        assert result.valid
        assert len(result.errors) == 0

    def test_missing_api_key(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="openai", model="gpt-4o", base_url="", api_key=None),
        )
        result = validate_config(config)
        assert not result.valid
        assert any("API key" in e for e in result.errors)

    def test_proxy_without_base_url(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="proxy", model="gpt-4", base_url=""),
        )
        result = validate_config(config)
        assert not result.valid
        assert any("base_url" in e for e in result.errors)

    def test_proxy_with_base_url(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="proxy", model="gpt-4", base_url="http://localhost:8080/v1"),
        )
        result = validate_config(config)
        assert result.valid

    def test_local_no_key_ok(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="llama3", base_url="http://localhost:11434/v1"),
        )
        result = validate_config(config)
        assert result.valid

    def test_invalid_threat_threshold(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="", base_url=""),
            security=SecurityConfig(threat_threshold=1.5),
        )
        result = validate_config(config)
        assert not result.valid
        assert any("threat_threshold" in e for e in result.errors)

    def test_invalid_block_threshold(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="", base_url=""),
            security=SecurityConfig(block_threshold=-0.1),
        )
        result = validate_config(config)
        assert not result.valid
        assert any("block_threshold" in e for e in result.errors)

    def test_channel_enabled_no_token_warning(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="", base_url=""),
            channels=[ChannelConfig(name="telegram", enabled=True, token=None)],
        )
        result = validate_config(config)
        assert result.valid  # warnings don't make it invalid
        assert any("telegram" in w for w in result.warnings)

    def test_result_dataclass(self):
        r = ConfigValidationResult(valid=True, errors=[], warnings=["test warning"])
        assert r.valid
        assert len(r.warnings) == 1

    def test_invalid_vector_settings(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="", base_url=""),
        )
        config.memory.embedding_dimension = 0
        config.memory.vector_similarity_top_k = 0

        result = validate_config(config)

        assert not result.valid
        assert any("embedding_dimension" in e for e in result.errors)
        assert any("vector_similarity_top_k" in e for e in result.errors)

    def test_invalid_custom_pii_pattern(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="", base_url=""),
            security=SecurityConfig(pii_patterns=["["]),
        )

        result = validate_config(config)

        assert not result.valid
        assert any("pii_patterns" in e for e in result.errors)

    def test_invalid_audit_limits(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="", base_url=""),
        )
        config.audit.max_memory_entries = 0
        config.audit.retention_days = -1

        result = validate_config(config)

        assert not result.valid
        assert any("audit.max_memory_entries" in e for e in result.errors)
        assert any("audit.retention_days" in e for e in result.errors)

    def test_invalid_desktop_settings(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="", base_url=""),
        )
        config.desktop.action_delay_ms = -1
        config.browser.navigation_timeout = 0
        config.policy.desktop_blocked_regions = ["10,20,30"]

        result = validate_config(config)

        assert not result.valid
        assert any("desktop.action_delay_ms" in e for e in result.errors)
        assert any("browser.navigation_timeout" in e for e in result.errors)
        assert any("desktop_blocked_regions" in e for e in result.errors)

    def test_invalid_voice_and_workspace_limits(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="", base_url=""),
        )
        config.tts.max_tts_chars = 0
        config.tts.speed = 0
        config.google_workspace.max_email_results = 0
        config.google_workspace.max_drive_results = 0
        config.google_workspace.response_body_limit = 0
        config.microsoft365.max_email_results = 0
        config.microsoft365.max_file_results = 0

        result = validate_config(config)

        assert not result.valid
        assert any("tts.max_tts_chars" in e for e in result.errors)
        assert any("tts.speed" in e for e in result.errors)
        assert any("google_workspace.max_email_results" in e for e in result.errors)
        assert any("google_workspace.max_drive_results" in e for e in result.errors)
        assert any("google_workspace.response_body_limit" in e for e in result.errors)
        assert any("microsoft365.max_email_results" in e for e in result.errors)
        assert any("microsoft365.max_file_results" in e for e in result.errors)

    def test_load_config_reads_vector_memory_fields(self, tmp_path):
        config_path = tmp_path / "config.toml"
        with config_path.open("w", encoding="utf-8") as fh:
            toml.dump(
                {
                    "features": {
                        "vector_memory": False,
                        "vision": True,
                        "voice": True,
                        "browser": True,
                        "structured_output": False,
                        "streaming_responses": True,
                        "streaming_edit_interval": 9,
                        "desktop": True,
                        "a2a_federation": True,
                    },
                    "identity": {"enabled": False, "cross_channel": False, "inject_in_prompt": False},
                    "traceline": {"enabled": True, "db_path": "/tmp/traces.db", "retention_days": 14},
                    "audit": {
                        "enabled": True,
                        "jsonl_path": "/tmp/audit.jsonl",
                        "max_memory_entries": 50,
                        "retention_days": 14,
                        "siem_export": True,
                        "include_args": False,
                    },
                    "desktop": {
                        "enabled": True,
                        "screenshot_on_action": False,
                        "action_delay_ms": 25,
                    },
                    "tts": {
                        "enabled": True,
                        "provider": "piper",
                        "voice": "en_US-lessac-medium",
                        "speed": 1.1,
                        "output_format": "wav",
                        "auto_speak": True,
                        "max_tts_chars": 300,
                    },
                    "browser": {
                        "enabled": True,
                        "headless": False,
                        "browser_type": "firefox",
                        "navigation_timeout": 12,
                        "max_steps_per_task": 7,
                        "allowed_domains": ["example.com"],
                    },
                    "google_workspace": {
                        "enabled": True,
                        "max_email_results": 4,
                        "max_drive_results": 5,
                        "response_body_limit": 1234,
                    },
                    "microsoft365": {
                        "enabled": True,
                        "tenant_id": "tenant-1",
                        "max_email_results": 6,
                        "max_file_results": 7,
                        "default_user": "alice@example.com",
                    },
                    "federation": {
                        "a2a_enabled": True,
                        "a2a_auth_required": False,
                    },
                    "policy": {
                        "parallel_tool_execution": False,
                    },
                    "memory": {
                        "vector_memory": False,
                        "embedding_provider": "openai",
                        "embedding_model": "text-embedding-3-small",
                        "embedding_dimension": 1536,
                        "vector_similarity_top_k": 7,
                    },
                    "security": {
                        "output_filtering": True,
                        "output_pii_detection": False,
                        "output_prompt_leak_check": True,
                        "canary_tokens": False,
                        "pii_patterns": ["employee-[0-9]+"],
                    },
                },
                fh,
            )

        config = load_config(config_path)

        assert not config.features.vector_memory
        assert config.features.vision
        assert config.features.voice
        assert config.features.browser
        assert not config.features.structured_output
        assert config.features.streaming_responses
        assert config.features.streaming_edit_interval == 9
        assert config.features.desktop
        assert config.features.a2a_federation
        assert not config.identity.enabled
        assert not config.identity.cross_channel
        assert not config.identity.inject_in_prompt
        assert config.traceline.enabled
        assert config.traceline.db_path == "/tmp/traces.db"
        assert config.traceline.retention_days == 14
        assert config.audit.enabled
        assert config.audit.jsonl_path == "/tmp/audit.jsonl"
        assert config.audit.max_memory_entries == 50
        assert config.audit.retention_days == 14
        assert config.audit.siem_export
        assert not config.audit.include_args
        assert config.desktop.enabled
        assert not config.desktop.screenshot_on_action
        assert config.desktop.action_delay_ms == 25
        assert config.tts.enabled
        assert config.tts.provider == "piper"
        assert config.tts.voice == "en_US-lessac-medium"
        assert config.tts.speed == 1.1
        assert config.tts.output_format == "wav"
        assert config.tts.auto_speak
        assert config.tts.max_tts_chars == 300
        assert config.browser.enabled
        assert not config.browser.headless
        assert config.browser.browser_type == "firefox"
        assert config.browser.navigation_timeout == 12
        assert config.browser.max_steps_per_task == 7
        assert config.browser.allowed_domains == ["example.com"]
        assert config.google_workspace.enabled
        assert config.google_workspace.max_email_results == 4
        assert config.google_workspace.max_drive_results == 5
        assert config.google_workspace.response_body_limit == 1234
        assert config.microsoft365.enabled
        assert config.microsoft365.tenant_id == "tenant-1"
        assert config.microsoft365.max_email_results == 6
        assert config.microsoft365.max_file_results == 7
        assert config.microsoft365.default_user == "alice@example.com"
        assert config.federation.a2a_enabled
        assert not config.federation.a2a_auth_required
        assert not config.policy.parallel_tool_execution
        assert not config.memory.vector_memory
        assert config.memory.embedding_provider == "openai"
        assert config.memory.embedding_model == "text-embedding-3-small"
        assert config.memory.embedding_dimension == 1536
        assert config.memory.vector_similarity_top_k == 7
        assert config.security.output_filtering
        assert not config.security.output_pii_detection
        assert config.security.output_prompt_leak_check
        assert not config.security.canary_tokens
        assert config.security.pii_patterns == ["employee-[0-9]+"]
        assert "speak" in config.policy.allowed_tools
        assert "desktop_screenshot" in config.policy.allowed_tools
        assert "browser_navigate" in config.policy.allowed_tools
        assert "gmail_search" in config.policy.allowed_tools
        assert "outlook_search" in config.policy.allowed_tools
        assert "gmail_send" in config.policy.mutating_tools
        assert "outlook_send" in config.policy.mutating_tools
