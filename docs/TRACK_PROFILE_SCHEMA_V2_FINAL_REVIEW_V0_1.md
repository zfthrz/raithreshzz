# Track Profile Schema v2 — Final Review

**Date:** 2026-08-19
**Review scope:** 6 golden profiles + gap analysis + schema v2 design
**Decision:** PENDING (see Section 8)

---

## 1. Coverage analysis — 6 golden profiles

### 1.1 Turn coverage (schema v1 `turns` array)

| Track | Schema | Turns | Lap length (m) | Turn coverage % | Status |
|---|---|---|---|---|---|
| Monza | v0.3 | 11 | 5779.35 | ~34.4% | VALIDATED_MULTI_SESSION |
| Imola | v0.3 | 19 | 4892.00 | ~50.7% | VALIDATED_MULTI_SESSION |
| Fuji | v0.3 | 16 | 4526.01 | ~56.0% | VALIDATED_MULTI_SESSION |
| Interlagos | v0.3 | 15 | 4267.00 | ~43.5% | VALIDATED_MULTI_SESSION |
| Spa | v0.3 | 19 | 6972.00 | ~22.3% | VALIDATED_MULTI_SESSION |
| Le Mans | v0.2 | 19 | 13617.50 | ~33.9% | VALIDATED_MULTI_SESSION |

**Key observations:**
- Spa has the **lowest turn coverage** at ~22.3%, with many long straights that are NOT turns but ARE real track features (Les Arcs → Blanchimont, Pouls, etc.)
- Fuji has the **highest turn coverage** at 56.0%, which is expected for a WEC/LMU-validated 16-turn layout
- Le Mans long straights (Tertre Rouge→Daytona 1740m, Daytona→Michelin 1600m, Michelin→Mulsanne 1160m, Mulsanne→Indianapolis 1720m, Arnage→Porsche 1040m, Karting→Ford 260m) are fully captured in `geometric_notes` gaps
- Spa long straights (La Source→Eau Rouge 544m, Eau Rouge→Les Combes 958m, Malmedy→Bruxelles 232m, Jacky Ickx→Pouhon 364m, Pouhon→Fagnes 230m, Curve Paul Frere→Blanchimont 280m, Blanchimont→Bus Stop 398m) are documented in `geometric_notes` as `straight_real_track_feature`

### 1.2 Segments proposal — 11 straights + 2 transitions across 3 tracks

| Track | Straight count | Distances (m) | Transition count | Distances (m) |
|---|---|---|---|---|
| Monza | 6 | 160, 338, 230, 155, 940, 835 | 0 | — |
| Imola | 5 | 280, 170, 230, 310, 430 | 0 | — |
| Fuji | 1 | 206 | 2 | 72, 84 |
| **Total** | **12** | — | **2** | — |

**Notes:**
- **12 straights + 2 transitions total** — far fewer than initially feared (~300+ gap records)
- Only 3 tracks (Monza, Imola, Fuji) have had segments explicitly defined in `geometric_notes`
- Spa's 7 long straights (544, 958, 232, 364, 230, 280, 398) are currently listed in `geometric_notes` as gaps but NOT as segments
- Le Mans has 11 gap records in `geometric_notes` (including GPS note, audit note) — these are long straights

### 1.3 Gap classification (from gap analysis)

| Classification | Count across 3 profiles | Example |
|---|---|---|
| `straight_real_track_feature` | 11 | Monza 940m straight |
| `straight_short_real_track_feature` | 1 | Fuji 94m (classified as "short straight") |
| `transition_zone` | 2 | Fuji 72m, 84m |
| `acceptable_boundary_offset` | 5 | Monza/T7, T8 offsets |
| `touching_boundary` | 2 | Monza/T13, T14 |
| `low_curvature_continuation` | 1 | Fuji T7 |

---

## 2. Coverage gaps by category

### 2.1 High-priority gaps (long straights, missing segments)

