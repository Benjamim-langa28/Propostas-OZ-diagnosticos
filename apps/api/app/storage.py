from urllib.parse import quote

import httpx
from fastapi import HTTPException

from app.supabase_rest import headers_for, require_supabase

BUCKET = "proposal-documents"


async def upload_document(token: str, object_path: str, data: bytes, content_type: str) -> None:
    base, _ = require_supabase()
    url = f"{base}/storage/v1/object/{BUCKET}/{quote(object_path, safe='/')}"
    headers = headers_for(token)
    headers["Content-Type"] = content_type
    headers["x-upsert"] = "true"
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(url, headers=headers, content=data)
    if response.is_error:
        raise HTTPException(502, "O pedido foi guardado, mas o anexo original não ficou disponível para transferência.")


async def signed_document_url(token: str, object_path: str, expires_in: int = 3600) -> str:
    base, _ = require_supabase()
    url = f"{base}/storage/v1/object/sign/{BUCKET}/{quote(object_path, safe='/')}"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, headers=headers_for(token), json={"expiresIn": expires_in})
    if response.is_error:
        raise HTTPException(502, "Não foi possível criar uma ligação temporária para o anexo.")
    signed = response.json().get("signedURL")
    if not signed:
        raise HTTPException(502, "O armazenamento não devolveu uma ligação de transferência.")
    return signed if signed.startswith("http") else f"{base}/storage/v1{signed}"
