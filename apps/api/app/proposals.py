import html
import json
import re
import asyncio
import mimetypes
import base64
from pathlib import PurePath
from datetime import date
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from app.auth import CurrentUser, current_user
from app.config import settings
from app.documents import extract_mqt_rows, extract_upload
from app.proposal_pdf import build_proposal_pdf
from app.supabase_rest import rest
from app.storage import signed_document_url, upload_document

router = APIRouter(prefix="/api", tags=["proposals"])

STATUSES = {
    "DRAFT", "ANALYSING", "NEEDS_INFORMATION", "TECHNICAL_SCOPE", "PRICING",
    "TECHNICAL_REVIEW", "READY_FOR_APPROVAL", "APPROVED", "GENERATED", "SENT",
    "CLIENT_REVIEW", "ACCEPTED", "REJECTED", "EXPIRED",
}

ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "client_name": {"type": ["string", "null"]},
        "client_email": {"type": ["string", "null"]},
        "project_name": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "construction_year": {"type": ["integer", "null"]},
        "basement_count": {"type": ["integer", "null"]},
        "objective": {"type": ["string", "null"]},
        "deadline": {"type": ["string", "null"]},
        "categories": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "missing_information": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "client_name", "client_email", "project_name", "location", "construction_year",
        "basement_count", "objective", "deadline", "categories", "constraints",
        "missing_information",
    ],
}


class StatusChange(BaseModel):
    status: str


class ItemCreate(BaseModel):
    service_id: str
    quantity: float = Field(default=1, ge=0)


class ItemUpdate(BaseModel):
    quantity: float | None = Field(default=None, ge=0)
    unit_price: float | None = Field(default=None, ge=0)
    enabled: bool | None = None
    name: str | None = Field(default=None, max_length=400)


class EmailRequest(BaseModel):
    to: str | None = None
    subject: str | None = Field(default=None, max_length=300)
    message: str = Field(default="", max_length=5000)


class FieldsUpdate(BaseModel):
    fields: dict[str, Any]


class VisitCreate(BaseModel):
    scheduled_at: datetime
    note: str = Field(default="", max_length=1000)


class VisitStatusUpdate(BaseModel):
    status: str


def fallback_analysis(text: str, fields: dict[str, Any]) -> dict[str, Any]:
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    email = fields.get("client_email") or (email_match.group(0) if email_match else None)
    categories = []
    lowered = text.lower()
    for words, category in [
        (("fissur", "rachad", "rache"), "Patologia / fissuração"),
        (("betão", "concreto", "carote", "carbonatação", "cloreto"), "Ensaios de betão"),
        (("humidade", "infiltração", "água"), "Humidade / infiltração"),
        (("monitor", "fissurómetro"), "Monitorização"),
        (("inspeção", "vistoria", "diagnóstico"), "Inspeção / diagnóstico"),
    ]:
        if any(word in lowered for word in words):
            categories.append(category)
    result: dict[str, Any] = {
        "client_name": fields.get("client_name") or None,
        "client_email": email,
        "project_name": fields.get("project_name") or None,
        "location": fields.get("location") or None,
        "construction_year": None,
        "basement_count": None,
        "objective": text.strip()[:600] or None,
        "deadline": fields.get("deadline") or None,
        "categories": categories,
        "constraints": [],
    }
    missing = []
    for key, label in [("client_name", "Nome do cliente"), ("client_email", "Email do cliente"),
                       ("project_name", "Nome da obra"), ("location", "Localização")]:
        if not result.get(key):
            missing.append(label)
    result["missing_information"] = missing
    return result


async def analyze_with_openai(text: str) -> tuple[dict[str, Any], str | None]:
    if not settings.openai_api_key:
        return {}, None
    payload = {
        "model": settings.openai_model,
        "input": [{
            "role": "user",
            "content": [{
                "type": "input_text",
                "text": (
                    "Extrai os dados de um pedido para proposta de diagnóstico de engenharia. "
                    "Não inventes factos: usa null quando não houver evidência. Mantém o idioma "
                    "original e assinala dados em falta. Texto do pedido:\n\n" + text[:50000]
                ),
            }],
        }],
        "text": {"format": {"type": "json_schema", "name": "oz_request_analysis", "strict": True,
                              "schema": ANALYSIS_SCHEMA}},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=payload,
            )
        response.raise_for_status()
        data = response.json()
        for output in data.get("output", []):
            for item in output.get("content", []):
                if item.get("type") == "output_text":
                    return json.loads(item["text"]), None
        return {}, "A OpenAI não devolveu uma análise estruturada."
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        return {}, "A análise OpenAI falhou; foram usados campos básicos."