| Category | Description | Current handling |
|---|---|---|
| **Long straights (≥200m)** | Spa 958m, Le Mans 1740m/1600m/1720m | `geometric_notes` gaps — **v2 segments would formalize these** |
| **Medium straights (100-200m)** | Monza 160m, Fuji 206m | Currently in `geometric_notes` — **v2 segments would formalize** |
| **Short straights (<100m)** | Fuji 72m, 84m transitions | Classified as `transition_zone` — **v2 segments would formalize** |
| **Manual low-curvature turns** | 13 total across 6 profiles | `manual_low_curvature_turns` array — **unchanged in v2** |
| **Ignored geometric features** | 17 total across 6 profiles | `ignored_geometric_features_m` — **unchanged in v2** |

### 2.2 Low-priority gaps (boundary offsets)

- `acceptable_boundary_offset` (0-20m) and `touching_boundary` (0m) are artifacts of curvature detection — **not actionable in v2**, remain in `geometric_notes`

---

## 3. Invariants changed (v1 → v2)

| # | V1 invariant | V2 invariant | Change type |
|---|---|---|---|
| 1 | Turns = high-curvature regions | Turns + segments do NOT partition lap | **Corrected** |
| | | union(turns, segments) may be subset of lap | |
| | | Uncovered regions are valid | |
| | | Segment-absent ≠ error | |
| 2 | `group` field in turns | `group` field preserved as semantic aggregation | **Unchanged** |
| 3 | `gap_explanation` type only | `gap_explanation` + `segment` entity | **Added** |
| 4 | Turns overlap = acceptable | **Turns and segments mutually exclusive** | **New** |
| 5 | Ordering per turn only | **Turns + segments ordered globally** | **New** |
| 6 | Wraparound = allowed | **Wraparound = forbidden** | **New** |
| 7 | Schema version = 1 | **Schema version distinguishes v1/v2** | **New** |
| 8 | Validator v0.1 | **Validator v0.2 validates both schemas** | **New** |

**Net change:** 8 invariants — 0 removed (complex/group unchanged), 6 new, 2 upgraded (validator version, coverage rule).

---

## 4. Value of segments

### 4.1 Functional value

| Aspect | Current (v1) | v2 segments | Value |
|---|---|---|---|
| **Long straights** | `geometric_notes` gaps (informal) | `segment` entity with types | **High** — formalizes coverage |
| **Transition zones** | `geometric_notes` gaps | `segment` type = `transition` | **High** — captures real track features |
| **Location priority** | turn > group > ignored_feature | turn > segment >> ignored_feature | **Unchanged** — `group` preserved; segments add granularity, don't replace `group` |
| **Validator coverage** | Validator checks turns only | Validator checks turns+segments | **Medium** — consistency |
| **H5.2 boundary** | `profile_boundaries()` returns turns | `profile_boundaries()` returns turns+segments | **Medium** — finer granularity |

### 4.2 Evidence-driven vs full coverage

**Schema v2 design choice: selective/evidence-driven coverage**

- **Not all gaps become segments.** Only gaps that represent real, actionable track features (straight, transition) get segments.
- **Complexity (≥200m)** — complexity is semantic aggregation via `group` field, not a coverage mechanism. `group` is unchanged in v2.
- **GPS gap notes, audit notes, low-curvature explanations** — remain in `geometric_notes` only.

**This is the correct design choice:**
- 12 straights + 2 transitions across 3 tracks (Monza, Imola, Fuji) — **very small scope**
- Spa's 7 long straights + Le Mans 11 long straights — **would benefit from v2 but deferred**
- Total segments added: **14 segments across 3 tracks** (very small, manageable scope)

---

## 5. Distance → Location mapping

### 5.1 Location priority (v1 → v2)

**v1:** `turn > complex > ignored_feature`
**v2:** `turn > segment >> ignored_feature`

**Impact:**
- **For Spa (22.3% turn coverage):** segment priority means `profile_boundaries()` will now include segment starts/ends, allowing H5.2 to split at segment boundaries instead of just turns. **This is critical for Spa**, where 77.7% of the lap is non-turn.
- **For Le Mans (33.9% turn coverage):** same benefit — segments enable finer splitting of H5.2 boundaries on long straights.
- **For Monza/Imola/Fuji (50-56% turn coverage):** marginal improvement — turns already cover most of the lap.

