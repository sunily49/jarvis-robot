"""Tests for OllamaService — HTTP-based LLM service (mocked requests)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "server"))


@pytest.fixture
def ollama():
    from services.ollama_service import OllamaService
    return OllamaService()


def test_generate_success(ollama):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"response": "Hello, I am Mistral."}

    with patch("services.ollama_service.requests.post", return_value=mock_resp):
        result = ollama.generate("Say hello", system="Be brief")
    assert result == "Hello, I am Mistral."


def test_generate_connection_error(ollama):
    import requests
    with patch("services.ollama_service.requests.post", side_effect=requests.ConnectionError()):
        result = ollama.generate("Hello")
    assert result == ""


def test_generate_timeout(ollama):
    import requests
    with patch("services.ollama_service.requests.post", side_effect=requests.Timeout()):
        result = ollama.generate("Hello")
    assert result == ""


def test_generate_no_response_key(ollama):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {}

    with patch("services.ollama_service.requests.post", return_value=mock_resp):
        result = ollama.generate("Hello")
    assert result == ""


def test_is_available_true(ollama):
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("services.ollama_service.requests.get", return_value=mock_resp):
        assert ollama.is_available() is True


def test_is_available_false_status(ollama):
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("services.ollama_service.requests.get", return_value=mock_resp):
        assert ollama.is_available() is False


def test_is_available_connection_error(ollama):
    import requests
    with patch("services.ollama_service.requests.get", side_effect=requests.ConnectionError()):
        assert ollama.is_available() is False


def test_generate_sends_correct_payload(ollama):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"response": "ok"}

    with patch("services.ollama_service.requests.post", return_value=mock_resp) as mock_post:
        ollama.generate("test prompt", system="test system")

    call_kwargs = mock_post.call_args
    payload = call_kwargs[1]["json"]
    assert payload["prompt"] == "test prompt"
    assert payload["system"] == "test system"
    assert payload["stream"] is False


def test_generate_without_system(ollama):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"response": "response without system"}

    with patch("services.ollama_service.requests.post", return_value=mock_resp) as mock_post:
        result = ollama.generate("hello")

    call_kwargs = mock_post.call_args
    payload = call_kwargs[1]["json"]
    assert "system" not in payload or payload.get("system") == ""
    assert result == "response without system"
