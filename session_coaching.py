"""Deterministic session coaching orchestration."""

from coaching_precision import (
    build_p10_plan_presentation,
    build_p11_plan_focus,
    enrich_cues_with_deterministic_priority,
    enrich_patterns_with_precision,
    enrich_plan_items_with_coaching_sequence,
    enrich_plan_items_with_precision,
    enrich_plan_with_p9_presentation_metadata,
)
from deterministic_coaching import (
    THROTTLE_ONSET_SESSION_MIN_DELTA_M,
    THROTTLE_RELEASE_SESSION_MIN_DELTA_M,
    _episode_speed_context_facts,
    _session_brake_release_fact,
    _session_braking_point_fact,
    _session_throttle_onset_fact,
    _session_throttle_release_fact,
    _single_event_direction,
    _steering_direct_action_present,
    build_driver_cues_for_plan_item,
    safe_float,
    safe_int,
)
from session_coaching_intervals import _channel_event_distance_intervals
from session_coaching_location import (
    enrich_items_with_track_location,
    track_location_context_summary,
)
from session_coaching_patterns import (
    _build_repeated_brake_release_patterns,
    _build_repeated_braking_point_patterns,
    _build_repeated_throttle_patterns,
)
from session_coaching_plan import (
    _build_next_stint_plan,
    build_plan_priority_reason,
)
from session_coaching_priority import _build_priority_regions
from session_coaching_quality import build_session_comparison_quality_gate
from session_coaching_recurrence import (
    SESSION_PRIORITY_POLICY_VERSION,
    _apply_recurrence_aware_session_priority,
    _attach_point_anchored_reference_profiles,
    _attach_repeated_throttle_patterns_to_plan,
    _brake_throttle_relation_from_channels,
    _channel_direction_coaching_label,
    _channel_quantitative_fact,
    _comparison_quality_map,
    _priority_ranking_map,
    _sanitize_recurrence_regions,
)
from session_coaching_reference import _attach_reference_action_profiles

SESSION_ACTIONABILITY_POLICY_VERSION = "1.7"

THROTTLE_ONSET_PATTERN_REFERENCE_TOLERANCE_M = 12.0

THROTTLE_RELEASE_PATTERN_REFERENCE_TOLERANCE_M = 12.0

