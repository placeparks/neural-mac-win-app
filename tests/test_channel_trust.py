from pathlib import Path

from neuralclaw.channels.protocol import ChannelMessage
from neuralclaw.channels.trust import BindingStore, ChannelTrustController
from neuralclaw.config import ChannelConfig


def _msg(content: str, *, platform: str = "telegram", chat_id: str = "123", is_private: bool = True) -> ChannelMessage:
    return ChannelMessage(
        content=content,
        author_id="user-1",
        author_name="User",
        channel_id=chat_id,
        metadata={
            "platform": platform,
            "source": platform,
            "is_private": is_private,
            "is_shared": not is_private,
        },
    )


class TestChannelTrustController:
    def test_open_mode_allows(self, tmp_path):
        ctl = ChannelTrustController(BindingStore(tmp_path / "bindings.json"))
        decision = ctl.evaluate(ChannelConfig(name="telegram", trust_mode="open"), _msg("hello"))
        assert decision.trusted

    def test_pair_mode_requires_pair_first(self, tmp_path):
        ctl = ChannelTrustController(BindingStore(tmp_path / "bindings.json"))
        decision = ctl.evaluate(ChannelConfig(name="telegram", trust_mode="pair"), _msg("hello"))
        assert decision.status == "unpaired"
        assert "/pair" in (decision.response or "")

    def test_pair_command_binds_route(self, tmp_path):
        store = BindingStore(tmp_path / "bindings.json")
        ctl = ChannelTrustController(store)
        pair = ctl.evaluate(ChannelConfig(name="telegram", trust_mode="pair"), _msg("/pair"))
        assert pair.status == "paired"
        trusted = ctl.evaluate(ChannelConfig(name="telegram", trust_mode="pair"), _msg("hello"))
        assert trusted.trusted
        assert len(store.list_bindings()) == 1

    def test_bound_mode_denies_without_binding(self, tmp_path):
        ctl = ChannelTrustController(BindingStore(tmp_path / "bindings.json"))
        decision = ctl.evaluate(ChannelConfig(name="discord", trust_mode="bound"), _msg("hello", platform="discord", is_private=False))
        assert decision.status == "denied"


def test_telegram_adapter_registers_pair_command():
    source = Path("neuralclaw/channels/telegram.py").read_text(encoding="utf-8")
    assert 'CommandHandler("pair", handle_message)' in source
