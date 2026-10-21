from __future__ import annotations

import asyncio
import difflib
import logging
import re
import mimetypes
import unicodedata
from uuid import uuid4
from pathlib import PurePath
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.auth import CurrentUser, current_user
from app.documents import MAX_UPLOAD_BYTES, extract_upload
from app.email_intake import looks_like_email, parse_email_request
from app.services.material_guard import detect_materials, request_text
from app.services.proposal_reader import get_reading, read_and_store, reprocess_one, reprocess_pending
from app.storage import delete_document, signed_document_url, upload_document
from app.supabase_rest import rest

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/api/proposal-library", tags=["proposal library"])
BUCKET = "proposal-library"
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".txt", ".csv", ".eml"}
STOP_WORDS = {
    "com", "para", "por", "uma", "uns", "das", "dos", "que", "nas", "nos", "mais",
    "sobre", "entre", "pelo", "pela", "este", "esta", "ser", "sua", "seu", "the",
    "and", "for", "from", "with", "this", "that", "servico", "servicos", "proposta",
    "propostas", "pedido", "pedidos", "cliente", "empresa", "obra", "projeto",
}
TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def _metadata(filename: str, content: str, requested_title: str) -> dict[str, Any]:
    """Metadados por regras (ficam como reserva se a leitura com IA falhar)."""
    stem = PurePath(filename).stem.strip()
    flat = " ".join(content.split())
    email_fields = parse_email_request(content) if looks_like_email(content) else {}

    number = re.search(r"Proposta\s*N[ºo°]\.?\s*:?\s*(\d{1,4}\s*/\s*\d{2}(?:\s*-\s*\d{2})?)", flat, re.I)
    if number:
        proposal_no = re.sub(r"\s+", "", number.group(1))
    else:
        alt = re.search(r"\bOZ[-\s]\d{4}[-/]\d{3,6}\b", flat, re.I)
        proposal_no = alt.group(0).strip() if alt else None

    subject = re.search(r"V\.?\s*solicitação\s*:\s*[“\"]([^”\"]{5,220})[”\"]", flat, re.I)
    service = re.search(r"Proposta de prestação de serviços de ([^.]{10,220})", flat, re.I)
    first_line = next((line.strip(" #\t") for line in content.splitlines()
                       if len(line.strip()) >= 4 and line.strip().lower() not in {"e-mail", "email"}
                       and not line.strip().lower().startswith("escritório")), "")
    title = (requested_title.strip() or (subject.group(1).strip() if subject else "")
             or (service.group(1).strip() if service else "")
             or (first_line[:180] if 3 <= len(first_line) <= 180 else stem))

    para = re.search(r"Para\s*\(To\)\s*:\s*(.{2,100}?)\s+(?:Tel\.|À\s*At\.)", flat, re.I)
    client_match = re.search(r"(?:cliente|empresa|client|company)\s*:\s*([^\n|]{2,160})", content, re.I)
    location_match = re.search(r"(?:localização|localizacao|morada da obra)\s*:\s*([^\n|]{2,160})", content, re.I)
    client_name = ((para.group(1).strip() if para else None) or email_fields.get("client_name")
                   or (client_match.group(1).strip() if client_match else None))

    body = flat.split("1. Objeto", 1)[1] if "1. Objeto" in flat else flat
    project_type = (email_fields.get("categories") or [None])[0]
    return {
        "title": title[:180],
        "client_name": client_name,
        "project_type": project_type,
        "location": email_fields.get("location") or (location_match.group(1).strip() if location_match else None),
        "proposal_no": proposal_no,
        "summary": body.strip()[:1000],
        "tags": email_fields.get("categories") or [],
    }


@router.get("")
async def search_proposal_library(
    query: str = Query(default="", max_length=300),
    limit: int = Query(default=100, ge=1, le=500),
    user: CurrentUser = Depends(current_user),
) -> list[dict[str, Any]]:
    result = await rest(user.token, "rpc/list_proposal_library", method="POST", body={
        "p_query": query.strip(), "p_limit": limit,
    })
    return result or []


def _tokens(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(item) for item in value if item)
    folded = unicodedata.normalize("NFKD", str(value or "").casefold())
    plain = "".join(char for char in folded if not unicodedata.combining(char))
    return list(dict.fromkeys(token for token in TOKEN_RE.findall(plain) if token not in STOP_WORDS))