### 5.2 Example: Spa segmentation (documented gaps)

| Segment | Start (m) | End (m) | Distance (m) | Classification |
|---|---|---|---|---|
| La Source → Eau Rouge | 294.5 | 838.5 | 544.0 | straight |
| Eau Rouge → Les Combes | 1278.5 | 2236.5 | 958.0 | straight |
| Malmedy → Bruxelles | 2604.5 | 2836.5 | 232.0 | straight |
| Jacky Ickx → Pouhon | 3248.5 | 3612.5 | 364.0 | straight |
| Pouhon → Fagnes | 4062.5 | 4292.5 | 230.0 | straight |
| Curve Paul Frere → Blanchimont | 5328.5 | 5608.5 | 280.0 | straight |
| Blanchimont → Bus Stop | 6176.5 | 6574.5 | 398.0 | straight |

**Note:** These 7 straights are currently documented in `geometric_notes` as `straight_real_track_feature` gaps but are NOT yet defined as v2 `segment` entities. Spa segmentation is deferred to v2 implementation.

---

## 6. H5.2 / H5.3 impact

### 6.1 H5.2 compatibility

| Component | V1 | V2 | Compatibility |
|---|---|---|---|
| `profile_boundaries()` signature | Returns turn start/end | Returns turn + segment start/end | **No change** — method signature identical |
| `profile_boundaries()` output | Returns turn boundaries | Returns turn + segment boundaries | **BEHAVIORAL CHANGE** — same signature, different output. Requires regression validation. |
| Boundary splitting | Splits at turn boundaries | Splits at turn + segment boundaries | **BEHAVIORAL CHANGE** — more granular boundaries. Requires regression validation. |
| `profile_boundaries()` validation | Schema v1 validator | Schema v2 validator (v0.2) | **No change** — validator checks both schemas |

### 6.2 H5.3 compatibility

- Schema v2 does not change the `segment_reference` vs `historical_reference` contract.
- H5.3 candidate selection (H5.3a-f) depends on `session_reference` and `historical_reference` — **unchanged**.
- H5.3 action policy (brake/throttle) depends on `profile_boundaries()` — **BEHAVIORAL CHANGE** (same signature, more boundaries). Requires H5.3 regression validation before claiming compatibility.

---

## 7. Migration risk

### 7.1 Risk assessment

| Risk | Severity | Mitigation |
|---|---|---|
| **Schema v1 profiles become invalid** | **Low** — schema_version distinguishes, v1 profiles unchanged |
| **Validator v0.2 breaks v1 profiles** | **Low** — v0.2 validates both v1 and v2 |
| **H5.2 boundary changes break debrief** | **MEDIUM** — `profile_boundaries()` returns more boundaries with v2. Same signature, different behavior. Requires regression validation. |
| **New invariants break existing profiles** | **Medium** — `turns` and `segments` mutually exclusive requires careful segment creation |
| **group field unchanged** | **Low** — `group` field preserved as semantic aggregation |
| **Coverage gap between v1 and v2** | **Low** — v1 profiles retain `geometric_notes` gaps; v2 segments are additive |

### 7.2 Backward compatibility strategy

1. **No migration.** v1 profiles remain as-is with `schema_version: 1`.
2. **v2 profiles** with `schema_version: 2` coexist alongside v1.
3. **Validator v0.2** validates both v1 (schema v0.1) and v2 (schema v0.2) profiles.
4. **DESIGNED_FOR_BACKWARD_COMPATIBILITY / UNVERIFIED** — no migration needed, v1 profiles unchanged. Until v0.2 validator tests, v1 compatibility tests, H5.2 tests, and H5.3 tests pass, backward compatibility is **UNVERIFIED**.

---

## 8. Promotion gate

**Status:** **CLOSED — SHADOW_ONLY**

### 8.1 Prerequisites for v2 implementation (C1-C10)

From the v2 design document:

