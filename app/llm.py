"""Phase 6: the language model that writes answers.

Locally this is Llama 3.1 8B through Ollama (free, runs on the Mac). Cloudflare
Workers AI hosts the same model (@cf/meta/llama-3.1-8b-instruct), so the
deployed app can switch providers without changing the prompts or the
evaluation. The Workers AI provider is added at deployment (Phase 8).
"""

import json
import os
import re

import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("LLM_MODEL", "llama3.1:8b")


def chat(messages: list[dict], max_tokens: int = 700, json_mode: bool = True) -> str:
    body = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": 8192},
    }
    if json_mode:
        body["format"] = "json"  # Ollama constrains the output to valid JSON
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=180)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def parse_json(text: str) -> dict:
    """Parse a JSON object, tolerating stray text around it."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group(0))
        raise
