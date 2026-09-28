from __future__ import annotations

import re
import mimetypes
from uuid import uuid4
from pathlib import PurePath
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.auth import CurrentUser, current_user
from app.documents import MAX_UPLOAD_BYTES, extract_upload
from app.email_intake import looks_like_email, parse_email_request
from app.storage import signed_document_url, upload_document
from app.supabase_rest import rest

router = APIRouter(prefix="/api/proposal-library", tags=["proposal library"])
BUCKET = "proposal-library"
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".txt", ".csv", ".eml"}


def _metadata(filename: str, content: str, requested_title: str) -> dict[str, Any]:
    stem = PurePath(filename).stem.strip()
    first_line = next((line.strip(" #\t") for line in content.splitlines() if line.strip()), "")
    title = requested_title.strip() or (first_line[:180] if 3 <= len(first_line) <= 180 else stem)
    email_fields = parse_email_request(content) if looks_like_email(content) else {}
    client_match = re.search(r"(?:cliente|empresa|client|company)\s*:\s*([^\n|]{2,160})", content, re.I)
    location_match = re.search(r"(?:localização|localizacao|morada da obra|local)\s*:\s*([^\n|]{2,160})", content, re.I)
    project_type = (email_fields.get("categories") or [None])[0]
    proposal_no_match = re.search(r"\b(?:OZ[-\s]?)?\d{4}[-/]\d{3,6}\b", content, re.I)
    return {
        "title": title[:180],
        "client_name": email_fields.get("client_name") or (client_match.group(1).strip() if client_match else None),
        "project_type": project_type,
        "location": email_fields.get("location") or (location_match.group(1).strip() if location_match else None),
        "proposal_no": proposal_no_match.group(0).strip() if proposal_no_match else None,
        "summary": " ".join(content.split())[:1000],
        "tags": email_fields.get("categories") or [],
    }


@router.get("")
async def search_proposal_library(
    query: str = Query(default="", max_length=300),
    limit: int = Query(default=20, ge=1, le=20),
    user: CurrentUser = Depends(current_user),
) -> list[dict[str, Any]]:
    result = await rest(user.token, "rpc/search_proposal_references", method="POST", body={
        "p_query": query.strip(), "p_limit": limit,
    })
    return result or []


@router.post("")
async def upload_proposal_reference(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    user: CurrentUser = Depends(current_user),
) -> dict[str, Any]:
    filename = PurePath(file.filename or "proposta").name
    suffix = PurePath(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "Formato não suportado. Usa PDF, DOCX, XLSX, TXT, CSV ou EML.")
    extracted_text = await extract_upload(file)
    await file.seek(0)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "O ficheiro excede o limite de 15 MB.")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[:180] or "proposta"
    object_path = f"{user.id}/{uuid4()}-{safe_name}"
    mime_type = {
        ".eml": "message/rfc822", ".txt": "text/plain", ".csv": "text/csv",
    }.get(suffix) or file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    try:
        await upload_document(user.token, object_path, data, mime_type, bucket=BUCKET)
        rows = await rest(user.token, "proposal_library", method="POST", body={
            "owner_id": user.id,
            "file_name": filename,
            "mime_type": mime_type,
            "storage_path": object_path,
            "extracted_text": extracted_text,
            **_metadata(filename, extracted_text, title),
        }, prefer="return=representation")
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Não foi possível guardar esta proposta na biblioteca privada.") from exc
    return rows[0]


@router.get("/{record_id}/download")
async def download_proposal_reference(record_id: str,
                                     user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    rows = await rest(user.token, "proposal_library", params={
        "id": f"eq.{record_id}", "select": "storage_path", "limit": "1",
    })
    if not rows:
        raise HTTPException(404, "Esta referência não foi encontrada na tua biblioteca.")
    return {"url": await signed_document_url(user.token, rows[0]["storage_path"], bucket=BUCKET)}