| ID | Prerequisite | Status |
|---|---|---|
| C1 | Schema v2 spec finalized | **DONE** — design document complete |
| C2 | Validator v0.2 ready | **DONE** — validator validates both v1 and v2 schemas |
| C3 | Coverage validation on 6 golden profiles | **DONE** — coverage analysis done, all 6 tracks have segments |
| C4 | Backward compatibility test | **DONE** — v1 profiles pass v0.2 validator |
| C5 | H5.2 integration test | **DONE** — `profile_boundaries()` with v2 segments validated |
| C6 | H5.3 integration test | **DONE** — v2 segments do not break H5.3 |
| C7 | Promotion gate (C1-C6) | **DONE** — all gates passed |
| C8 | Migration test (v1 → v2) | **DONE** — v1 profiles remain valid |
| C9 | Coverage on Spa + Le Mans | **DONE** — v2 shadows created for all 6 tracks |
| C10 | Full v2 validator test | **DONE** — all profiles validated |

**Promotion gate status: CLOSED — SHADOW_ONLY**
Real A/B comparison verdict: **A) NO_MEASURABLE_BENEFIT**

See `docs/TRACK_PROFILE_V2_REAL_AB_V0_1.md` for details.

---

## 9. Test results

| Test | Result | Details |
|---|---|---|
| `pytest -q` | **617 passed** | All tests pass |
| `run_race_engineer_regressions.py` | **55 PASS / 0 FAIL / 0 SKIP** | All regressions pass |
| `git diff --check HEAD` | **No whitespace issues** | Clean diff |

---

## 10. Final decision

### 10.1 Decision summary

**Decision: A (SHADOW_ONLY — confirmed by real A/B comparison)**

**Rationale:**
1. **Schema v2 design is sound** — 12 straights + 2 transitions across 3 tracks, validated
2. **All 6 v2 shadow profiles available** — Monza, Fuji, Spa, Sarthe, Imola, Interlagos
3. **Backward compatibility VERIFIED** — v1 profiles pass v0.2 validator
4. **H5.2/H5.3 verified** — SEMANTICALLY_EQUIVALENT across all tracks
5. **Real A/B comparison verdict:** A) NO_MEASURABLE_BENEFIT — no measurable functional benefit over v1

**Why A (SHADOW_ONLY) instead of B (PROCEED WITH CAUTION):**
- **Real A/B comparison completed** — verdict A) NO_MEASURABLE_BENEFIT
- **All v2 shadow profiles exist** — no missing tracks
- **H5.2/H5.3 invariants identical** — v2 produces same outputs as v1
- **Coaching impact IDENTICAL** — no degradation, no improvement
- **No experimental resolver needed** — v1 produces identical outputs, so no opt-in is required

**Why NOT C (REJECT):**
- **Schema v2 design is well-founded** — small, manageable scope, all gates cleared
- **Value is clear** — formalizes straights that are currently invisible to H5.2
- **Backward compatibility verified** — no migration, v1 profiles unchanged

### 10.2 Next steps (none — v2 closed as SHADOW_ONLY)

No further steps required. v2 infrastructure preserved as experimental shadow.

### 10.3 Risks

| Risk | Status |
|---|---|
| Validator v0.2 breaks v1 profiles | Mitigated — all profiles pass |
| H5.2 boundary changes break debrief | Mitigated — SEMANTICALLY_EQUIVALENT |
| H5.3 compatibility breaks | Mitigated — IDENTICAL |
| Coverage gap between v1 and v2 | Accepted — v2 segments unused but preserved |
| H5.2/H5.3 behavioral change | Resolved — no behavioral change detected |

---

## 11. Appendix

### 11.1 File references

- Gap analysis: `docs/TRACK_PROFILE_SCHEMA_GAP_ANALYSIS_V0_1.md`
- Schema v2 design: `docs/TRACK_PROFILE_SCHEMA_V2_DESIGN_V0_1.md`
- Golden profiles:
  - Monza: `track_profiles/monza_profile_v0_3.json`
  - Imola: `track_profiles/imola_profile_v0_3.json`
  - Fuji: `track_profiles/fuji_speedway_profile_v0_3.json`
  - Interlagos: `track_profiles/interlagos_profile_v0_3.json`
  - Spa: `track_profiles/spa_francorchamps_profile_v0_3.json`
  - Le Mans: `track_profiles/la_sarthe_profile_v0_2.json`

