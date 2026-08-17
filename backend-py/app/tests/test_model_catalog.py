"""Unit tests for the AI model catalog (Feature 4, metadata only).

The catalog is pure static metadata — no network, no credentials, no file I/O.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

from app.modules.ai.model_catalog import (  # noqa: E402
    MODEL_CATALOG,
    list_models,
    model_info,
    providers,
    supports,
)


def test_azure_provider_present():
    assert "azure-openai" in providers()
    assert "azure-openai" in MODEL_CATALOG


def test_azure_models_include_gpt4o_and_o_series():
    ids = {m["id"] for m in list_models("azure-openai")}
    assert "gpt-4o" in ids
    assert "gpt-4o-mini" in ids
    assert "o1" in ids


def test_azure_entries_carry_metadata_and_label():
    for m in list_models("azure-openai"):
        assert m["provider"] == "azure-openai"
        assert m["label"] == "Azure OpenAI"
        assert m["contextWindow"] > 0
        assert m["maxOutputTokens"] > 0


def test_model_info_lookup():
    info = model_info("azure-openai", "gpt-4o")
    assert info is not None
    assert info["id"] == "gpt-4o"
    assert model_info("azure-openai", "does-not-exist") is None


def test_supports_auto_detection_hint():
    assert supports("azure-openai", "gpt-4o")
    assert not supports("azure-openai", "gpt-6-nonexistent")
    assert supports("anthropic", "claude-sonnet-4-20250514")


def test_unknown_provider_returns_empty():
    assert list_models("no-such-provider") == []


def test_catalog_includes_all_registered_providers():
    ids = set(providers())
    assert {"azure-openai", "openai-compatible", "anthropic", "gemini",
            "openrouter", "glm", "lmstudio", "local-fallback"} <= ids


def test_models_are_copies_not_references():
    first = list_models("azure-openai")
    first[0]["contextWindow"] = 1
    assert list_models("azure-openai")[0]["contextWindow"] != 1
