# Race Engineer — ChatGPT handoff — 2026-08-24

**Project name: Threshzz's Telemetry Analysis LMU (= Race Engineer).** La app se
muestra como "Threshzz's Telemetry Analysis LMU"; toda la doc interna usa
"Race Engineer". Son el mismo proyecto.

This is the current portable continuation checkpoint. Supplement it with
`AGENTS.md`, `PROJECT_CONTEXT.md`, `PROJECT_STATUS.md`, `README.md` and the exact
current code/tests (source of truth; never infer from `legacy/`).

## Repository checkpoint

```text
repository: zfthrz/raithreshzz
branch: main (puede estar N commits ahead de origin; el usuario pushea)
GUI: 1.17 — telemetry playback + resolution (20 Hz default, 10-50 Hz)
full pytest: 1114 passed (última corrida completa)
matcher: episode_pair_matcher.py v0.3 con CALIBRATIONS por contexto
```

## Reading order (before any non-trivial change)

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `PROJECT_STATUS.md`
4. `README.md`
5. `docs/DEEPSEEK_HANDOFF_2026_08_17.md`
6. `docs/CHATGPT_HANDOFF_2026_08_23.md`
7. this handoff
8. exact code/tests of the chosen task

## Hard rules (non-negotiable)

- Python owns deterministic facts: laps, deltas, events, physical points, gates,
  History, matching, candidate generation, action authorization, validators,
  reference selection. The LLM only interprets/prioritizes/words authorized
  evidence.
- Never invent metres/percentages/turns/counts; never weaken a validator; never
  relax track/layout/vehicle gates to get matches.
- Speed is context, not a driving target. `LMP2_ELMS` != `LMP2`/WEC.
- H5.1 `session_reference` is coaching authority; H5.2/H5.3 observational/shadow;
  `historical_actions_authorized=false`; H5.3 = ROADMAP_ONLY.
- H5.4 P10/P11 presentation-only; never mutate `next_stint_plan`.
- LLM prompt experiments only via `run_llm_prompt_shadow.py`; promotion needs
  exact A/B paired evidence; current verdict
  `PROMOTION_BLOCKED_INSUFFICIENT_PAIRED_EVIDENCE`.
- Runtime outputs only under `telemetria/`, `data/generated/`, `data/local/`.
- No `git add .`; stage explicit paths only; no commit/push unless requested.
- Preserve untracked local evidence: `track_exports/`, `.qwen/`, `Modelfile`,
  `*.patch`, `fix_h5_4_p9*`, `p11_diff.txt`,
  `tests/test_coaching_precision_p10.py`, `$null` (junk, ignore).

## Current state highlights

### GUI v1.17
- Section navigation (Resumen/Telemetría/Historial/Diagnóstico), compact cards,
  status badges + tooltips, side-by-side H5.2 comparison, calibration status
  panel (Diagnóstico → Calibración, dedupe por contexto, registry como fuente
  de verdad).
- Telemetría: GPS map + 3-lane chart, turn selector, plan-zone selector
  (plan ↔ mapa ↔ telemetría sync), playback (`▶/⏸/⏮`, 1 índice/tick con
  intervalo 1000/Hz), resolution selector 10/20/50 Hz (default 20; native
  ~100 Hz), window default 1480x880.

### Matcher H2 v0.3 — calibración por contexto (`CALIBRATIONS`)
- Spa LMP2_ELMS: `CALIBRATED_PROVISIONAL_SINGLE_CONTEXT` (72 labels, v0.3
  original intacto).
- Imola LMP2_ELMS e Interlagos LMP2_ELMS: `CALIBRATED_PROVISIONAL_LOW_EVIDENCE`
  (MATCH core + REJECT; 0 contradicciones sobre 24 labels reales cada uno).
- Monza HYPER y Monza LMP2_ELMS: `CALIBRATED_PROVISIONAL_LOW_EVIDENCE`
  REJECT-only (sin SAME en calibración; `match_enabled=False`, REJECT >1000 m).
- Contextos sin calibración → fail-closed `NO_CALIBRATION_FOR_CONTEXT`.
- Alias versionado `episode_pair_matcher_v0_3.py` byte-idéntico.

### Calibración H2 (campaign 2026-08-23/24)
- 8 batches labelados 24/24 (Imola LMP2_ELMS, Interlagos, Fuji, Sarthe
  LMP2_WEC, Imola HYPER, Monza HYPER, Monza LMP2_ELMS, Spa 034f). Cola Spa 98
  obsoleta eliminada.
- Interlagos: `evaluation_readiness: PASS` (5 eval). Fuji/Sarthe/Imola
  HYPER/Monza: eval vacía (faltan sesiones independientes).
- Comandos: `prepare_calibration_batch.py` (orchestrator 1.5, `--skip-import`),
  `label_episode_pairs.py`, `validate_pair_labels.py`.

### Phase E/F (H5.2/H3)
- Phase E: primer raw H5.2 de Spa generado (determinista). Sarthe LMP2_WEC,
  Imola HYPER y Sarthe HYPER bloqueados por gates H4 (reference lap / vueltas
  válidas) → CALIBRATION SESSION REQUIRED (sesiones del mismo auto, ≥2-3
  vueltas válidas).
- Phase F: matcher corrido sobre 4 batches; persistent patterns Imola (15) e
  Interlagos (9) importados a History (runs 3-4). Orchestrator `h3` stage:
  `SKIPPED_NOT_APPLICABLE` con razón por contexto (`h3_applicability`).

### Phase J (golden set)
- `golden_set_semantic_regression.py` + `golden_set/golden_set_v0_1.json`
  (6 records SEED, un track cada uno). Evaluación semántica (región, familias,
  P10/P11, acciones prohibidas, evidencia). 6/6 PASS.

### WIP sin commitear
- Phase I completada (2026-08-24): `model_observability.py` read-only con
  tests; corrida real: deepseek 23 (12 PASS/11 STALE), llamacpp 5 (1/4), ollama
  3 (0/3); retries deepseek 6.4%, ollama 9.9%. Tokens/cost/latencia requieren
  benchmark vivo (no están en artefactos).

## Roadmap position

Phases: A (GUI) en curso/pulido · B cerrada · C completada (KEEP_SHADOW con 1
CONFLICTS en Imola T5) · D en curso (Monza necesita pares SAME) · E parcial ·
F parcial · G bloqueado · H futuro · I iniciada (tool WIP) · J v0.1 · K futuro.

Next natural slices:
1. Terminar Phase I: tests + corrida real + reporte por backend/modelo
   (deepseek-v4-pro, deepseek-v4-flash, llamacpp qwen3-14b, ollama
   ingenierov3, qwen3.8-27b). Sin telemetría nueva.
2. Phase A: más pulido GUI (estética/UX) si el usuario lo pide.
3. Phase D: re-estratificar colas de Monza para pares SAME (labeling, no
   telemetría) y registrar núcleos MATCH.
4. Telemetría nueva (CALIBRATION SESSION): Sarthe LMP2_WEC/Imola HYPER/Sarthe
   HYPER para H5.2; +2-3 sesiones por contexto para particiones de evaluación.

## Validation commands

```powershell
python -m pytest -q -p no:cacheprovider --basetemp=data\generated\pytest_tmp_x tests
python run_race_engineer_regressions.py --analyzer analyze_telemetry.py
python apply_objective_python_recovery_2026_08_13.py --check analyze_telemetry.py
```

Report exactly what ran/passed/failed/skipped. GUI-only changes need no LLM call.
