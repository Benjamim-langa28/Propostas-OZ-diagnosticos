import json
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings


def require_supabase() -> tuple[str, str]:
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise HTTPException(503, "Configura SUPABASE_URL e SUPABASE_PUBLISHABLE_KEY no .env da API.")
    return settings.supabase_url.rstrip("/"), settings.supabase_publishable_key


def headers_for(token: str, prefer: str | None = None) -> dict[str, str]:
    _, key = require_supabase()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


async def rest(
    token: str,
    path: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    body: Any = None,
    prefer: str | None = None,
) -> Any:
    base, _ = require_supabase()
    url = f"{base}/rest/v1/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            method,
            url,
            params=params,
            headers=headers_for(token, prefer),
            content=json.dumps(body, default=str) if body is not None else None,
        )
    if response.is_error:
        if response.status_code in (401, 403):
            raise HTTPException(response.status_code, "O Supabase recusou o acesso a este registo.")
        try:
            detail: Any = response.json().get("message") or response.json().get("hint") or response.text
        except ValueError:
            detail = response.text
        raise HTTPException(502, f"Supabase rejeitou a operação: {detail}")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


async def verify_access_token(token: str) -> dict[str, Any]:
    base, _ = require_supabase()
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{base}/auth/v1/user", headers=headers_for(token))
    if response.status_code in (401, 403):
        raise HTTPException(401, "A sessão expirou. Inicia sessão novamente.")
    if response.is_error:
        raise HTTPException(502, "Não foi possível validar a sessão no Supabase.")
    return response.json()