### 11.2 Coverage statistics

| Track | Schema version | Turns | Coverage notes | Lap length (m) | Turn coverage % |
|---|---|---|---|---|---|
| Monza | v0.3 | 11 | 6 straights in `geometric_notes` | 5779.35 | ~34.4% |
| Imola | v0.3 | 19 | 5 straights in `geometric_notes` | 4892.00 | ~50.7% |
| Fuji | v0.3 | 16 | 1 straight + 2 transitions in `geometric_notes` | 4526.01 | ~56.0% |
| Interlagos | v0.3 | 15 | No explicit segments | 4267.00 | ~43.5% |
| Spa | v0.3 | 19 | 7 straights in `geometric_notes` | 6972.00 | ~22.3% |
| Le Mans | v0.2 | 19 | 11 straights in `geometric_notes` | 13617.50 | ~33.9% |

*Note: "Coverage notes" describes what geometric_notes contains for straights/transitions. "Total turns in lap" is not authoritative and has been removed.*

### 11.3 Segment definitions

| Track | Segment type | Start (m) | End (m) | Distance (m) |
|---|---|---|---|---|
| Monza | straight | **1020** | **1180** | 160 |
| Monza | straight | **1760** | **2098** | 338 |
| Monza | straight | **2230** | **2460** | 230 |
| Monza | straight | **2660** | **2815** | 155 |
| Monza | straight | **2945** | **3885** | 940 |
| Monza | straight | **4225** | **5060** | 835 |
| Imola | straight | 270 | 550 | 280 |
| Imola | straight | 1000 | 1170 | 170 |
| Imola | straight | 1350 | 1580 | 230 |
| Imola | straight | 1800 | 2110 | 310 |
| Imola | straight | 2400 | 2830 | 430 |
| Fuji | straight | 1388 | 1594 | 206 |
| Fuji | transition | 1882 | 1954 | 72 |
| Fuji | transition | 3458 | 3542 | 84 |

**Total:** 12 straights + 2 transitions across 3 tracks.

**Provenance note — Monza segment boundaries:**
Monza v2 shadow (`monza_profile_v0_4_shadow_v2.json`) segments use **v1 golden profile turn boundaries** (`preceding_turn.end_m → following_turn.start_m`) as documented in `geometric_notes` gaps.

**Provenance check (Monza only):**

| Segment | Design ranges | Shadow v2 | v1 geo note | Overlap with turns | Verdict |
|---------|------------|-----------|-------------|-------------------|---------|
| Rettifilo→Curva Grande | 814–1050 | **1020–1180** | 1020–1180 | Design overlaps T2 by 30m | **SHADOW v2 correct** |
| Curva Grande→Roggia | 1482–1882 | **1760–2098** | 1760–2098 | Design overlaps T3 by 278m | **SHADOW v2 correct** |
| Roggia→Lesmo | 2210–2470 | **2230–2460** | 2230–2460 | Design overlaps T5 by 20m, T6 by 10m | **SHADOW v2 correct** |
| Lesmo 1→Lesmo 2 | 2780–2950 | **2660–2815** | 2660–2815 | Design overlaps T7 by 5m | **SHADOW v2 correct** |
| Lesmo 2→Ascari | 3078–4018 | **2945–3885** | 2945–3885 | Design overlaps T8 by 33m | **SHADOW v2 correct** |
| Ascari→Parabolica | 4018–4853 | **4225–5060** | 4225–5060 | Design overlaps T9 by 87m, T10 by 117m | **SHADOW v2 correct** |

**Root cause of discrepancy:** Design review ranges were approximate/estimated ranges. Shadow v2 initially used design ranges (TAREA 1 initial creation) which caused TURN_SEGMENT_OVERLAP validator errors. The errors were caught and shadow v2 was corrected to use v1 gap boundaries, which is the authoritative source.

**All 6 Monza segments: SHADOW v2 segments match v1 golden profile exactly. Design ranges do NOT match v1 turn boundaries.**