def build_session_coaching_facts(
    valid_comparison_results,
    track_location_context=None,
    source_data=None,
):
    """
    Convierte comparaciones ya validadas en una ficha determinista.

    v3.10.8:
    - priority_findings conserva sólo episodios PRIORITARIOS para el tiebreak;
    - recurrence_findings usa TODOS los episodios coaching-eligible para que la
      recurrencia física no dependa de la clasificación elegida por el LLM;
    - los patrones repetidos sólo se declaran si reaparecen en una región
      espacial compatible y en múltiples comparaciones;
    - Python construye un plan concreto para la próxima tanda;
    - Python distingue secuencia/solapamiento de freno y acelerador;
    - Python resuelve nombres de curva únicamente desde un perfil validado;
    - no se infiere causalidad ni se permite al LLM inventar ubicaciones.
    """
    comparison_order = []
    priority_findings = []
    recurrence_findings = []
    braking_point_findings = []
    brake_release_findings = []
    throttle_onset_findings = []
    throttle_release_findings = []

    comparison_quality_gate = build_session_comparison_quality_gate(
        valid_comparison_results
    )
    comparison_quality_by_key = _comparison_quality_map(
        comparison_quality_gate
    )

    ordered_results = sorted(
        [
            item
            for item in valid_comparison_results
            if (
                isinstance(item, dict)
                and
                item.get("status") == "VALID"
            )
        ],
        key=lambda item: (
            safe_int(
                item.get(
                    "driver_analysis_priority_rank"
                )
            )
            if safe_int(
                item.get(
                    "driver_analysis_priority_rank"
                )
            ) is not None
            else 999999,
            abs(
                safe_float(
                    item.get(
                        "comparison_minus_reference_s"
                    )
                )
                or 0.0
            ),
        ),
    )

    for comparison in ordered_results:
        reference_lap = safe_int(
            comparison.get(
                "reference_lap"
            )
        )
        comparison_lap = safe_int(
            comparison.get(
                "comparison_lap"
            )
        )

        comparison_key = (
            f"{reference_lap}->{comparison_lap}"
            if (
                reference_lap is not None
                and
                comparison_lap is not None
            )
            else "comparison"
        )

        quality = comparison_quality_by_key.get(comparison_key, {})
        session_plan_eligible = bool(quality.get("session_plan_eligible", True))

        comparison_order.append({
            "reference_lap": reference_lap,
            "comparison_lap": comparison_lap,
            "comparison_minus_reference_s": safe_float(
                comparison.get("comparison_minus_reference_s")
            ),
            "driver_analysis_priority_rank": safe_int(
                comparison.get("driver_analysis_priority_rank")
            ),
            "session_plan_eligible": session_plan_eligible,
            "quality_status": quality.get("quality_status", "SESSION_PLAN_ELIGIBLE"),
        })

        if not session_plan_eligible:
            continue

        ranking_map = (
            _priority_ranking_map(
                comparison
            )
        )

        assessment_by_episode = {
            safe_int(item.get("episode_id")): item
            for item in (
                ((comparison.get("llm_structured") or {}).get("episode_assessments", []))
                or []
            )
            if isinstance(item, dict) and safe_int(item.get("episode_id")) is not None
        }

        episodes = [
            item
            for item in (
                comparison.get(
                    "episode_ground_truth",
                    [],
                )
                or []
            )
            if isinstance(item, dict)
        ]

        for episode in episodes:
            episode_id = safe_int(
                episode.get(
                    "episode_id"
                )
            )

            ranking = ranking_map.get(
                episode_id,
                {},
            )

            classification = (
                ranking.get(
                    "classification"
                )
            )

            braking_point = _session_braking_point_fact(
                episode
            )

            if braking_point is not None:
                braking_point_findings.append({
                    "comparison": comparison_key,
                    "reference_lap": reference_lap,
                    "comparison_lap": comparison_lap,
                    "episode_id": episode_id,
                    "classification": classification,
                    "start_distance_m": safe_float(episode.get("start_distance_m")),
                    "end_distance_m": safe_float(episode.get("end_distance_m")),
                    "track_location": episode.get("track_location"),
                    "action_time_loss_s": safe_float(episode.get("action_time_loss_s")),
                    "braking_point": braking_point,
                })

            brake_release = _session_brake_release_fact(
                episode
            )

            if brake_release is not None:
                brake_release_findings.append({
                    "comparison": comparison_key,
                    "reference_lap": reference_lap,
                    "comparison_lap": comparison_lap,
                    "episode_id": episode_id,
                    "classification": classification,
                    "start_distance_m": safe_float(episode.get("start_distance_m")),
                    "end_distance_m": safe_float(episode.get("end_distance_m")),
                    "track_location": episode.get("track_location"),
                    "action_time_loss_s": safe_float(episode.get("action_time_loss_s")),
                    "brake_release": brake_release,
                })

            throttle_onset = _session_throttle_onset_fact(episode)
            if throttle_onset is not None:
                throttle_onset_findings.append({
                    "comparison": comparison_key,
                    "reference_lap": reference_lap,
                    "comparison_lap": comparison_lap,
                    "episode_id": episode_id,
                    "classification": classification,
                    "start_distance_m": safe_float(episode.get("start_distance_m")),
                    "end_distance_m": safe_float(episode.get("end_distance_m")),
                    "track_location": episode.get("track_location"),
                    "action_time_loss_s": safe_float(episode.get("action_time_loss_s")),
                    "throttle_onset": throttle_onset,
                })

            throttle_release = _session_throttle_release_fact(episode)
            if throttle_release is not None:
                throttle_release_findings.append({
                    "comparison": comparison_key,
                    "reference_lap": reference_lap,
                    "comparison_lap": comparison_lap,
                    "episode_id": episode_id,
                    "classification": classification,
                    "start_distance_m": safe_float(episode.get("start_distance_m")),
                    "end_distance_m": safe_float(episode.get("end_distance_m")),
                    "track_location": episode.get("track_location"),
                    "action_time_loss_s": safe_float(episode.get("action_time_loss_s")),
                    "throttle_release": throttle_release,
                })

            channels = []

            evidence_by_channel = (
                episode.get(
                    "action_evidence_by_channel",
                    {},
                )
                or {}
            )

            for channel in (
                episode.get(
                    "action_channels",
                    [],
                )
                or []
            ):
                evidence = (
                    evidence_by_channel.get(
                        channel,
                        {},
                    )
                    if isinstance(
                        evidence_by_channel,
                        dict,
                    )
                    else {}
                )

                direction = (
                    _single_event_direction(
                        evidence
                    )
                )

                channels.append({
                    "channel":
                        channel,
                    "direction":
                        direction,
                    "description":
                        _channel_direction_coaching_label(
                            channel,
                            evidence,
                        ),
                    "quantitative":
                        _channel_quantitative_fact(
                            channel,
                            evidence,
                        ),
                    "event_intervals_m":
                        [
                            [start, end]
                            for start, end in (
                                _channel_event_distance_intervals(
                                    evidence
                                )
                            )
                        ],
                })

            brake_throttle_relation = (
                _brake_throttle_relation_from_channels(
                    channels
                )
            )

            speed_context = (
                _episode_speed_context_facts(
                    episode
                )
            )

            assessment = assessment_by_episode.get(episode_id, {})
            validated_recommendation = str(assessment.get("recommendation") or "").strip()
            steering_coaching_requested = bool(
                validated_recommendation
                and _steering_direct_action_present(validated_recommendation)
                and "steering_magnitude" in set(episode.get("action_channels", []) or [])
            )

            finding = {
                "comparison":
                    comparison_key,
                "reference_lap":
                    reference_lap,
                "comparison_lap":
                    comparison_lap,
                "comparison_minus_reference_s":
                    safe_float(
                        comparison.get(
                            "comparison_minus_reference_s"
                        )
                    ),
                "comparison_priority_rank":
                    safe_int(
                        comparison.get(
                            "driver_analysis_priority_rank"
                        )
                    ),
                "episode_id":
                    episode_id,
                "relative_priority_rank":
                    safe_int(
                        ranking.get(
                            "relative_priority_rank"
                        )
                    ),
                "classification":
                    classification,
                "start_distance_m":
                    safe_float(
                        episode.get(
                            "start_distance_m"
                        )
                    ),
                "end_distance_m":
                    safe_float(
                        episode.get(
                            "end_distance_m"
                        )
                    ),
                "track_location":
                    episode.get(
                        "track_location"
                    ),
                "action_time_loss_s":
                    safe_float(
                        episode.get(
                            "action_time_loss_s"
                        )
                    ),
                "evidence_strength":
                    episode.get(
                        "evidence_strength"
                    ),
                "steering_coaching_requested":
                    steering_coaching_requested,
                "validated_recommendation":
                    validated_recommendation,
                "channels":
                    channels,
                "brake_throttle_relation":
                    brake_throttle_relation,
                "braking_point":
                    braking_point,
                "brake_release":
                    brake_release,
                "throttle_onset":
                    throttle_onset,
                "throttle_release":
                    throttle_release,
                **speed_context,
            }

            # La recurrencia física pertenece al ground truth, no al ranker LLM.
            recurrence_findings.append(finding)

            if classification == "PRIORITARIO":
                priority_findings.append(finding)

    recurrence_findings.sort(
        key=lambda item: (
            item.get("comparison_priority_rank")
            if item.get("comparison_priority_rank") is not None
            else 999999,
            -abs(item.get("action_time_loss_s") or 0.0),
            item.get("start_distance_m")
            if item.get("start_distance_m") is not None
            else 999999.0,
            item.get("episode_id")
            if item.get("episode_id") is not None
            else 999999,
        )
    )

    priority_findings.sort(
        key=lambda item: (
            item.get(
                "comparison_priority_rank"
            )
            if item.get(
                "comparison_priority_rank"
            ) is not None
            else 999999,
            item.get(
                "relative_priority_rank"
            )
            if item.get(
                "relative_priority_rank"
            ) is not None
            else 999999,
            -abs(
                item.get(
                    "action_time_loss_s"
                )
                or 0.0
            ),
        )
    )

    # Regiones de coaching: conservan el filtro PRIORITARIO del ranker, pero
    # su orden interno ya no usa relative_priority_rank como criterio.
    priority_regions = (
        _build_priority_regions(
            priority_findings
        )
    )

    # Capa física independiente del modelo: todos los episodios elegibles
    # alimentan recurrencia, sin cambiar por PRIORITARIO/SECUNDARIO/NO_ACCIONABLE.
    recurrence_regions = _sanitize_recurrence_regions(
        _build_priority_regions(
            recurrence_findings
        )
    )

    enrich_items_with_track_location(
        priority_regions,
        track_location_context,
    )
    enrich_items_with_track_location(
        recurrence_regions,
        track_location_context,
    )

    # v3.10.8: el target mixed de acelerador sólo existe si Python puede
    # explicar la forma observada de la vuelta de referencia.
    _attach_reference_action_profiles(
        priority_regions,
        source_data,
    )
    _attach_reference_action_profiles(
        recurrence_regions,
        source_data,
    )

    repeated_braking_point_patterns = (
        _build_repeated_braking_point_patterns(
            braking_point_findings,
            recurrence_regions,
        )
    )

    repeated_brake_release_patterns = (
        _build_repeated_brake_release_patterns(
            brake_release_findings,
            recurrence_regions,
        )
    )

    repeated_throttle_onset_patterns = (
        _build_repeated_throttle_patterns(
            throttle_onset_findings,
            recurrence_regions,
            fact_key="throttle_onset",
            point_key="reference_onset_m",
            min_delta_m=THROTTLE_ONSET_SESSION_MIN_DELTA_M,
            tolerance_m=THROTTLE_ONSET_PATTERN_REFERENCE_TOLERANCE_M,
            region_field="throttle_onset_patterns",
        )
    )

    repeated_throttle_release_patterns = (
        _build_repeated_throttle_patterns(
            throttle_release_findings,
            recurrence_regions,
            fact_key="throttle_release",
            point_key="reference_release_m",
            min_delta_m=THROTTLE_RELEASE_SESSION_MIN_DELTA_M,
            tolerance_m=THROTTLE_RELEASE_PATTERN_REFERENCE_TOLERANCE_M,
            region_field="throttle_release_patterns",
        )
    )

    # Un patrón físico puede ser válido aunque no haya formado una
    # priority_region. Resolver igualmente su nombre de curva desde el perfil
    # validado usando su intervalo agregado, para TODOS los tipos de punto.
    enrich_items_with_track_location(
        repeated_braking_point_patterns,
        track_location_context,
    )
    enrich_items_with_track_location(
        repeated_brake_release_patterns,
        track_location_context,
    )
    enrich_items_with_track_location(
        repeated_throttle_onset_patterns,
        track_location_context,
    )
    enrich_items_with_track_location(
        repeated_throttle_release_patterns,
        track_location_context,
    )

    # H5.4/P1 — precisión driver-facing derivada. La coordenada LMU absoluta
    # permanece intacta; sólo se añade provenance de vueltas y una referencia
    # relativa a curva cuando existe un perfil validado.
    precision_profile = (
        track_location_context.get("profile")
        if isinstance(track_location_context, dict)
        and track_location_context.get("status") == "ACTIVE"
        else None
    )
    enrich_patterns_with_precision(
        repeated_braking_point_patterns,
        precision_profile,
        event_kind="braking_onset",
        point_key="reference_onset_m",
    )
    enrich_patterns_with_precision(
        repeated_brake_release_patterns,
        precision_profile,
        event_kind="brake_release",
        point_key="reference_release_m",
    )
    enrich_patterns_with_precision(
        repeated_throttle_onset_patterns,
        precision_profile,
        event_kind="throttle_onset",
        point_key="reference_onset_m",
    )
    enrich_patterns_with_precision(
        repeated_throttle_release_patterns,
        precision_profile,
        event_kind="throttle_release",
        point_key="reference_release_m",
    )

    # Patrones usados por el debrief mantienen compatibilidad con el plan de
    # coaching. En paralelo exponemos una capa de recurrencia puramente física.
    repeated_input_patterns = []

    for region in recurrence_regions:
        if (
            region.get(
                "comparison_count",
                0,
            )
            < 2
        ):
            continue

        for repeated in (
            region.get(
                "repeated_differences",
                [],
            )
            or []
        ):
            repeated_input_patterns.append({
                **repeated,
                "region_label":
                    region.get(
                        "region_label"
                    ),
                "start_distance_m":
                    region.get(
                        "start_distance_m"
                    ),
                "end_distance_m":
                    region.get(
                        "end_distance_m"
                    ),
                "track_location":
                    region.get(
                        "track_location"
                    ),
            })

    repeated_input_patterns.sort(
        key=lambda item: (
            -item.get(
                "comparison_count",
                0,
            ),
            -item.get(
                "recurrence_episode_count",
                0,
            ),
            item.get(
                "start_distance_m"
            )
            if item.get(
                "start_distance_m"
            ) is not None
            else 999999.0,
            item.get(
                "description"
            )
            or "",
        )
    )

    recurrence_input_patterns = []

    for region in recurrence_regions:
        if region.get("comparison_count", 0) < 2:
            continue

        for repeated in (region.get("repeated_differences", []) or []):
            recurrence_pattern = {
                **repeated,
                "region_label": region.get("region_label"),
                "start_distance_m": region.get("start_distance_m"),
                "end_distance_m": region.get("end_distance_m"),
                "track_location": region.get("track_location"),
            }
            recurrence_pattern.pop("priority_episode_count", None)
            recurrence_input_patterns.append(recurrence_pattern)

    recurrence_input_patterns.sort(
        key=lambda item: (
            -item.get("comparison_count", 0),
            -item.get("recurrence_episode_count", 0),
            item.get("start_distance_m")
            if item.get("start_distance_m") is not None
            else 999999.0,
            item.get("description") or "",
        )
    )

    next_stint_plan = (
        _build_next_stint_plan(
            recurrence_regions,
            priority_findings,
            max_items=max(
                3,
                len(recurrence_regions) + len(priority_findings),
            ),
        )
    )

    enrich_items_with_track_location(
        next_stint_plan,
        track_location_context,
    )

    _attach_repeated_throttle_patterns_to_plan(
        next_stint_plan,
        repeated_throttle_onset_patterns,
        repeated_throttle_release_patterns,
    )

    next_stint_plan = (
        _apply_recurrence_aware_session_priority(
            next_stint_plan,
            repeated_braking_point_patterns,
            repeated_brake_release_patterns,
            repeated_throttle_onset_patterns,
            repeated_throttle_release_patterns,
        )
    )

    enrich_items_with_track_location(
        next_stint_plan,
        track_location_context,
    )

    # H5.4/P2 — extend the same deterministic precision layer to the final
    # selected plan, including authorized SINGLE physical-point cues.
    enrich_plan_items_with_precision(
        next_stint_plan,
        precision_profile,
    )

    # H5.4/P7 — additive deterministic consolidation of already-authorized
    # physical-point cues. Original patterns remain untouched.
    enrich_plan_items_with_coaching_sequence(next_stint_plan)

    _attach_point_anchored_reference_profiles(
        next_stint_plan,
        source_data,
    )

    for item in next_stint_plan:
        if not isinstance(item, dict):
            continue
        item["driver_cues"] = build_driver_cues_for_plan_item(item, max_cues=2)
        # H5.4/P8 — deterministic driver-facing cue priority ordering
        item["driver_cues"] = enrich_cues_with_deterministic_priority(
            item["driver_cues"],
        )
        item["actionable_cue_count"] = len(item["driver_cues"])

    # H5.4/P9 — deterministic cross-zone driver-plan diversity ordering
    next_stint_plan = enrich_plan_with_p9_presentation_metadata(
        next_stint_plan,
    )

    # H5.4/P10 — deterministic driver-facing plan projection
    next_stint_plan_presentation = build_p10_plan_presentation(next_stint_plan)

    # H5.4/P11 — deterministic driver focus slots
    next_stint_focus = build_p11_plan_focus(next_stint_plan, next_stint_plan_presentation)

    return {
        "track_location_profile":
            track_location_context_summary(
                track_location_context
            ),
        "comparison_quality_gate":
            comparison_quality_gate,
        "comparison_order":
            comparison_order,
        "priority_findings":
            priority_findings,
        "recurrence_findings":
            recurrence_findings,
        "priority_regions":
            priority_regions,
        "recurrence_regions":
            recurrence_regions,
        "repeated_input_patterns":
            repeated_input_patterns,
        "recurrence_input_patterns":
            recurrence_input_patterns,
        "repeated_braking_point_patterns":
            repeated_braking_point_patterns,
        "repeated_brake_release_patterns":
            repeated_brake_release_patterns,
        "repeated_throttle_onset_patterns":
            repeated_throttle_onset_patterns,
        "repeated_throttle_release_patterns":
            repeated_throttle_release_patterns,
        "next_stint_plan":
            next_stint_plan,
        "next_stint_plan_presentation":
            next_stint_plan_presentation,
        "next_stint_focus":
            next_stint_focus,
        "session_priority_policy": {
            "version":
                SESSION_PRIORITY_POLICY_VERSION,
            "method":
                "physical_point_support_then_specificity_then_priority_rank",
            "order":
                [
                    "repeated_physical_point",
                    "single_authorized_physical_point",
                    "reference_action_profile",
                    "other_actionable_evidence",
                    "comparison_priority_rank",
                    "episode_priority_rank",
                    "local_loss_tiebreak",
                    "track_distance_last_tiebreak",
                ],
            "per_comparison_ranker_unchanged":
                True,
            "per_comparison_ranker_used_for_recurrence":
                False,
            "recurrence_source":
                "session_plan_eligible_coaching_episode_ground_truth",
            "comparison_quality_gate":
                "median_mad_candidate_plus_local_severity_confirmation",
            "comparison_quality_exclusion_scope":
                "session_aggregation_only",
            "repeated_input_pattern_source":
                "recurrence_regions",
            "next_stint_plan_source":
                "recurrence_regions_plus_physical_points_profiles_and_validated_priority_steering",
            "temporal_observation_policy":
                "descriptive_only_without_temporal_target",
            "mixed_throttle_target_policy":
                "reference_action_profile_or_omit",
            "mixed_brake_target_policy":
                "reference_action_profile_or_omit",
            "actionability_policy_version":
                SESSION_ACTIONABILITY_POLICY_VERSION,
            "generic_channel_difference_policy":
                "qualitative_reference_alignment_for_unambiguous_brake_throttle; steering_separate_validated_path",
            "steering_target_policy":
                "validated_llm_direct_or_secondary_low_priority_no_causal_claim",
            "driver_cue_limit_per_zone":
                2,
            "reference_action_profile_source": {
                "throttle":
                    "throttle_physical_point_profiles.reference_event",
                "brake":
                    "driver_action_episode_ranking.braking_point_comparison+brake_release_point_comparison",
            },
        },
        "priority_finding_count":
            len(
                priority_findings
            ),
        "recurrence_finding_count":
            len(
                recurrence_findings
            ),
    }
