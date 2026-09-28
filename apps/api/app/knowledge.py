from typing import Any

from fastapi import APIRouter, Depends

from app.auth import CurrentUser, current_user
from app.supabase_rest import rest

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("")
async def get_knowledge(user: CurrentUser = Depends(current_user)) -> dict[str, list[dict[str, Any]]]:
    tables = {
        "pathologies": "kb_pathologies_full",
        "causes": "kb_causes",
        "tests": "kb_tests",
        "solutions": "kb_solutions",
        "equipment": "kb_equipment",
        "construction_types": "kb_construction_types",
        "report_sections": "kb_report_sections",
    }
    data = {}
    for key, table in tables.items():
        data[key] = await rest(user.token, table, params={"select": "*", "limit": "500"})
    return data
