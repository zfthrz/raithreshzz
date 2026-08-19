# Track Profile Schema v2 — Promotion Gate Decision

**Date:** 2026-08-19
**Status:** CLOSED — SHADOW_ONLY
**Decision:** A (Keep v2 shadow-only)

---

## 0. Closure summary

**Real A/B comparison completed.** See `docs/TRACK_PROFILE_V2_REAL_AB_V0_1.md`.

| Metric | Value |
|--------|-------|
| Tracks compared | 6 |
| v2 shadow profiles available | 6 / 6 |
| H5.2 A/B classification | SEMANTICALLY_EQUIVALENT (all) |
| H5.3 invariants | IDENTICAL (all) |
| Coaching impact | IDENTICAL (all) |
| v2 segments assessed | 32 |
| Verdict | **A) NO_MEASURABLE_BENEFIT** |
| Promotion gate | **BLOCKED_BY_NO_MEASURABLE_BENEFIT** |
| pytest | 728 / 728 passed |
| Regressions | 55 / 55 passed |

**Result:** v2 shadow is technically validated and production-safe, but the real
A/B comparison demonstrated **no measurable functional benefit** over v1 across
all six tracks. v2 stays SHADOW_ONLY. No production code was modified.

---

## 1. Evidence Completeness

### What exists

| # | Track | v1 Golden | v2 Shadow | Status |
|---|-------|-----------|-----------|--------|
| 1 | Autodromo Nazionale Monza | `monza_profile_v0_3.json` (VALIDATED_MULTI_SESSION) | `shadow_v2/monza_profile_v0_4_shadow_v2.json` | Shadow-test validated |
| 2 | Fuji Speedway | `fuji_speedway_profile_v0_3.json` (VALIDATED_MULTI_SESSION) | `shadow_v2/fuji_speedway_profile_v0_4_shadow_v2.json` | Shadow-test validated |
| 3 | Circuit de Spa-Francorchamps | `spa_francorchamps_profile_v0_3.json` (VALIDATED_MULTI_SESSION) | `shadow_v2/spa_francorchamps_profile_v0_4_shadow_v2.json` | Shadow-test validated |
| 4 | Circuit de la Sarthe | `la_sarthe_profile_v0_2.json` (VALIDATED_MULTI_SESSION) | `shadow_v2/la_sarthe_profile_v0_3_shadow_v2.json` | Shadow-test validated |
| 5 | Imola | `imola_profile_v0_3.json` (VALIDATED_MULTI_SESSION) | `shadow_v2/imola_profile_v0_4_shadow_v2.json` | Shadow-test validated |
| 6 | Interlagos | `interlagos_profile_v0_3.json` (VALIDATED_MULTI_SESSION) | `shadow_v2/interlagos_profile_v0_4_shadow_v2.json` | Shadow-test validated |

**All 6 v2 shadow profiles now available.**

### Validated artifacts

- **v1 vs v2 real A/B comparison:** `audit_track_profile_v2_real_ab.py` — `docs/TRACK_PROFILE_V2_REAL_AB_V0_1.md`
- **H5.2 A/B classification:** SEMANTICALLY_EQUIVALENT (all 6 tracks)
- **H5.3 invariants:** IDENTICAL (all 6 tracks)
- **Coaching impact:** IDENTICAL (all 6 tracks)
- **Real telemetry replay:** not required (verdict NO_MEASURABLE_BENEFIT)
- **H5.2 output equivalence:** tested with synthetic inputs, confirmed
- **H5.3 candidate equivalence:** tested with synthetic inputs, confirmed

### v2 segment structure

All existing v2 shadows follow the same structure:
- `schema_version: 2`
- All v1 `turns` array preserved unchanged
- `segments` array added with `straight_real_track_feature` classification
- Segment types restricted to `straight` or `transition`
- No coaching authority fields (no brake/throttle/speed/time)

Monza v2 example: 11 turns + 6 segments (Rettifilo, Curva Grande→Roggia, Roggia→Lesmo, Lesmo→Lesmo, Lesmo→Ascari, Ascari→Parabolica)
Spa v2 example: 19 turns + 7 segments (La Source→Eau Rouge 544m, Eau Rouge→Les Combes 958m, Malmedy→Bruxelles 232m, Jacky Ickx→Pouhon 364m, Pouhon→Fagnes 230m, Curve Paul Frere→Blanchimont 280m, Blanchimont→Bus Stop 398m)

---

## 2. Runtime Value

### What v2 segments provide

- Explicit `straight_real_track_feature` boundaries between turns
- Segments are **localization context only**, not coaching authority
- Segment provenance: `v1 straight gap documentation` — derived from existing v1 `geometric_notes` gap explanations
- No change to `profile_boundaries()` — turn boundaries unchanged
- No change to `localize_trend_zones()` — uses turn boundaries, not segments

### What v2 does NOT provide

- No change to H5.2 zone-splitting behavior (uses turn boundaries)
- No change to H5.3 candidate generation (based on turns)
- No change to coaching output (turn-based)
- No new coaching authority
- No new decision paths in the pipeline

### Current test results

- H5.2 shadow: 728 tests, 0 failures
- H5.3 shadow: 728 tests, 0 failures
- Full pytest: 728 tests, 0 failures

### Real value assessment

**Low immediate value:** segments are purely localization context with no pipeline integration.

**Potential future value:** if `localize_trend_zones()` or H5.2 zone-splitting were extended to consume `segments` array, v2 would provide explicit acceleration corridor boundaries. Currently segments are **not consumed** by any production code.

---

## 3. Production Risk

### Current behavior

