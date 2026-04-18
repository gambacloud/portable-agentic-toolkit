"""Helpers for detecting and interacting with the local Ollama service."""
import httpx
import ollama


OLLAMA_BASE_URL = "http://localhost:11434"


def is_ollama_running() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def list_model_names() -> list[str]:
    """Return sorted list of installed model names, or [] if Ollama is down."""
    try:
        resp = ollama.list()
        return sorted(m.model for m in (resp.models or []))
    except Exception:
        return []


def model_exists(name: str) -> bool:
    return name in list_model_names()
