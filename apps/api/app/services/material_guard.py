"""Deteta o material do pedido e evita serviços próprios de outro material."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

TIMBER_TERMS = ("madeira", "xilofag", "resistograph", "pilodyn", "carunch", "termita", "cupim",
                "frechal", "frechai", "travessanho", "cruzes de santo andre", "gaiola pombalina", "pombalino")
CONCRETE_TERMS = ("betao", "betoe", "concreto", "armadura", "carbonatac", "cloreto", "esclerometr", "pacometro", "carote")
CONCRETE_SERVICE_WORDS = ("betao", "betoe", "carbonatac", "esclerometr", "cloreto", "armadura", "carote",
                          "pacometr", "corrosao", "petrograf", "pull off")
REQUEST_KEYS = ("objective", "request_type", "problem_type", "problem_summary", "symptom_locations",
                "requested_services", "source_subject", "project_name")


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def request_text(fields: dict[str, Any] | None, raw_text: str | None) -> str:
    parts = [raw_text or ""]
    for key in REQUEST_KEYS:
        value = (fields or {}).get(key)
        if isinstance(value, (list, tuple)):
            parts.extend(str(v) for v in value if v)
        elif value:
            parts.append(str(value))
    return "\n".join(parts)


def detect_materials(text: str) -> set[str]:
    folded = _fold(text)
    found: set[str] = set()
    if sum(1 for term in TIMBER_TERMS if term in folded) >= 2:
        found.add("madeira")
    if any(term in folded for term in CONCRETE_TERMS):
        found.add("betao")
    return found


def is_timber_only(materials: set[str]) -> bool:
    return "madeira" in materials and "betao" not in materials


def service_is_concrete_specific(name: Any) -> bool:
    folded = _fold(name)
    return any(word in folded for word in CONCRETE_SERVICE_WORDS)