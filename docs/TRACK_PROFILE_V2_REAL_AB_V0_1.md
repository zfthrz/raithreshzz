# Track Profile v2 Real A/B Shadow Comparison

**Version:** v0.1
**Date:** 2026-08-19T18:47:43.188247+00:00Z
**Tracks compared:** 6
**Telemetry source:** synthetic (no raw telemetry available)

---

## Executive Summary

**Verdict: A) NO_MEASURABLE_BENEFIT**

## Tracks Compared

| # | Track | Layout | V1 Profile | V2 Shadow Profile |
|---|-------|--------|------------|-------------------|
| 1 | Autodromo Nazionale Monza | Autodromo Nazionale Monza | monza_profile_v0_3.json | monza_profile_v0_4_shadow_v2.json |
| 2 | Fuji Speedway | Fuji Speedway | fuji_speedway_profile_v0_3.json | fuji_speedway_profile_v0_4_shadow_v2.json |
| 3 | Circuit de Spa-Francorchamps | Circuit de Spa-Francorchamps | spa_francorchamps_profile_v0_3.json | spa_francorchamps_profile_v0_4_shadow_v2.json |
| 4 | Circuit de la Sarthe | Circuit de la Sarthe | la_sarthe_profile_v0_2.json | la_sarthe_profile_v0_3_shadow_v2.json |
| 5 | Imola | Imola | imola_profile_v0_3.json | imola_profile_v0_4_shadow_v2.json |
| 6 | Interlagos | Interlagos | interlagos_profile_v0_3.json | interlagos_profile_v0_4_shadow_v2.json |

## H5.2 A/B Comparison

Comparing `profile_boundaries()` and `localize_trend_zones()` outputs
between v1 golden and v2 shadow profiles on synthetic H5.2 inputs.

| Track | V1 Candidates | V2 Candidates | Boundaries Identical | Classification |
|-------|---------------|---------------|---------------------|----------------|
| Autodromo Nazionale Monza | 1 | 1 | True | SEMANTICALLY_EQUIVALENT |
| Fuji Speedway | 4 | 4 | True | SEMANTICALLY_EQUIVALENT |
| Circuit de Spa-Francorchamps | 4 | 4 | True | SEMANTICALLY_EQUIVALENT |
| Circuit de la Sarthe | 4 | 4 | True | SEMANTICALLY_EQUIVALENT |
| Imola | 5 | 5 | True | SEMANTICALLY_EQUIVALENT |
| Interlagos | 4 | 4 | True | SEMANTICALLY_EQUIVALENT |

### Localization Improvements

### Unexpected Changes

## Segment Value Assessment

Assessing whether v2 segments add useful localization or are redundant.

