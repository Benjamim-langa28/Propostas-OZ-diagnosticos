from __future__ import annotations

import re
import unicodedata
from typing import Any


EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def _clean_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"\*\*|__|`", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def _lines(value: str) -> list[str]:
    return [line.strip() for line in _clean_text(value).splitlines() if line.strip()]


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _field(block: str, labels: tuple[str, ...]) -> str | None:
    for line in _lines(block):
        match = re.match(r"^\s*(?:[-*•]\s*)?([^:]{1,60})\s*:\s*(.*?)\s*$", line)
        if match:
            actual_label = _fold(match.group(1).strip().strip("*_` "))
            if actual_label not in {_fold(label) for label in labels}:
                continue
            value = match.group(2).strip().strip("*_` ")
            value = re.sub(r"\s+", " ", value)
            return value or None
    return None


def _section(text: str, start: re.Pattern[str], stop: re.Pattern[str] | None = None) -> str:
    match = start.search(text)
    if not match:
        return ""
    end = stop.search(text, match.end()) if stop else None
    return text[match.end():end.start() if end else len(text)]


def _signature_details(text: str) -> dict[str, str]:
    closing = re.search(
        r"\b(?:atenciosamente|com os melhores cumprimentos|cumprimentos|best regards|kind regards|regards)\b\s*[,;:]?",
        text,
        re.I,
    )
    if not closing:
        return {}

    tail = text[closing.end():]
    email_matches = EMAIL_RE.findall(tail)
    phone_matches = PHONE_RE.findall(tail)
    without_contacts = EMAIL_RE.sub(" ", tail)
    without_contacts = PHONE_RE.sub(" ", without_contacts)
    without_contacts = re.sub(r"[📧📞✉️☎️]+", " ", without_contacts)
    without_contacts = re.sub(r"\s+", " ", without_contacts).strip(" ,;:-")

    role_match = re.search(
        r"\b(?:(?:senior|junior)\s+)?(?:architect|arquiteto|arquiteta|engenheiro|engenheira|"
        r"director|diretor(?:a)?|gestor(?:a)?|coordenador(?:a)?|manager)"
        r"(?:\s+(?:&|and|e)?\s*(?:project\s+)?(?:manager|gestor(?:a)? de projeto))?\b",
        without_contacts,
        re.I,
    )
    name_region = without_contacts[:role_match.start()] if role_match else without_contacts
    tail = without_contacts[role_match.end():] if role_match else ""
    # Prefer the organization after the person's role, so names like
    # "Senior Architect & Project Manager MultiSis, Lda." stay separated.
    legal_match = re.search(
        r"\b([A-ZÀ-ÖØ-Ý][\wÀ-ÿ&.'-]*(?:\s+[A-ZÀ-ÖØ-Ý][\wÀ-ÿ&.'-]*){0,2}\s*,?\s*"
        r"(?:Lda\.?|Ltd\.?|Limitada|S\.A\.?|SA|LLC))(?=\s|$)",
        tail if role_match else without_contacts,
        re.I,
    )
    organization = legal_match.group(1).strip(" ,;:-") if legal_match else None
    role = role_match.group(0).strip(" ,;:-") if role_match else None
    if not role_match:
        org_matches = list(re.finditer(
            r"\b(?:[A-ZÀ-ÖØ-Ý][\wÀ-ÿ&.'-]*\s+){0,3}[A-ZÀ-ÖØ-Ý][\wÀ-ÿ&.'-]*\s*,?\s*"
            r"(?:Lda\.?|Ltd\.?|Limitada|S\.A\.?|SA|LLC)\b",
            without_contacts,
            re.I,
        ))
        if org_matches:
            organization = org_matches[-1].group(0).strip(" ,;:-")
            name_region = without_contacts[:org_matches[-1].start()]
    name_region = re.sub(r"\b(?:Lda\.?|Ltd\.?|SA|S\.A\.?)\b.*", "", name_region, flags=re.I)
    name_parts = [part for part in re.split(r"[,;|\n]+", name_region) if part.strip()]
    sender_name = name_parts[-1].strip(" ,;:-") if name_parts else None
    if sender_name and len(sender_name.split()) > 4:
        sender_name = " ".join(sender_name.split()[:3])

    result: dict[str, str] = {}
    for key, value in (
        ("sender_name", sender_name),
        ("sender_role", role),
        ("sender_organization", organization),
        ("sender_email", email_matches[-1] if email_matches else None),
        ("sender_phone", phone_matches[-1].strip() if phone_matches else None),
    ):
        if value:
            result[key] = value
    return result


