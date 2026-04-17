from __future__ import annotations

from types import SimpleNamespace

from neuralclaw.dashboard import Dashboard
from neuralclaw.dashboard import _normalize_provider_model_catalog
from neuralclaw.providers.anthropic import AnthropicProvider


def test_normalize_provider_model_catalog_dedupes_and_marks_vision_models():
    models = _normalize_provider_model_catalog("openrouter", [
        {"id": "openai/gpt-4o", "name": "GPT-4o", "owned_by": "openai"},
        {"id": "openai/gpt-4o", "name": "GPT-4o duplicate", "owned_by": "openai"},
        {"id": "meta/llama-3.1-8b", "name": "Llama 3.1 8B", "owned_by": "meta"},
    ])

    assert [model["id"] for model in models] == ["openai/gpt-4o", "meta/llama-3.1-8b"]
    assert models[0]["supports_vision"] is True
    assert models[1]["supports_documents"] is True


def test_anthropic_provider_converts_openai_image_url_blocks():
    provider = AnthropicProvider(api_key="test-key")

    converted = provider._convert_content_blocks([
        {"type": "text", "text": "Describe this"},
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64,ZmFrZQ==",
                "detail": "high",
            },
        },
    ])

    assert converted[0] == {"type": "text", "text": "Describe this"}
    assert converted[1]["type"] == "image"
    assert converted[1]["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": "ZmFrZQ==",
    }


def test_dashboard_authorizes_loopback_requests_without_token():
    dashboard = Dashboard()
    request = SimpleNamespace(
        remote="127.0.0.1",
        headers={},
        transport=None,
    )

    assert dashboard._request_is_authorized(request) is True


def test_dashboard_requires_token_for_non_local_requests():
    dashboard = Dashboard(host="0.0.0.0", auth_token="top-secret")
    request = SimpleNamespace(
        remote="203.0.113.10",
        headers={"Authorization": "Bearer top-secret"},
        transport=None,
    )

    assert dashboard._request_is_authorized(request) is True
    request.headers["Authorization"] = "Bearer wrong"
    assert dashboard._request_is_authorized(request) is False
