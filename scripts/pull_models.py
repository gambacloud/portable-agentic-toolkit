"""
Pull Ollama models defined in config/agents.yaml (or a specific model via --model).

Usage:
    uv run python scripts/pull_models.py               # pull all defaults
    uv run python scripts/pull_models.py --model phi3  # pull one
    uv run python scripts/pull_models.py --list        # show what's installed
"""
import argparse
import sys
from pathlib import Path

import ollama
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config" / "agents.yaml"


def main():
    parser = argparse.ArgumentParser(description="Manage Ollama models")
    parser.add_argument("--model", help="Pull a specific model by name")
    parser.add_argument("--list", action="store_true", help="List installed models")
    args = parser.parse_args()

    if args.list:
        _list_models()
        return

    if args.model:
        _pull(args.model)
    else:
        _pull_defaults()


def _pull(model_name: str):
    print(f"Pulling '{model_name}' …")
    try:
        for progress in ollama.pull(model_name, stream=True):
            status = getattr(progress, "status", "")
            completed = getattr(progress, "completed", None)
            total = getattr(progress, "total", None)
            if total and completed:
                pct = int(100 * completed / total)
                print(f"\r  {status} {pct}%", end="", flush=True)
            else:
                print(f"\r  {status}", end="", flush=True)
        print(f"\n  Done: {model_name}")
    except Exception as exc:
        print(f"\n  ERROR pulling {model_name}: {exc}", file=sys.stderr)


def _pull_defaults():
    models = _default_models()
    if not models:
        print("No default models configured in config/agents.yaml.")
        return
    for m in models:
        _pull(m)


def _default_models() -> list[str]:
    if not CONFIG_PATH.exists():
        return ["llama3.2"]
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data.get("default_models", ["llama3.2"])
    except Exception:
        return ["llama3.2"]


def _list_models():
    try:
        resp = ollama.list()
        models = resp.models or []
        if not models:
            print("No models installed. Run: ollama pull llama3.2")
            return
        print(f"Installed models ({len(models)}):")
        for m in models:
            size_gb = (getattr(m, "size", 0) or 0) / 1e9
            print(f"  {m.model:<35} {size_gb:.1f} GB")
    except Exception as exc:
        print(f"Could not reach Ollama: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
