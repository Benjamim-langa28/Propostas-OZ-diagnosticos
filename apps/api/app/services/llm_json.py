"""Chamada a um modelo (Gemini ou outro compatível com a API da OpenAI) que devolve JSON.

Lê LLM_BASE_URL, LLM_API_KEY, LLM_MODEL e (opcional) LLM_FALLBACK_MODEL do .env."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("uvicorn.error")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _cfg(name: str) -> str:
    value = getattr(settings, name.lower(), None)
    if value in (None, ""):
        value = os.environ.get(name.upper())
    return str(value).strip().strip('"').strip() if value not in (None, "") else ""


def llm_settings() -> dict[str, Any] | None:
    key, base = _cfg("GEMINI_API_KEY"), _cfg("GEMINI_BASE_URL")
    model, fallback = _cfg("GEMINI_MODEL"), _cfg("GEMINI_FALLBACK_MODEL")
    if key:
        base = base or GEMINI_URL
    else:
        key = _cfg("LLM_API_KEY")
        base = base or _cfg("LLM_BASE_URL")
        model = model or _cfg("LLM_MODEL")
        fallback = fallback or _cfg("LLM_FALLBACK_MODEL")
    if not (base and model):
        return None
    models = [model] + ([fallback] if fallback and fallback != model else [])
    return {"key": key, "base": base.rstrip("/") + "/", "models": models}


def llm_available() -> bool:
    return llm_settings() is not None


def _parse_json(text: str) -> dict[str, Any] | None:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.I).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


async def ask_json(system: str, user: str, schema: dict[str, Any], name: str = "resposta",
                   timeout: float = 90.0) -> dict[str, Any] | None:
    """Devolve o JSON da resposta ou None se a IA não estiver configurada ou falhar em todos os modelos."""
    cfg = llm_settings()
    if not cfg:
        return None
    headers = {"Content-Type": "application/json"}
    if cfg["key"]:
        headers["Authorization"] = f"Bearer {cfg['key']}"
    url = cfg["base"] + "chat/completions"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for model in cfg["models"]:
                body: dict[str, Any] = {
                    "model": model, "temperature": 0,
                    "messages": [
                        {"role": "system",
                         "content": system + "\nResponde apenas com JSON válido, sem texto fora do JSON."},
                        {"role": "user", "content": user}],
                    "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
                }
                response = await client.post(url, headers=headers, json=body)
                if response.status_code in (400, 422):
                    logger.warning("LLM (%s) recusou o formato estruturado: %s", model, response.text[:300])
                    body.pop("response_format")
                    response = await client.post(url, headers=headers, json=body)
                if response.is_error:
                    logger.warning("LLM (%s) devolveu erro %s: %s", model, response.status_code, response.text[:300])
                    continue
                try:
                    content = response.json()["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError, ValueError):
                    logger.warning("LLM (%s) devolveu uma resposta sem conteúdo.", model)
                    continue
                data = _parse_json(content if isinstance(content, str) else "")
                if data is not None:
                    return data
                logger.warning("LLM (%s) devolveu algo que não é JSON válido: %s", model, str(content)[:300])
    except httpx.HTTPError:
        logger.exception("Falha ao chamar o LLM")
    return None