def _fuzzy_token_f1(left: list[str], right: list[str]) -> float:
    """Greedily pair similar words once, then return a precision/recall F1 score."""
    if not left or not right:
        return 0.0
    possible = sorted(
        (
            difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(),
            left_index,
            right_index,
        )
        for left_index, a in enumerate(left)
        for right_index, b in enumerate(right)
        if difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.72
    )
    relevant_right = {right_index for _, _, right_index in possible}
    if not relevant_right:
        return 0.0
    used_left: set[int] = set()
    used_right: set[int] = set()
    similarity_sum = 0.0
    for similarity, left_index, right_index in reversed(possible):
        if left_index in used_left or right_index in used_right:
            continue
        used_left.add(left_index)
        used_right.add(right_index)
        similarity_sum += similarity
    precision = similarity_sum / len(relevant_right)
    recall = similarity_sum / len(left)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _text(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item) for item in value if item)
    return str(value or "")


DUPLICATE_THRESHOLD = 0.85
MAX_REFERENCES = 5


def _reference_signature(candidate: dict[str, Any]) -> set[str]:
    return set(_tokens(" ".join((str(candidate.get("title") or ""), str(candidate.get("summary") or "")))))


def _dedupe_similar_references(scored: list[dict[str, Any]], limit: int = MAX_REFERENCES) -> list[dict[str, Any]]:
    """Agrupa propostas praticamente idênticas para não contarem como evidências independentes.

    Recebe a lista já ordenada (melhor primeiro). Mantém a melhor de cada grupo e regista
    em `duplicates_hidden` quantas cópias quase iguais ficaram agrupadas nela.
    """
    kept: list[dict[str, Any]] = []
    signatures: list[set[str]] = []
    for candidate in scored:
        signature = _reference_signature(candidate)
        group = None
        for index, other in enumerate(signatures):
            union = signature | other
            same_request = bool(candidate.get("request_id")) and candidate.get("request_id") == kept[index].get("request_id")
            if same_request or (union and len(signature & other) / len(union) >= DUPLICATE_THRESHOLD):
                group = kept[index]
                break
        if group is not None:
            group["duplicates_hidden"] = int(group.get("duplicates_hidden") or 0) + 1
            continue
        candidate["duplicates_hidden"] = 0
        kept.append(candidate)
        signatures.append(signature)
    return kept[:limit]


def _label_compatible(request_materials: set[str], label: Any) -> bool:
    """Compara o material do pedido com o material lido na proposta carregada."""
    value = str(label or "").strip().lower()
    if not request_materials or value in {"", "desconhecido", "outro", "misto"}:
        return True
    if "madeira" in request_materials and "betao" not in request_materials:
        return value == "madeira"
    if "madeira" in request_materials:
        return True
    return value != "madeira"