async def create_client(token: str, owner_id: str, name: str | None, email: str | None) -> str | None:
    if not name:
        return None
    found = []
    if email:
        found = await rest(token, "clients", params={
            "select": "id", "owner_id": f"eq.{owner_id}", "email": f"eq.{email}", "limit": "1",
        })
    if found:
        rows = await rest(token, "clients", method="PATCH", params={"id": f"eq.{found[0]['id']}"},
                          body={"name": name}, prefer="return=representation")
        return rows[0]["id"]
    rows = await rest(token, "clients", method="POST", body={"owner_id": owner_id, "name": name, "email": email},
                      prefer="return=representation")
    return rows[0]["id"]


async def mark_pricing(token: str, proposal_id: str) -> None:
    proposals = await rest(token, "proposals", params={"id": f"eq.{proposal_id}", "select": "id,request_id", "limit": "1"})
    if not proposals:
        return
    request_id = proposals[0]["request_id"]
    await rest(token, "proposals", method="PATCH", params={"id": f"eq.{proposal_id}"},
               body={"status": "PRICING"}, prefer="return=minimal")
    await rest(token, "proposal_requests", method="PATCH", params={"id": f"eq.{request_id}"},
               body={"status": "PRICING"}, prefer="return=minimal")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "oz-proposals-api"}


@router.get("/proposals")
async def list_requests(user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    return await rest(user.token, "proposal_requests", params={
        "select": "*", "order": "created_at.desc", "limit": "250",
    })


@router.post("/proposals/analyze")
async def analyze_request(
    raw_text: str = Form(default=""),
    client_name: str = Form(default=""),
    client_email: str = Form(default=""),
    project_name: str = Form(default=""),
    location: str = Form(default=""),
    deadline: str = Form(default=""),
    file: UploadFile | None = File(default=None),
    user: CurrentUser = Depends(current_user),
) -> dict[str, Any]:
    extracted_text = await extract_upload(file) if file else ""
    file_bytes = b""
    if file:
        await file.seek(0)
        file_bytes = await file.read()
    mqt_rows = extract_mqt_rows(file.filename or "", file_bytes) if file else []
    content = "\n\n".join(part for part in [raw_text.strip(), extracted_text.strip()] if part)
    if not content:
        raise HTTPException(422, "Cola o email do cliente ou anexa um documento.")
    if len(content) > 60000:
        content = content[:60000]
    fields = {"client_name": client_name.strip(), "client_email": client_email.strip(),
              "project_name": project_name.strip(), "location": location.strip(),
              "deadline": deadline.strip()}
    analysis, analysis_error = await analyze_with_openai(content)
    result = fallback_analysis(content, fields)
    mode = "RULES"
    if analysis:
        result.update({key: value for key, value in analysis.items() if value is not None})
        mode = "OPENAI"
    for key, value in fields.items():
        if value:
            result[key] = value
    missing = list(result.get("missing_information") or [])
    for key, label in [("client_name", "Nome do cliente"), ("client_email", "Email do cliente"),
                       ("project_name", "Nome da obra"), ("location", "Localização")]:
        if result.get(key):
            missing = [item for item in missing if label.casefold() not in str(item).casefold()]
        elif not any(label.casefold() in str(item).casefold() for item in missing):
            missing.append(label)
    result["missing_information"] = missing
    if result.get("deadline"):
        try:
            date.fromisoformat(result["deadline"][:10])
        except (TypeError, ValueError):
            result["deadline"] = None

    client_id = await create_client(user.token, user.id, result.get("client_name"), result.get("client_email"))
    project_id = None
    project_name_value = result.get("project_name")
    if project_name_value:
        projects = await rest(user.token, "projects", method="POST", body={
            "owner_id": user.id, "client_id": client_id, "name": project_name_value,
            "location": result.get("location"), "year_built": result.get("construction_year"),
        }, prefer="return=representation")
        project_id = projects[0]["id"]

    title = project_name_value or result.get("client_name") or "Novo pedido de proposta"
    status = "NEEDS_INFORMATION" if result.get("missing_information") else "DRAFT"
    request_rows = await rest(user.token, "proposal_requests", method="POST", body={
        "owner_id": user.id, "client_id": client_id, "project_id": project_id,
        "title": title[:300], "source": "upload" if file else "email", "raw_text": content,
        "extracted_fields": result, "deadline": result.get("deadline"), "status": status,
    }, prefer="return=representation")
    request_row = request_rows[0]
    analysis_rows = await rest(user.token, "proposal_analysis", method="POST", body={
        "owner_id": user.id, "request_id": request_row["id"], "categories": result.get("categories", []),
        "extracted": result, "missing_information": result.get("missing_information", []),
        "restrictions": result.get("constraints", []), "analysis_mode": mode,
    }, prefer="return=representation")
    if mqt_rows:
        await rest(user.token, "mqt_items", method="POST", body=[{
            "owner_id": user.id, "request_id": request_row["id"], **row,
            "origin": "REQUIRES_REVIEW",
        } for row in mqt_rows], prefer="return=minimal")
    storage_error = None
    if file:
        filename = PurePath(file.filename or "anexo").name
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename)[:180] or "anexo"
        object_path = f"{user.id}/{request_row['id']}/{safe_name}"
        mime_by_extension = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".txt": "text/plain", ".csv": "text/csv", ".eml": "message/rfc822",
        }
        mime_type = mime_by_extension.get(PurePath(safe_name).suffix.lower()) or file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        documents = await rest(user.token, "documents", method="POST", body={
            "owner_id": user.id, "request_id": request_row["id"],
            "file_name": filename, "mime_type": mime_type,
            "extracted_text": extracted_text,
        }, prefer="return=representation")
        try:
            await upload_document(user.token, object_path, file_bytes, mime_type)
            await rest(user.token, "documents", method="PATCH", params={"id": f"eq.{documents[0]['id']}"},
                       body={"storage_path": object_path}, prefer="return=minimal")
        except HTTPException as exc:
            storage_error = str(exc.detail)
        except httpx.HTTPError:
            storage_error = "O pedido foi guardado, mas a ligação ao armazenamento falhou."
    return {"request": request_row, "analysis": analysis_rows[0], "analysis_error": analysis_error,
            "storage_error": storage_error}


