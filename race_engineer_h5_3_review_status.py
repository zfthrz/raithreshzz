"""Read-only GUI projection of local H5.3 review-maintenance state."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class H53ReviewStatus:
    code: str
    text: str
    style: str
    detail: str


def _nonnegative_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def project_state(document: dict[str, Any]) -> H53ReviewStatus:
    if document.get("historical_actions_authorized") is not False:
        raise ValueError("historical_actions_authorized must remain false")
    code = document.get("status")
    pending = _nonnegative_int(
        document.get("pending_review_count", 0), field="pending_review_count"
    )
    revision_value = document.get("current_revision")
    revision = (
        f"v{_nonnegative_int(revision_value, field='current_revision')}"
        if revision_value is not None
        else "sin revisión"
    )
    if code == "UP_TO_DATE":
        if pending:
            raise ValueError("UP_TO_DATE cannot contain pending reviews")
        return H53ReviewStatus(
            code=code,
            text=f"H5.3 shadow · al día · {revision}",
            style="H53Ready.TLabel",
            detail="La cola automática coincide con todos los artefactos disponibles.",
        )
    if code == "NEW_REVIEW_REQUIRED":
        if pending < 1:
            raise ValueError("NEW_REVIEW_REQUIRED requires pending reviews")
        suffix = "caso pendiente" if pending == 1 else "casos pendientes"
        return H53ReviewStatus(
            code=code,
            text=f"H5.3 shadow · {pending} {suffix} · {revision}",
            style="H53Pending.TLabel",
            detail=str(document.get("current_labels_json") or "Revisión manual requerida."),
        )
    if code == "EXPANDED_NO_REVIEW_REQUIRED":
        return H53ReviewStatus(
            code=code,
            text=f"H5.3 shadow · migrado · {revision}",
            style="H53Ready.TLabel",
            detail="La evidencia cambió, pero todos los labels se conservaron exactamente.",
        )
    if code == "NO_SOURCE_ARTIFACTS":
        return H53ReviewStatus(
            code=code,
            text="H5.3 shadow · sin evidencia",
            style="H53Muted.TLabel",
            detail="Todavía no existen artefactos históricos de acción para revisar.",
        )
    if code == "FAILED":
        return H53ReviewStatus(
            code=code,
            text="H5.3 shadow · revisar estado",
            style="H53Error.TLabel",
            detail=str(document.get("error") or "El mantenimiento H5.3 falló."),
        )
    raise ValueError(f"unknown H5.3 maintenance status: {code!r}")


def load_status(path: Path) -> H53ReviewStatus:
    path = Path(path)
    if not path.is_file():
        return H53ReviewStatus(
            code="STATE_UNAVAILABLE",
            text="H5.3 shadow · estado no disponible",
            style="H53Muted.TLabel",
            detail=f"No existe todavía: {path}",
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("JSON root must be an object")
        return project_state(document)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return H53ReviewStatus(
            code="STATE_INVALID",
            text="H5.3 shadow · estado inválido",
            style="H53Error.TLabel",
            detail=str(exc),
        )