@router.get("/matches")
async def match_request_to_prior_proposals(
    request_id: str = Query(min_length=1, max_length=80),
    user: CurrentUser = Depends(current_user),
) -> list[dict[str, Any]]:
    """Find prior generated/uploaded proposals and score their textual similarity."""
    requests = await rest(user.token, "proposal_requests", params={
        "id": f"eq.{request_id}",
        "select": "id,title,raw_text,extracted_fields",
        "limit": "1",
    })
    if not requests:
        return []
    request = requests[0]
    extracted = request.get("extracted_fields") or {}
    scope_text = " ".join((
        _text(extracted.get("requested_services")),
        _text(extracted.get("categories")),
    )).strip()
    objective_text = " ".join((
        _text(extracted.get("objective")),
        _text(request.get("title")),
    )).strip()
    location_text = _text(extracted.get("location"))
    scope_tokens = _tokens(scope_text)
    objective_tokens = _tokens(objective_text)
    location_tokens = _tokens(location_text)

    # Search independently by meaningful technical terms to avoid an AND query
    # hiding a good candidate just because one phrase was worded differently.
    search_terms = list(dict.fromkeys(scope_tokens + objective_tokens))[:12]
    if not search_terms:
        return []
    result_sets = await asyncio.gather(*(
        rest(user.token, "rpc/search_proposal_references", method="POST", body={
            "p_query": term, "p_limit": 20,
        })
        for term in search_terms
    ))
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for rows in result_sets:
        for row in rows or []:
            key = (str(row.get("source", "")), str(row.get("id", "")))
            if key[1] and row.get("request_id") != request_id:
                candidates[key] = row

    # Material: ignora propostas carregadas cujo material (lido com IA) não é compatível com o pedido.
    uploaded_ids = [key[1] for key in candidates if key[0] == "uploaded"]
    if uploaded_ids:
        try:
            material_rows = await rest(user.token, "proposal_library", params={
                "id": "in.(" + ",".join(uploaded_ids) + ")", "select": "id,material", "limit": "500"})
        except Exception:
            material_rows = []  # a coluna ainda não existe: não filtra
        labels = {str(r["id"]): r.get("material") for r in (material_rows if isinstance(material_rows, list) else [])}
        request_materials = detect_materials(request_text(extracted, request.get("raw_text")))
        for key in [k for k in candidates if k[0] == "uploaded"]:
            if not _label_compatible(request_materials, labels.get(key[1])):
                del candidates[key]

    scored: list[dict[str, Any]] = []
    for candidate in candidates.values():
        candidate_scope = _tokens(" ".join((
            str(candidate.get("title") or ""),
            str(candidate.get("summary") or ""),
        )))
        candidate_objective = _tokens(str(candidate.get("summary") or ""))
        candidate_location = _tokens(str(candidate.get("location") or ""))
        components: dict[str, int] = {}
        weighted_score = 0.0
        active_weight = 0.0
        for key, left, right, weight in (
            ("scope", scope_tokens, candidate_scope, 0.60),
            ("objective", objective_tokens, candidate_objective, 0.30),
            ("location", location_tokens, candidate_location, 0.10),
        ):
            if left and right:
                score = _fuzzy_token_f1(left, right)
                components[key] = round(score * 100)
                weighted_score += weight * score
                active_weight += weight
        if not active_weight:
            continue
        percent = round(100 * weighted_score / active_weight)
        if percent < 18 or components.get("scope", 0) < 12:
            continue
        candidate["match_percent"] = percent
        candidate["match_components"] = components
        scored.append(candidate)
    ordered = sorted(
        scored,
        key=lambda row: (row["match_percent"], row.get("created_at", "")),
        reverse=True,
    )
    return _dedupe_similar_references(ordered)


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
    record = rows[0]
    # Leitura com IA no momento do carregamento (metadados e mapa de preços).
    try:
        reading = await read_and_store(user.token, user.id, record["id"], extracted_text,
                                       title_is_auto=not title.strip())
    except Exception:
        logger.exception("Leitura com IA falhou para a proposta %s", record.get("id"))
        reading = {"status": "FAILED", "note": "Erro ao ler a proposta com IA.", "items": 0}
    return {**record, "extraction_status": reading["status"], "extraction_note": reading["note"],
            "extraction_items": reading["items"]}


@router.post("/reprocess")
async def reprocess_pending_readings(user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    return await reprocess_pending(user.token, user.id)


@router.post("/{record_id}/reprocess")
async def reprocess_reading(record_id: str, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    return await reprocess_one(user.token, user.id, record_id)


@router.get("/{record_id}/reading")
async def proposal_reading(record_id: str, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    data = await get_reading(user.token, record_id)
    if data is None:
        raise HTTPException(404, "Esta referência não foi encontrada na tua biblioteca.")
    return data


@router.delete("/{record_id}")
async def delete_proposal_reference(
    record_id: str,
    source: Literal["uploaded", "generated"] = Query(),
    user: CurrentUser = Depends(current_user),
) -> dict[str, Any]:
    if source == "uploaded":
        rows = await rest(user.token, "proposal_library", params={
            "id": f"eq.{record_id}", "select": "id,storage_path", "limit": "1",
        })
        if not rows:
            raise HTTPException(404, "Este ficheiro não foi encontrado na tua biblioteca.")
        if rows[0].get("storage_path"):
            await delete_document(user.token, rows[0]["storage_path"], bucket=BUCKET)
        deleted = await rest(user.token, "proposal_library", method="DELETE", params={
            "id": f"eq.{record_id}", "select": "id",
        }, prefer="return=representation")
    else:
        rows = await rest(user.token, "proposals", params={
            "id": f"eq.{record_id}", "select": "id,request_id,proposal_no", "limit": "1",
        })
        if not rows:
            raise HTTPException(404, "Esta proposta não foi encontrada no teu espaço.")
        deleted = await rest(user.token, "proposals", method="DELETE", params={
            "id": f"eq.{record_id}", "select": "id",
        }, prefer="return=representation")
    if not deleted:
        raise HTTPException(404, "O registo já não está disponível para apagar.")
    return {"deleted": True, "source": source, "id": record_id}


@router.get("/{record_id}/download")
async def download_proposal_reference(record_id: str,
                                     user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    rows = await rest(user.token, "proposal_library", params={
        "id": f"eq.{record_id}", "select": "storage_path", "limit": "1",
    })
    if not rows:
        raise HTTPException(404, "Esta referência não foi encontrada na tua biblioteca.")
    return {"url": await signed_document_url(user.token, rows[0]["storage_path"], bucket=BUCKET)}