@router.get("/proposals/{request_id}")
async def get_request(request_id: str, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    rows = await rest(user.token, "proposal_requests", params={"id": f"eq.{request_id}", "select": "*", "limit": "1"})
    if not rows:
        raise HTTPException(404, "Pedido não encontrado.")
    request_row = rows[0]
    analyses, proposals, documents, visits, mqt_items = await asyncio.gather(
        rest(user.token, "proposal_analysis", params={"request_id": f"eq.{request_id}", "limit": "1"}),
        rest(user.token, "proposals", params={"request_id": f"eq.{request_id}", "limit": "1"}),
        rest(user.token, "documents", params={"request_id": f"eq.{request_id}",
                                               "select": "id,file_name,mime_type,storage_path,created_at",
                                               "order": "created_at.desc"}),
        rest(user.token, "visits", params={"request_id": f"eq.{request_id}", "order": "scheduled_at.asc"}),
        rest(user.token, "mqt_items", params={"request_id": f"eq.{request_id}", "order": "created_at.asc"}),
    )
    proposal = proposals[0] if proposals else None
    items = []
    if proposal:
        items = await rest(user.token, "proposal_items", params={
            "proposal_id": f"eq.{proposal['id']}", "order": "position.asc,created_at.asc",
        })
    return {"request": request_row, "analysis": analyses[0] if analyses else None,
            "proposal": proposal, "items": items, "documents": documents, "visits": visits,
            "mqt_items": mqt_items}


@router.get("/documents/{document_id}/download")
async def download_document(document_id: str,
                           user: CurrentUser = Depends(current_user)) -> dict[str, str]:
    rows = await rest(user.token, "documents", params={"id": f"eq.{document_id}",
                                                        "select": "storage_path", "limit": "1"})
    if not rows or not rows[0].get("storage_path"):
        raise HTTPException(404, "O ficheiro original não está disponível.")
    return {"url": await signed_document_url(user.token, rows[0]["storage_path"])}


@router.get("/proposals/{request_id}/pdf")
async def download_proposal_pdf(request_id: str, user: CurrentUser = Depends(current_user)) -> Response:
    request_rows = await rest(user.token, "proposal_requests", params={"id": f"eq.{request_id}", "limit": "1"})
    proposals = await rest(user.token, "proposals", params={"request_id": f"eq.{request_id}", "limit": "1"})
    if not request_rows or not proposals:
        raise HTTPException(404, "Gera uma proposta antes de transferir o PDF.")
    items = await rest(user.token, "proposal_items", params={"proposal_id": f"eq.{proposals[0]['id']}",
                                                               "order": "position.asc"})
    pdf = build_proposal_pdf(request_rows[0], proposals[0], items)
    safe_number = re.sub(r"[^A-Za-z0-9_-]", "-", proposals[0]["proposal_no"])
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="OZ_{safe_number}.pdf"',
    })