- Resolver: `find_validated_track_profile()` matches on `status` + `track` + `layout`
- `profile_boundaries()`: extracts start/end from turns, ignores schema_version
- `localize_trend_zones()`: uses turn boundaries, ignores segments
- Shadow profiles are **physically isolated** in `shadow_v2/` subdirectory

### What happens if v2 shadows were accidentally included in production

If `find_validated_track_profile()` discovered `shadow_v2/` files:
- **Low risk:** turn boundaries would be extracted correctly (same as v1)
- **No coaching change:** segments are localization-only, no coaching fields
- **No pipeline change:** H5.2/H5.3 use turns, not segments

### Fail-closed behavior

- Malformed v2 JSON → resolver returns `None`
- Unknown segment ID → `profile_boundaries()` returns turn boundaries only
- Uncovered regions → no crash, no invented coaching
- v2 profile with no segments → works like v1

### Risk assessment

**Current (shadow-isolated): LOW** — shadows physically isolated, production untouched
**If accidentally included: LOW** — turn boundaries unchanged, fail-closed
**If segments integrated: MEDIUM** — zone-splitting behavior would change, requires real telemetry validation

---

## 4. Experimental Resolver Option

### Option A: No change (current)

- Keep `shadow_v2/` physically isolated
- No resolver change
- No production benefit

### Option B: Explicit opt-in v2 resolver (recommended)

- Add `find_validated_track_profile_v2()` or parameter to resolver
- Allows gradual rollout without changing existing behavior
- Experimental: v2 shadows testable without affecting production

### Option C: Implicit glob pattern match

- Add `schema_version=2` to resolver's glob pattern
- Would discover shadow files automatically
- Higher risk of unexpected behavior changes

### Recommendation: Option B

- **Low risk:** opt-in, no change to existing resolver
- **High flexibility:** allows v2 testing with real sessions
- **Clear separation:** v1 vs v2 behavior visible

---

## 5. Production Promotion Requirements

### Before v2 can be promoted to production

1. **All circuits need v2 shadows** (Imola and Interlagos missing)
2. **Real telemetry replay** for each v2 shadow — test against actual LMU sessions
3. **H5.2 output equivalence test** — v1 vs v2 output must be equivalent or explainable
4. **H5.3 candidate equivalence test** — v2 shadow candidates must match v1 behavior
5. **New-session validation** — at least one real session per track with v2 shadow
6. **Decision on v2 zones vs v1 zones** — if v2 segments are integrated, what's the zone-splitting preference?
7. **If v2 is promoted:** `shadow_v2/` must be physically isolated from production resolver

### Minimum viable promotion criteria

- At least 2 circuits with real telemetry replay
- H5.2 output equivalence confirmed
- H5.3 candidate equivalence confirmed
- No regression in existing v1 output

### Implementation plan for promotion

1. Create Imola v2 shadow
2. Create Interlagos v2 shadow
3. Run H5.2 v1 vs v2 output equivalence test with real sessions
4. Run H5.3 v1 vs v2 candidate equivalence test with real sessions
5. Decide on v2 vs v1 zone preference
6. If v2 preferred: promote via experimental resolver (opt-in)

---

## 6. Decision

### Option A: Keep v2 shadow-only (not promoted)

**Pros:**
- No production risk
- All tests pass
- Shadow isolation preserved
- No immediate maintenance cost
- **Real A/B comparison completed: NO_MEASURABLE_BENEFIT**

**Cons:**
- v2 validated with synthetic inputs, not real telemetry
- No benefit for production
- v2 segments are unused localization context
- Future v2 integration would require full validation

**Verdict:** CONFIRMED — v2 stays SHADOW_ONLY.

### Option B: Promote v2 with experimental resolver

**Status:** CANCELLED — real A/B comparison showed NO_MEASURABLE_BENEFIT.
No experimental resolver is needed when v1 produces identical outputs.

### Option C: Promote v2 to production (replace v1)

**Status:** CANCELLED — real A/B comparison showed NO_MEASURABLE_BENEFIT.

**Verdict:** Not recommended.

---

## 7. Closure status

**Status:** CLOSED — SHADOW_ONLY
**Decision:** A (Keep v2 shadow-only)

### Rationale

1. **All 6 v2 shadow profiles available** — Monza, Fuji, Spa, Sarthe, Imola, Interlagos
2. **Real A/B comparison completed** — verdict A) NO_MEASURABLE_BENEFIT
3. **H5.2 A/B classification:** SEMANTICALLY_EQUIVALENT (all 6 tracks)
4. **H5.3 invariants:** IDENTICAL (all 6 tracks)
5. **Coaching impact:** IDENTICAL (all 6 tracks)
6. **32 v2 segments assessed** — none add measurable localization value
7. **Production v1 authority unchanged** — no code modified

### Runtime promotion status

```
PROMOTION_GATE: BLOCKED_BY_NO_MEASURABLE_BENEFIT
```

### Conditions to re-open v2

v2 may be re-opened only if a real-world case demonstrates:
- v1 localization is insufficient for a track (e.g. Spa 22.3% turn coverage),
- candidate splitting would benefit from explicit straight/transition segments,
- or v2 segments contribute measurable functional evidence.

### What to preserve

- `track_profiles/shadow_v2/` — all 6 v2 shadow profiles
- `audit_track_profile_v2_real_ab.py` — the real A/B comparison script
- `data/generated/track_profile_v2_real_ab/track_profile_v2_real_ab_result.json` — JSON audit artifact
- `docs/TRACK_PROFILE_V2_REAL_AB_V0_1.md` — generated documentation
- `docs/TRACK_PROFILE_SCHEMA_V2_FINAL_REVIEW_V0_1.md` — final review (updated below)

**Do NOT delete v2 shadow infrastructure.** It remains experimental.
