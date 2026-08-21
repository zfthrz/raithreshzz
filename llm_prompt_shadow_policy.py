"""Opt-in episode prompt policy used only by the LLM shadow A/B runner."""

from __future__ import annotations

import hashlib


SHADOW_PROMPT_POLICY_VERSION = "episode-grounding-shadow-v0.1"
SHADOW_AUTHORITY = "SHADOW_OBSERVATIONAL_ONLY"

SHADOW_EPISODE_PROMPT_APPENDIX = r"""

============================================================
SHADOW PREFLIGHT DE GROUNDING
============================================================

Antes de redactar el objeto, hacé internamente estas comprobaciones. No las
incluyas en la respuesta:

- Para interpretation, copiá literalmente la relación semántica resuelta por
  channel_direction_contract: higher significa mayor, lower significa menor y
  mixed significa variable o mixto.
- Para recommendation, obedecé literalmente coaching_direction: decrease pide
  reducir hacia la referencia, increase pide aumentar hacia la referencia y
  replicate_sequence pide reproducir o acompañar la secuencia de la referencia.
- La vuelta de REFERENCIA es siempre el objetivo de coaching. La vuelta comparada
  describe lo observado y nunca debe presentarse como objetivo.
- Los únicos dominios nombrables son action_channels y, si existe, speed_context.
  No completes causas mediante conocimiento general de conducción o del vehículo.
- Si una hipótesis necesita potencia, tracción, grip, trayectoria, línea, balance,
  transferencia de carga, neumáticos, aerodinámica o dinámica del vehículo,
  descartala y devolvé hypotheses vacía.
- Si no existe speed_context, no menciones velocidad. Si existe, usala sólo como
  contexto observado, nunca como acción del piloto ni como resultado prometido.
- Hacé una última comprobación cruzada: cada sustantivo técnico de interpretation,
  hypotheses y recommendation debe estar autorizado por el payload.

Estas reglas refuerzan el contrato existente; no agregan evidencia, canales,
ranking ni autoridad de coaching.
"""


def build_shadow_episode_system_prompt(production_prompt: str) -> str:
    """Return the production prompt plus the isolated shadow preflight."""

    if not isinstance(production_prompt, str) or not production_prompt.strip():
        raise ValueError("production episode prompt must be a non-empty string")
    return production_prompt.rstrip() + SHADOW_EPISODE_PROMPT_APPENDIX


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()
