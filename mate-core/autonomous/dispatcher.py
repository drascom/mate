"""Mate Core — Pi JSON output → action handler dispatch.

Pi ```json``` kod bloğu döner; bu modül parse eder, allowed_actions
whitelist'iyle filtreler, her aksiyonu sıralı yürütür.
"""
from __future__ import annotations

import json
import re
from typing import Any

from autonomous import actions

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


def parse_action_plan(reply: str) -> dict[str, Any] | None:
    """Pi cevabından ilk JSON bloğunu çıkar ve şemayı doğrula.

    Beklenen: `{"plan": str, "actions": [{"type": str, ...}, ...], "summary": str}`.
    """
    match = _JSON_BLOCK_RE.search(reply)
    candidate = match.group(1) if match else reply.strip()
    candidate = candidate.strip()
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return None
    try:
        obj = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if not isinstance(obj.get("actions"), list):
        return None
    if "plan" in obj and not isinstance(obj["plan"], str):
        return None
    if "summary" in obj and not isinstance(obj["summary"], str):
        return None
    return obj


async def execute_action(
    spec: dict[str, Any],
    allowed: list[str],
    *,
    admin: bool = False,
) -> dict[str, Any]:
    """Tek aksiyonu çalıştır. allowed whitelist dışındaki tip rejected sayılır.

    ADMIN_ONLY_ACTIONS (örn. agentic_pi) sadece admin=True ise yürütülür;
    task fm.admin alanından geliyor.
    """
    if not isinstance(spec, dict):
        return {"status": "rejected", "reason": "action dict değil", "spec": spec}
    action_type = spec.get("type")
    if not isinstance(action_type, str):
        return {"status": "rejected", "reason": "type alanı eksik", "spec": spec}
    if action_type not in allowed:
        return {"status": "rejected", "reason": f"izinli değil: {action_type}", "spec": spec}
    if action_type in actions.ADMIN_ONLY_ACTIONS and not admin:
        return {
            "status": "rejected",
            "reason": f"{action_type} admin context gerektirir",
            "spec": spec,
        }
    handler = actions.HANDLERS.get(action_type)
    if not handler:
        return {"status": "rejected", "reason": f"bilinmiyor: {action_type}", "spec": spec}
    try:
        return await handler(spec)
    except actions.ActionError as exc:
        return {"status": "error", "error": str(exc), "spec": spec}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300], "spec": spec}


async def execute_plan(
    action_plan: dict[str, Any],
    allowed: list[str],
    *,
    admin: bool = False,
) -> list[dict[str, Any]]:
    """Aksiyon listesini sırayla çalıştır, her birinin sonucunu döndür.

    İlk hata sonrasında dur (fail-fast). MVP'de bu yeterli; ileride
    `continue_on_error` flag'i eklenebilir.
    """
    results: list[dict[str, Any]] = []
    for spec in action_plan.get("actions", []):
        result = await execute_action(spec, allowed, admin=admin)
        results.append({"action": spec, "result": result})
        if result.get("status") == "error":
            break
    return results
