"""Tests for config validation."""

from neuralclaw.config import (
    NeuralClawConfig,
    ProviderConfig,
    SecurityConfig,
    ChannelConfig,
    validate_config,
    ConfigValidationResult,
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