| Segment ID | Type | Distance (m) | Adds Localization | Redundant | Fragments | Changes Semantics |
|------------|------|--------------|-------------------|-----------|-----------|-------------------|
| monza_straight_rettifilo_to_curva_grande | straight | 160 | False | False | False | False |
| monza_straight_curva_grande_to_roggia | straight | 338 | False | False | False | False |
| monza_straight_roggia_to_lesmo | straight | 230 | False | False | False | False |
| monza_straight_lesmo_1_to_lesmo_2 | straight | 155 | False | False | False | False |
| monza_straight_lesmo_2_to_ascari | straight | 940 | False | False | False | False |
| monza_straight_ascari_to_parabolica | straight | 835 | False | False | False | False |
| fuji_transition_100r_to_hairpin | transition | 72 | False | False | False | False |
| fuji_transition_gr_supra_to_panasonic | transition | 84 | False | False | False | False |
| spa_straight_la_source_to_eau_rouge | straight | 544 | False | False | False | False |
| spa_straight_eau_rouge_to_les_combes | straight | 958 | False | False | False | False |
| spa_straight_malmedy_to_bruxelles | straight | 232 | False | False | False | False |
| spa_straight_jacky_ickx_to_pouhon | straight | 364 | False | False | False | False |
| spa_straight_pouhon_to_fagnes | straight | 230 | False | False | False | False |
| spa_straight_curve_paul_frere_to_blanchimont | straight | 280 | False | False | False | False |
| spa_straight_blanchimont_to_bus_stop | straight | 398 | False | False | False | False |
| sarthe_straight_tertre_rouge_to_daytona | straight | 1740 | False | False | False | False |
| sarthe_straight_daytona_to_michelin | straight | 1600 | False | False | False | False |
| sarthe_straight_michelin_to_mulsanne | straight | 1160 | False | False | False | False |
| sarthe_straight_mulsanne_to_indianapolis | straight | 1720 | False | False | False | False |
| sarthe_straight_arnage_to_porsche | straight | 1040 | False | False | False | False |
| sarthe_straight_karting_essse2_to_ford_chicanes | straight | 260 | False | False | False | False |
| imola_straight_tamburello_to_villeneuve | straight | 280 | False | False | False | False |
| imola_straight_villeneuve_to_tosa | straight | 170 | False | False | False | False |
| imola_straight_tosa_to_piratella | straight | 230 | False | False | False | False |
| imola_straight_acque_minerali_to_gresini | straight | 310 | False | False | False | False |
| imola_straight_gresini_to_rivazza | straight | 430 | False | False | False | False |
| interlagos_straight_senna_to_descida_lago | straight | 596 | False | False | False | False |
| interlagos_straight_descida_lago_to_ferradura | straight | 282 | False | False | False | False |
| interlagos_straight_pinheirinho_to_bico_de_pato | straight | 164 | False | False | False | False |
| interlagos_straight_mergulho_to_juncao | straight | 136 | False | False | False | False |
| interlagos_straight_subida_dos_boxes_to_arquibancadas | straight | 130 | False | False | False | False |

## H5.3 A/B Comparison

H5.3 shadow pipeline is profile-independent — identical inputs produce
identical outputs regardless of v1/v2 context.

| Track | Eligibility Status | Eligible | Selected | Invariants Preserved |
|-------|-------------------|----------|----------|---------------------|
| Autodromo Nazionale Monza | UNKNOWN | 0 | 0 | True |
| Fuji Speedway | UNKNOWN | 0 | 0 | True |
| Circuit de Spa-Francorchamps | UNKNOWN | 0 | 0 | True |
| Circuit de la Sarthe | UNKNOWN | 0 | 0 | True |
| Imola | UNKNOWN | 0 | 0 | True |
| Interlagos | UNKNOWN | 0 | 0 | True |

## Coaching Impact

| Track | Impact | V1=V2 Boundaries | Invariants Preserved |
|-------|--------|-----------------|---------------------|
| Autodromo Nazionale Monza | IDENTICAL | True | True |
| Fuji Speedway | IDENTICAL | True | True |
| Circuit de Spa-Francorchamps | IDENTICAL | True | True |
| Circuit de la Sarthe | IDENTICAL | True | True |
| Imola | IDENTICAL | True | True |
| Interlagos | IDENTICAL | True | True |

## Overall Metrics

- **V1 Candidates (total):** 22
- **V2 Candidates (total):** 22
- **Added splits (total):** 0
- **Removed candidates (total):** 0
- **Same semantics:** 6
- **Localization improvements:** 0
- **Unexpected changes:** 0
- **H5.3 action differences:** 0

## Fail-Closed Analysis

All v2 shadow handling follows fail-closed principles:

- `profile_boundaries()` only iterates turns (identical v1/v2)
- `find_validated_track_profile()` raises `ValueError` when both coexist
- H5.3 pipeline is profile-independent (no v2 dependency)
- v2 segments are localization-only (no coaching semantics)
- No production code was modified

## Implementation Details

- **Script:** `audit_track_profile_v2_real_ab.py`
- **Synthetic input:** `localize_trend_zones()` with synthetic distance/time arrays
- **H5.3 input:** `_make_synthetic_h53_dataset()` with descending delta values
- **No telemetry required:** All inputs derived from profile boundaries
- **No production modification:** Script is shadow-only

## Output Files

- `data/generated/track_profile_v2_real_ab/track_profile_v2_real_ab_result.json`
- `docs/TRACK_PROFILE_V2_REAL_AB_V0_1.md` (this file)
