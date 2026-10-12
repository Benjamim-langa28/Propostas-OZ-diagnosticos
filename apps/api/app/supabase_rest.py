from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings


def require_supabase() -> tuple[str, str]:
    if (
        not settings.supabase_url
        or not settings.supabase_publishable_key
    ):
        raise HTTPException(
            503,
            "Configura SUPABASE_URL e SUPABASE_PUBLISHABLE_KEY no .env da API.",
        )

    return (
        settings.supabase_url.rstrip("/"),
        settings.supabase_publishable_key,
    )


def headers_for(
    token: str,
    prefer: str | None = None,
) -> dict[str, str]:

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
    table: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    body: Any = None,
    prefer: str | None = None,
) -> Any:

    base_url, _ = require_supabase()

    path = f"/rest/v1/{table}"
    url = f"{base_url}{path}"

    headers = headers_for(
        token,
        prefer=prefer,
    )

    async with httpx.AsyncClient(
        timeout=60.0
    ) as client:

        response = await client.request(
            method,
            url,
            headers=headers,
            params=params,
            json=body,
        )

    if response.is_error:

        if response.status_code in (
            401,
            403,
        ):
            raise HTTPException(
                response.status_code,
                "O Supabase recusou o acesso a este registo.",
            )

        try:

            payload = response.json()

            if isinstance(
                payload,
                dict,
            ):

                detail: Any = (
                    payload.get("message")
                    or payload.get("hint")
                    or payload.get("details")
                    or response.text
                )

            else:

                detail = response.text

        except ValueError:

            detail = response.text

        print(
            f"[SUPABASE ERROR] "
            f"{method} {path} -> "
            f"HTTP {response.status_code} | "
            f"{detail}",
            flush=True,
        )

        raise HTTPException(
            502,
            f"Supabase rejeitou a operação: {detail}",
        )

    if not response.content:
        return None

    content_type = response.headers.get(
        "content-type",
        "",
    )

    if "application/json" in content_type:

        try:
            return response.json()

        except ValueError:
            return response.text

    return response.text


async def verify_access_token(
    token: str,
) -> dict[str, Any]:

    if not token:

        raise HTTPException(
            401,
            "Token de autenticação em falta.",
        )

    base_url, _ = require_supabase()

    url = f"{base_url}/auth/v1/user"

    headers = headers_for(token)

    async with httpx.AsyncClient(
        timeout=30.0
    ) as client:

        response = await client.get(
            url,
            headers=headers,
        )

    if response.status_code in (
        401,
        403,
    ):

        raise HTTPException(
            401,
            "Sessão inválida ou expirada.",
        )

    if response.is_error:

        try:

            payload = response.json()

            if isinstance(
                payload,
                dict,
            ):

                detail = (
                    payload.get("message")
                    or payload.get(
                        "error_description"
                    )
                    or payload.get("error")
                    or response.text
                )

            else:

                detail = response.text

        except ValueError:

            detail = response.text

        print(
            f"[SUPABASE AUTH ERROR] "
            f"GET /auth/v1/user -> "
            f"HTTP {response.status_code} | "
            f"{detail}",
            flush=True,
        )

        raise HTTPException(
            502,
            "Não foi possível validar a sessão "
            f"no Supabase: {detail}",
        )

    try:

        data = response.json()

    except ValueError:

        raise HTTPException(
            502,
            "O Supabase devolveu uma resposta "
            "inválida ao validar a sessão.",
        )

    if (
        not isinstance(data, dict)
        or not data.get("id")
    ):

        raise HTTPException(
            401,
            "Sessão inválida.",
        )

    return data