@router.patch("/proposals/{request_id}/fields")
async def update_request_fields(request_id: str, update: FieldsUpdate,
                                user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    allowed = {"client_name", "client_email", "project_name", "location", "construction_year",
               "basement_count", "objective", "deadline", "categories", "constraints",
               "missing_information"}
    if set(update.fields) - allowed:
        raise HTTPException(422, "O pedido contém campos desconhecidos.")
    current = await rest(user.token, "proposal_requests", params={"id": f"eq.{request_id}",
                                                                    "select": "*", "limit": "1"})
    if not current:
        raise HTTPException(404, "Pedido não encontrado.")
    request_row = current[0]
    fields = {**(request_row.get("extracted_fields") or {}), **update.fields}
    title = fields.get("project_name") or fields.get("client_name") or request_row["title"]
    missing = list(fields.get("missing_information") or [])
    for key, label in [("client_name", "Nome do cliente"), ("client_email", "Email do cliente"),
                       ("project_name", "Nome da obra"), ("location", "Localização")]:
        if fields.get(key):
            missing = [item for item in missing if label.casefold() not in str(item).casefold()]
        elif not any(label.casefold() in str(item).casefold() for item in missing):
            missing.append(label)
    fields["missing_information"] = missing
    deadline = fields.get("deadline") or None
    if deadline:
        try:
            deadline = date.fromisoformat(str(deadline)[:10]).isoformat()
        except ValueError as exc:
            raise HTTPException(422, "O prazo tem de ser uma data válida.") from exc

    client_id = request_row.get("client_id")
    if fields.get("client_name"):
        if client_id:
            await rest(user.token, "clients", method="PATCH", params={"id": f"eq.{client_id}"},
                body={"name": fields.get("client_name"), "email": fields.get("client_email") or None},
                prefer="return=minimal")
        else:
            client_id = await create_client(user.token, user.id, fields.get("client_name"), fields.get("client_email"))

    project_id = request_row.get("project_id")
    year = fields.get("construction_year")
    if isinstance(year, str) and year.isdigit():
        year = int(year)
    if fields.get("project_name"):
        project_data = {"name": fields["project_name"], "location": fields.get("location") or None,
                        "year_built": year if isinstance(year, int) else None}
        if project_id:
            await rest(user.token, "projects", method="PATCH", params={"id": f"eq.{project_id}"},
                body=project_data, prefer="return=minimal")
        else:
            created_project = await rest(user.token, "projects", method="POST", body={
                **project_data, "owner_id": user.id, "client_id": client_id,
            }, prefer="return=representation")
            project_id = created_project[0]["id"]

    changes: dict[str, Any] = {"extracted_fields": fields, "title": str(title)[:300], "deadline": deadline}
    if request_row.get("client_id") != client_id:
        changes["client_id"] = client_id
    if request_row.get("project_id") != project_id:
        changes["project_id"] = project_id
    if request_row["status"] == "NEEDS_INFORMATION" and not missing:
        changes["status"] = "DRAFT"
    request_rows = await rest(user.token, "proposal_requests", method="PATCH",
        params={"id": f"eq.{request_id}", "select": "*"},
        body=changes,
        prefer="return=representation")
    await rest(user.token, "proposal_analysis", method="PATCH", params={"request_id": f"eq.{request_id}"},
        body={"extracted": fields, "categories": fields.get("categories", []),
              "missing_information": fields.get("missing_information", []),
              "restrictions": fields.get("constraints", [])}, prefer="return=minimal")
    return request_rows[0]


@router.patch("/proposals/{request_id}/status")
async def change_status(request_id: str, update: StatusChange,
                        user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    if update.status not in STATUSES:
        raise HTTPException(422, "Estado inválido.")
    if update.status == "SENT":
        raise HTTPException(409, "Usa o envio pelo Resend para marcar a proposta como enviada.")
    if update.status == "APPROVED":
        request_rows = await rest(user.token, "proposal_requests", params={"id": f"eq.{request_id}", "limit": "1"})
        if not request_rows:
            raise HTTPException(404, "Pedido não encontrado.")
        fields = request_rows[0].get("extracted_fields") or {}
        if fields.get("missing_information"):
            raise HTTPException(409, "Preenche a informação em falta antes de aprovar.")
        proposals = await rest(user.token, "proposals", params={"request_id": f"eq.{request_id}", "limit": "1"})
        if not proposals:
            raise HTTPException(409, "Gera uma proposta antes de a aprovar.")
        items = await rest(user.token, "proposal_items", params={"proposal_id": f"eq.{proposals[0]['id']}",
                                                                   "enabled": "eq.true"})
        if not items:
            raise HTTPException(409, "Adiciona pelo menos um serviço antes de aprovar.")
        if any(float(row["unit_price"]) <= 0 for row in items):
            raise HTTPException(409, "Confirma um preço superior a zero em todos os serviços ativos.")
    rows = await rest(user.token, "proposal_requests", method="PATCH",
                      params={"id": f"eq.{request_id}", "select": "*"},
                      body={"status": update.status}, prefer="return=representation")
    if not rows:
        raise HTTPException(404, "Pedido não encontrado.")
    await rest(user.token, "proposals", method="PATCH", params={"request_id": f"eq.{request_id}"},
               body={"status": update.status}, prefer="return=minimal")
    return rows[0]


@router.get("/services")
async def list_services(user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    return await rest(user.token, "services", params={"select": "*", "active": "eq.true",
                                                       "order": "category.asc,name.asc", "limit": "250"})


@router.post("/proposals/{request_id}/generate")
async def generate_proposal(request_id: str,
                            user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    result = await rest(user.token, "rpc/create_proposal_for_request", method="POST",
                        body={"p_request_id": request_id})
    row = result[0] if isinstance(result, list) else result
    return {"id": row["proposal_id"], "proposal_no": row["proposal_no"]}


@router.post("/proposals/{request_id}/items")
async def add_item(request_id: str, item: ItemCreate,
                   user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    proposals = await rest(user.token, "proposals", params={"request_id": f"eq.{request_id}", "limit": "1"})
    if not proposals:
        raise HTTPException(409, "Gera uma proposta antes de adicionar serviços.")
    services = await rest(user.token, "services", params={"service_id": f"eq.{item.service_id}",
                                                          "active": "eq.true", "limit": "1"})
    if not services:
        raise HTTPException(404, "Serviço não encontrado.")
    service = services[0]
    positions = await rest(user.token, "proposal_items", params={"proposal_id": f"eq.{proposals[0]['id']}",
                                                                  "select": "position", "order": "position.desc", "limit": "1"})
    row = {
        "owner_id": user.id, "proposal_id": proposals[0]["id"], "service_id": service["service_id"],
        "name": service["name"], "unit": service["unit"], "quantity": item.quantity,
        "unit_price": service["selling_price"], "technical_basis": service.get("technical_basis"),
        "position": (positions[0]["position"] + 1) if positions else 0,
    }
    created = await rest(user.token, "proposal_items", method="POST", body=row, prefer="return=representation")
    await mark_pricing(user.token, proposals[0]["id"])
    return created[0]


@router.post("/proposals/{request_id}/mqt-items/{mqt_item_id}/add")
async def add_mqt_item(request_id: str, mqt_item_id: str,
                       user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    proposals = await rest(user.token, "proposals", params={"request_id": f"eq.{request_id}", "limit": "1"})
    if not proposals:
        raise HTTPException(409, "Gera a proposta antes de importar linhas da MQT.")
    mqt_rows = await rest(user.token, "mqt_items", params={"id": f"eq.{mqt_item_id}",
        "request_id": f"eq.{request_id}", "limit": "1"})
    if not mqt_rows:
        raise HTTPException(404, "Linha da MQT não encontrada.")
    existing = await rest(user.token, "proposal_items", params={"source_mqt_item_id": f"eq.{mqt_item_id}", "limit": "1"})
    if existing:
        return existing[0]
    mqt = mqt_rows[0]
    positions = await rest(user.token, "proposal_items", params={"proposal_id": f"eq.{proposals[0]['id']}",
        "select": "position", "order": "position.desc", "limit": "1"})
    created = await rest(user.token, "proposal_items", method="POST", body={
        "owner_id": user.id, "proposal_id": proposals[0]["id"], "source_mqt_item_id": mqt_item_id,
        "service_id": mqt.get("service_id"), "name": mqt["description"], "unit": mqt["unit"],
        "quantity": mqt["quantity"], "unit_price": 0, "origin": "REQUIRES_REVIEW",
        "technical_basis": "Importado da MQT; preço e correspondência de serviço por validar.",
        "position": (positions[0]["position"] + 1) if positions else 0,
    }, prefer="return=representation")
    await mark_pricing(user.token, proposals[0]["id"])
    return created[0]


@router.patch("/proposal-items/{item_id}")
async def update_item(item_id: str, item: ItemUpdate,
                      user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    values = item.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, "Indica os campos a alterar.")
    rows = await rest(user.token, "proposal_items", method="PATCH", params={"id": f"eq.{item_id}",
                                                                                 "select": "*"},
                      body=values, prefer="return=representation")
    if not rows:
        raise HTTPException(404, "Linha da proposta não encontrada.")
    await mark_pricing(user.token, rows[0]["proposal_id"])
    return rows[0]


@router.delete("/proposal-items/{item_id}")
async def delete_item(item_id: str, user: CurrentUser = Depends(current_user)) -> dict[str, bool]:
    rows = await rest(user.token, "proposal_items", params={"id": f"eq.{item_id}", "select": "proposal_id", "limit": "1"})
    await rest(user.token, "proposal_items", method="DELETE", params={"id": f"eq.{item_id}"})
    if rows:
        await mark_pricing(user.token, rows[0]["proposal_id"])
    return {"deleted": True}


@router.post("/proposals/{request_id}/visits")
async def schedule_visit(request_id: str, visit: VisitCreate,
                         user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    if visit.scheduled_at.tzinfo is None:
        raise HTTPException(422, "A data e hora da visita têm de incluir o fuso horário.")
    rows = await rest(user.token, "proposal_requests", params={"id": f"eq.{request_id}", "select": "id", "limit": "1"})
    if not rows:
        raise HTTPException(404, "Pedido não encontrado.")
    created = await rest(user.token, "visits", method="POST", body={
        "owner_id": user.id, "request_id": request_id, "scheduled_at": visit.scheduled_at.isoformat(),
        "note": visit.note,
    }, prefer="return=representation")
    return created[0]


@router.patch("/visits/{visit_id}")
async def update_visit(visit_id: str, update: VisitStatusUpdate,
                       user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    if update.status not in {"SCHEDULED", "COMPLETED", "CANCELLED"}:
        raise HTTPException(422, "Estado da visita inválido.")
    rows = await rest(user.token, "visits", method="PATCH", params={"id": f"eq.{visit_id}", "select": "*"},
                      body={"status": update.status}, prefer="return=representation")
    if not rows:
        raise HTTPException(404, "Visita não encontrada.")
    return rows[0]


@router.get("/proposals/{request_id}/versions")
async def list_versions(request_id: str, user: CurrentUser = Depends(current_user)) -> list[dict[str, Any]]:
    proposals = await rest(user.token, "proposals", params={"request_id": f"eq.{request_id}", "limit": "1"})
    if not proposals:
        return []
    return await rest(user.token, "proposal_versions", params={"select": "id,version,created_at,snapshot",
        "proposal_id": f"eq.{proposals[0]['id']}", "order": "version.desc"})


@router.post("/proposals/{request_id}/versions")
async def save_version(request_id: str, user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    proposals = await rest(user.token, "proposals", params={"request_id": f"eq.{request_id}", "limit": "1"})
    if not proposals:
        raise HTTPException(409, "Gera a proposta antes de guardar uma versão.")
    result = await rest(user.token, "rpc/save_proposal_version", method="POST",
                        body={"p_proposal_id": proposals[0]["id"]})
    row = result[0] if isinstance(result, list) else result
    return {"id": row["version_id"], "version": row["version_number"]}


@router.post("/proposals/{request_id}/send-email")
async def send_proposal_email(request_id: str, payload: EmailRequest,
                              user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    if not settings.resend_api_key or not settings.email_from:
        raise HTTPException(503, "Configura RESEND_API_KEY e EMAIL_FROM no .env da API.")
    request_rows = await rest(user.token, "proposal_requests", params={"id": f"eq.{request_id}", "limit": "1"})
    proposal_rows = await rest(user.token, "proposals", params={"request_id": f"eq.{request_id}", "limit": "1"})
    if not request_rows or not proposal_rows:
        raise HTTPException(404, "Gera a proposta antes de enviar email.")
    proposal = proposal_rows[0]
    if proposal["status"] != "APPROVED":
        raise HTTPException(409, "A proposta tem de estar aprovada antes do envio.")
    request_row = request_rows[0]
    fields = request_row.get("extracted_fields") or {}
    to = payload.to or fields.get("client_email")
    if not to or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", to):
        raise HTTPException(422, "Indica um email válido para o cliente.")
    items = await rest(user.token, "proposal_items", params={"proposal_id": f"eq.{proposal['id']}",
                                                               "enabled": "eq.true", "order": "position.asc"})
    if not items or any(float(row["unit_price"]) <= 0 for row in items):
        raise HTTPException(409, "Confirma todos os preços antes de enviar a proposta.")
    rows_html = "".join(
        f"<tr><td>{html.escape(row['name'])}</td><td>{row['quantity']} {html.escape(row['unit'])}</td>"
        f"<td>{float(row['unit_price']):.2f} €</td></tr>" for row in items
    )
    total = sum(float(row["quantity"]) * float(row["unit_price"]) for row in items)
    subject = payload.subject or f"Proposta {proposal['proposal_no']} — {request_row['title']}"
    message_html = "<p>" + "</p><p>".join(html.escape(line) for line in payload.message.splitlines() if line) + "</p>"
    email_html = (
        f"<p>Exmo.(a) Senhor(a),</p><p>Segue o resumo da proposta <b>{html.escape(proposal['proposal_no'])}</b> "
        f"para <b>{html.escape(request_row['title'])}</b>.</p>"
        f"<table border='1' cellpadding='8' cellspacing='0'><thead><tr><th>Serviço</th><th>Qtd.</th>"
        f"<th>Preço unitário</th></tr></thead><tbody>{rows_html}</tbody></table>"
        f"<p>Subtotal: {total:.2f} €<br/>IVA ({proposal['vat_rate']}%): {total * float(proposal['vat_rate']) / 100:.2f} €<br/>"
        f"<b>Total: {total * (1 + float(proposal['vat_rate']) / 100):.2f} €</b></p>{message_html}"
        "<p>Segue em anexo o documento PDF da proposta.</p>"
    )
    pdf_bytes = build_proposal_pdf(request_row, proposal, items)
    safe_number = re.sub(r"[^A-Za-z0-9_-]", "-", proposal["proposal_no"])
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}", "Content-Type": "application/json"},
            json={"from": settings.email_from, "to": [to], "subject": subject, "html": email_html,
                  "attachments": [{"filename": f"OZ_{safe_number}.pdf", "content": base64.b64encode(pdf_bytes).decode("ascii")} ]})
    if response.is_error:
        raise HTTPException(502, "O Resend não conseguiu enviar o email. Verifica a chave e o remetente.")
    await rest(user.token, "proposals", method="PATCH", params={"id": f"eq.{proposal['id']}"},
               body={"status": "SENT"}, prefer="return=minimal")
    await rest(user.token, "proposal_requests", method="PATCH", params={"id": f"eq.{request_id}"},
               body={"status": "SENT"}, prefer="return=minimal")
    return {"sent": True, "email_id": response.json().get("id"), "to": to}