def parse_email_request(text: str) -> dict[str, Any]:
    """Extract labeled customer details and requested scope from pasted email/chat text."""
    cleaned = _clean_text(text)
    lines = _lines(cleaned)
    subject_match = re.search(r"^\s*(?:assunto|subject)\s*:\s*(.+?)\s*$", cleaned, re.I | re.M)
    subject = subject_match.group(1).strip(" *_`") if subject_match else None
    project_name = subject
    if project_name:
        project_name = re.sub(
            r"^(?:pedido\s+de\s+orçamento|pedido\s+de\s+orcamento|solicitação\s+de\s+orçamento|"
            r"solicitacao\s+de\s+orcamento|pedido\s+de\s+proposta)\s*(?:[-–—:]\s*)?",
            "",
            project_name,
            flags=re.I,
        ).strip(" -–—:") or subject

    company_start = re.compile(
        r"(?:dados|identifica[cç][aã]o|informac[oõ]es)\s+da\s+empresa[^:\n]*:", re.I,
    )
    signature_start = re.compile(
        r"\b(?:atenciosamente|com os melhores cumprimentos|cumprimentos|best regards|kind regards|regards)\b",
        re.I,
    )
    company_block = _section(cleaned, company_start, signature_start)

    scope_start = re.search(r"\b(?:contemple|inclua|inclu[íi]r|abranger)\s*:?", cleaned, re.I)
    scope_end = company_start.search(cleaned) or signature_start.search(cleaned)
    scope_block = ""
    if scope_start:
        end_index = scope_end.start() if scope_end and scope_end.start() > scope_start.end() else len(cleaned)
        scope_block = cleaned[scope_start.end():end_index]

    bullets = []
    for line in _lines(scope_block):
        cleaned_line = re.sub(r"^\s*[-*•]\s*", "", line).strip(" *_` ;")
        cleaned_line = re.sub(r"\s+", " ", cleaned_line)
        if cleaned_line:
            bullets.append(cleaned_line)

    requested_services = []
    requested_conditions = []
    for item in bullets:
        lowered = item.casefold()
        if any(word in lowered for word in ("prazo estimado", "prazo de execução", "condições comerciais", "forma de pagamento")):
            requested_conditions.append(item)
        else:
            requested_services.append(item)

    body_end = company_start.search(cleaned) or signature_start.search(cleaned)
    request_body = cleaned[:body_end.start()] if body_end else cleaned
    objective_match = re.search(
        r"\b(?:o objetivo|objetivo)\s*(?:é|e|:)?\s*(.+?)(?=\n\s*\n|\n\s*(?:peço|solicito|pretendo)|$)",
        request_body,
        re.I | re.S,
    )
    objective = re.sub(r"\s+", " ", objective_match.group(1)).strip(" .;\n") if objective_match else None

    location_match = re.search(
        r"\b(?:localizado|situado|localizada|situada)\s+em\s+(.+?)(?=[.;\n]|\s+o objetivo\b|$)",
        request_body,
        re.I,
    )
    location = re.sub(r"\s+", " ", location_match.group(1)).strip(" *_` ,") if location_match else None
    if not location:
        location = _field(company_block, ("Localização", "Local", "Morada da obra", "Endereço da obra"))

    lowered = _fold(cleaned)
    categories: list[str] = []
    category_rules = (
        (("eletric", "electric", "curto-circuito", "isolamento eletrico"), "Diagnóstico elétrico"),
        (("fissur", "rachad", "rache"), "Patologia / fissuração"),
        (("betão", "concreto", "carote", "carbonatação", "cloreto"), "Ensaios de betão"),
        (("humidade", "infiltração", "água"), "Humidade / infiltração"),
        (("monitor", "fissurómetro"), "Monitorização"),
        (("inspeção", "vistoria", "diagnóstico"), "Inspeção / diagnóstico"),
    )
    for words, category in category_rules:
        if any(word in lowered for word in words) and category not in categories:
            categories.append(category)

    result: dict[str, Any] = {
        "source_subject": subject,
        "project_name": project_name,
        "client_name": _field(company_block, ("Empresa", "Nome da empresa", "Cliente")),
        "client_tax_id": _field(company_block, ("NIF", "NUIT", "Número de contribuinte", "Tax ID", "VAT")),
        "client_address": _field(company_block, ("Endereço", "Morada", "Address")),
        "client_phone": _field(company_block, ("Telefone", "Telefone de contacto", "Contacto telefónico", "Phone")),
        "client_email": _field(company_block, ("Email", "E-mail", "Correio eletrónico")),
        "client_contact_name": _field(company_block, ("Pessoa de contacto", "Contacto")),
        "location": location,
        "objective": objective,
        "requested_services": requested_services,
        "requested_conditions": requested_conditions,
        "categories": categories,
    }
    result.update(_signature_details(cleaned))
    return {key: value for key, value in result.items() if value not in (None, "", [])}


def looks_like_email(text: str) -> bool:
    return bool(
        re.search(r"^\s*(?:assunto|subject|de|from)\s*:", text, re.I | re.M)
        or re.search(r"\b(?:atenciosamente|com os melhores cumprimentos|best regards)\b", text, re.I)
    )
