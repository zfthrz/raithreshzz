import json
import os
import re
import sys


# ============================================================
# RACE ENGINEER - LLM OUTPUT VALIDATOR v1.0
# ============================================================
#
# Valida el archivo *_llm_analysis.json generado por
# llm_analysis.py v3.8.2+.
#
# No llama a Ollama.
# No necesita DuckDB.
# No modifica archivos.
#
# Uso:
#
#   python validate_llm_analysis_output.py "archivo_llm_analysis.json"
#
# Objetivo:
# detectar regresiones como las observadas en:
#
# - llm_analysis v3.8:
#   * tiempos de episodio usados como tiempos de vuelta
#   * delta de episodio usado como delta total
#
# - llm_analysis v3.8.1:
#   * episodios omitidos
#   * ground truth ignorado
#
# ============================================================


ALLOWED_CLASSIFICATIONS = {
    "PRIORITARIO",
    "SECUNDARIO",
    "NO_ACCIONABLE",
}


def safe_float(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    if value != value:
        return None

    if value in (
        float("inf"),
        float("-inf"),
    ):
        return None

    return value


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def approx_equal(
    a,
    b,
    tolerance=1e-9,
):
    a = safe_float(a)
    b = safe_float(b)

    if a is None or b is None:
        return False

    return abs(a - b) <= tolerance


def load_json(path):
    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if not isinstance(
        data,
        dict,
    ):
        raise ValueError(
            "La raíz del JSON debe ser un objeto."
        )

    return data


def contains_digit(text):
    return (
        isinstance(text, str)
        and
        re.search(r"\d", text)
        is not None
    )


def validate_text_list_no_digits(
    value,
    path,
    errors,
):
    if not isinstance(
        value,
        list,
    ):
        errors.append(
            f"{path}: debe ser lista."
        )
        return

    for index, item in enumerate(
        value
    ):
        item_path = (
            f"{path}[{index}]"
        )

        if not isinstance(
            item,
            str,
        ):
            errors.append(
                f"{item_path}: debe ser texto."
            )
            continue

        if contains_digit(
            item
        ):
            errors.append(
                f"{item_path}: contiene cifras "
                "que deberían provenir de Python."
            )


def validate_metadata(
    data,
    errors,
    warnings,
):
    metadata = data.get(
        "metadata"
    )

    if not isinstance(
        metadata,
        dict,
    ):
        errors.append(
            "metadata ausente o inválida."
        )
        return

    version = str(
        metadata.get(
            "llm_analysis_version",
            "",
        )
    )

    if not version:
        errors.append(
            "metadata.llm_analysis_version ausente."
        )

    structured_validation = metadata.get(
        "structured_validation"
    )

    if version >= "3.8.2":
        if structured_validation != "PASS":
            errors.append(
                "metadata.structured_validation "
                "debe ser PASS para v3.8.2+."
            )

    if not metadata.get(
        "track"
    ):
        warnings.append(
            "metadata.track está vacío."
        )

    if metadata.get(
        "reference_lap"
    ) is None:
        warnings.append(
            "metadata.reference_lap ausente."
        )


def validate_ground_truth(
    comparison,
    index,
    errors,
):
    base = f"comparisons[{index}]"

    gt = comparison.get(
        "ground_truth"
    )

    if not isinstance(
        gt,
        dict,
    ):
        errors.append(
            f"{base}.ground_truth ausente."
        )
        return

    pairs = (
        (
            "reference_lap",
            "reference_lap",
        ),
        (
            "comparison_lap",
            "comparison_lap",
        ),
        (
            "reference_time_s",
            "reference_time_s",
        ),
        (
            "comparison_time_s",
            "comparison_time_s",
        ),
        (
            "comparison_minus_reference_s",
            "comparison_minus_reference_s",
        ),
    )

    for gt_key, direct_key in pairs:
        gt_value = gt.get(
            gt_key
        )

        direct_value = comparison.get(
            direct_key
        )

        if gt_key.endswith(
            "_s"
        ):
            same = approx_equal(
                gt_value,
                direct_value,
            )
        else:
            same = (
                safe_int(gt_value)
                ==
                safe_int(direct_value)
            )

        if not same:
            errors.append(
                f"{base}: ground_truth.{gt_key} "
                f"no coincide con {direct_key}."
            )

    reference_time = safe_float(
        gt.get(
            "reference_time_s"
        )
    )

    comparison_time = safe_float(
        gt.get(
            "comparison_time_s"
        )
    )

    delta = safe_float(
        gt.get(
            "comparison_minus_reference_s"
        )
    )

    if (
        reference_time is not None
        and
        comparison_time is not None
        and
        delta is not None
    ):
        calculated = (
            comparison_time
            -
            reference_time
        )

        if not approx_equal(
            calculated,
            delta,
            tolerance=1e-6,
        ):
            errors.append(
                f"{base}: delta ground truth incorrecto. "
                f"B-A={calculated:+.9f}, "
                f"guardado={delta:+.9f}."
            )


def validate_episode_contract(
    comparison,
    index,
    errors,
):
    base = f"comparisons[{index}]"

    episode_gt = comparison.get(
        "episode_ground_truth"
    )

    structured = comparison.get(
        "llm_structured"
    )

    if not isinstance(
        episode_gt,
        list,
    ):
        errors.append(
            f"{base}.episode_ground_truth "
            "debe ser lista."
        )
        return

    declared_count = safe_int(
        comparison.get(
            "driver_action_episode_count"
        )
    )

    if declared_count is None:
        errors.append(
            f"{base}.driver_action_episode_count "
            "ausente."
        )
    elif declared_count != len(
        episode_gt
    ):
        errors.append(
            f"{base}: driver_action_episode_count="
            f"{declared_count}, pero episode_ground_truth "
            f"contiene {len(episode_gt)}."
        )

    gt_ids = []

    for pos, episode in enumerate(
        episode_gt,
        start=1,
    ):
        if not isinstance(
            episode,
            dict,
        ):
            errors.append(
                f"{base}.episode_ground_truth[{pos - 1}] "
                "no es objeto."
            )
            continue

        episode_id = safe_int(
            episode.get(
                "episode_id"
            )
        )

        gt_ids.append(
            episode_id
        )

        if episode_id != pos:
            errors.append(
                f"{base}: episode_id esperado={pos}, "
                f"recibido={episode_id}."
            )

        action_channels = episode.get(
            "action_channels",
            [],
        )

        if (
            isinstance(
                action_channels,
                list,
            )
            and
            "speed" in action_channels
        ):
            errors.append(
                f"{base}: episodio {episode_id} "
                "contiene speed como action_channel."
            )

    if not isinstance(
        structured,
        dict,
    ):
        errors.append(
            f"{base}.llm_structured ausente."
        )
        return

    assessments = structured.get(
        "episode_assessments"
    )

    if not isinstance(
        assessments,
        list,
    ):
        errors.append(
            f"{base}.llm_structured."
            "episode_assessments debe ser lista."
        )
        return

    if len(
        assessments
    ) != len(
        episode_gt
    ):
        errors.append(
            f"{base}: LLM devolvió "
            f"{len(assessments)} assessments para "
            f"{len(episode_gt)} episodios."
        )

    assessment_ids = []

    for assessment in assessments:
        if not isinstance(
            assessment,
            dict,
        ):
            errors.append(
                f"{base}: assessment inválido."
            )
            continue

        episode_id = safe_int(
            assessment.get(
                "episode_id"
            )
        )

        assessment_ids.append(
            episode_id
        )

        classification = assessment.get(
            "classification"
        )

        if classification not in (
            ALLOWED_CLASSIFICATIONS
        ):
            errors.append(
                f"{base}: episodio {episode_id} "
                f"tiene classification inválida: "
                f"{classification}"
            )

        interpretation = assessment.get(
            "interpretation"
        )

        if not isinstance(
            interpretation,
            str,
        ):
            errors.append(
                f"{base}: episodio {episode_id} "
                "interpretation inválida."
            )
        elif contains_digit(
            interpretation
        ):
            errors.append(
                f"{base}: episodio {episode_id} "
                "interpretation contiene cifras."
            )

        recommendation = assessment.get(
            "recommendation"
        )

        if not isinstance(
            recommendation,
            str,
        ):
            errors.append(
                f"{base}: episodio {episode_id} "
                "recommendation inválida."
            )
        elif contains_digit(
            recommendation
        ):
            errors.append(
                f"{base}: episodio {episode_id} "
                "recommendation contiene cifras."
            )

        validate_text_list_no_digits(
            assessment.get(
                "hypotheses"
            ),
            (
                f"{base}.episode_assessments."
                f"{episode_id}.hypotheses"
            ),
            errors,
        )

    if len(
        assessment_ids
    ) != len(
        set(assessment_ids)
    ):
        errors.append(
            f"{base}: episode_id duplicados "
            "en llm_structured."
        )

    if sorted(
        item
        for item in assessment_ids
        if item is not None
    ) != sorted(
        item
        for item in gt_ids
        if item is not None
    ):
        errors.append(
            f"{base}: IDs de assessments "
            "no coinciden con episode_ground_truth."
        )

    validate_text_list_no_digits(
        structured.get(
            "comparison_observations"
        ),
        (
            f"{base}.llm_structured."
            "comparison_observations"
        ),
        errors,
    )

    validate_text_list_no_digits(
        structured.get(
            "limitations"
        ),
        (
            f"{base}.llm_structured."
            "limitations"
        ),
        errors,
    )

    conclusion = structured.get(
        "conclusion"
    )

    if not isinstance(
        conclusion,
        str,
    ):
        errors.append(
            f"{base}.llm_structured.conclusion "
            "debe ser texto."
        )
    elif contains_digit(
        conclusion
    ):
        errors.append(
            f"{base}.llm_structured.conclusion "
            "contiene cifras."
        )


def validate_rendered_comparison(
    comparison,
    index,
    errors,
    warnings,
):
    base = f"comparisons[{index}]"

    analysis = comparison.get(
        "analysis"
    )

    if not isinstance(
        analysis,
        str,
    ):
        errors.append(
            f"{base}.analysis ausente."
        )
        return

    if (
        "No disponible en datos"
        in analysis
    ):
        errors.append(
            f"{base}.analysis contiene "
            "'No disponible en datos'."
        )

    gt = comparison.get(
        "ground_truth",
        {},
    )

    reference_time = safe_float(
        gt.get(
            "reference_time_s"
        )
    )

    comparison_time = safe_float(
        gt.get(
            "comparison_time_s"
        )
    )

    delta = safe_float(
        gt.get(
            "comparison_minus_reference_s"
        )
    )

    expected_strings = []

    if reference_time is not None:
        expected_strings.append(
            f"{reference_time:.4f} s"
        )

    if comparison_time is not None:
        expected_strings.append(
            f"{comparison_time:.4f} s"
        )

    if delta is not None:
        expected_strings.append(
            f"{delta:+.4f} s"
        )

    for expected in expected_strings:
        if expected not in analysis:
            errors.append(
                f"{base}.analysis no contiene "
                f"ground truth renderizado: {expected}"
            )

    episode_count = safe_int(
        comparison.get(
            "driver_action_episode_count"
        )
    )

    if episode_count is not None:
        for episode_id in range(
            1,
            episode_count + 1,
        ):
            token = (
                f"Episodio #{episode_id}"
            )

            if token not in analysis:
                errors.append(
                    f"{base}.analysis no menciona "
                    f"{token}."
                )

    causal_phrases = (
        "causó exactamente",
        "problema de motor",
        "pérdida de potencia",
        "problema de transmisión",
    )

    analysis_lower = (
        analysis.lower()
    )

    for phrase in causal_phrases:
        if phrase in analysis_lower:
            warnings.append(
                f"{base}.analysis contiene frase "
                f"sospechosa: '{phrase}'."
            )


def validate_global_structured(
    data,
    errors,
):
    structured = data.get(
        "global_structured"
    )

    if not isinstance(
        structured,
        dict,
    ):
        errors.append(
            "global_structured ausente."
        )
        return

    for field in (
        "opportunities",
        "repeated_observations",
        "hypotheses",
        "limitations",
        "next_session_priorities",
    ):
        validate_text_list_no_digits(
            structured.get(
                field
            ),
            f"global_structured.{field}",
            errors,
        )

    conclusion = structured.get(
        "conclusion"
    )

    if not isinstance(
        conclusion,
        str,
    ):
        errors.append(
            "global_structured.conclusion "
            "debe ser texto."
        )
    elif contains_digit(
        conclusion
    ):
        errors.append(
            "global_structured.conclusion "
            "contiene cifras."
        )


def validate_global_render(
    data,
    errors,
):
    analysis = data.get(
        "global_analysis"
    )

    if not isinstance(
        analysis,
        str,
    ):
        errors.append(
            "global_analysis ausente."
        )
        return

    if (
        "No disponible en datos"
        in analysis
    ):
        errors.append(
            "global_analysis contiene "
            "'No disponible en datos'."
        )

    comparisons = data.get(
        "comparisons",
        [],
    )

    for index, comparison in enumerate(
        comparisons
    ):
        gt = comparison.get(
            "ground_truth",
            {},
        )

        reference_time = safe_float(
            gt.get(
                "reference_time_s"
            )
        )

        comparison_time = safe_float(
            gt.get(
                "comparison_time_s"
            )
        )

        delta = safe_float(
            gt.get(
                "comparison_minus_reference_s"
            )
        )

        # El global no necesita repetir cada tiempo dos veces,
        # pero debe incluir al menos los tiempos y delta
        # autoritativos de cada comparación analizada.

        expected = []

        if reference_time is not None:
            expected.append(
                f"{reference_time:.4f} s"
            )

        if comparison_time is not None:
            expected.append(
                f"{comparison_time:.4f} s"
            )

        if delta is not None:
            expected.append(
                f"{delta:+.4f} s"
            )

        for token in expected:
            if token not in analysis:
                errors.append(
                    "global_analysis no contiene "
                    f"ground truth de comparación "
                    f"{index}: {token}"
                )


def validate_file(
    path,
):
    data = load_json(
        path
    )

    errors = []
    warnings = []

    validate_metadata(
        data,
        errors,
        warnings,
    )

    comparisons = data.get(
        "comparisons"
    )

    if not isinstance(
        comparisons,
        list,
    ):
        errors.append(
            "comparisons ausente o inválido."
        )
        comparisons = []

    if not comparisons:
        errors.append(
            "No hay comparaciones."
        )

    for index, comparison in enumerate(
        comparisons
    ):
        if not isinstance(
            comparison,
            dict,
        ):
            errors.append(
                f"comparisons[{index}] no es objeto."
            )
            continue

        status = comparison.get(
            "status"
        )

        if status != "VALID":
            errors.append(
                f"comparisons[{index}].status "
                f"no es VALID: {status}"
            )

        validate_ground_truth(
            comparison,
            index,
            errors,
        )

        validate_episode_contract(
            comparison,
            index,
            errors,
        )

        validate_rendered_comparison(
            comparison,
            index,
            errors,
            warnings,
        )

    validate_global_structured(
        data,
        errors,
    )

    validate_global_render(
        data,
        errors,
    )

    return errors, warnings


def main():
    print()
    print("=" * 60)
    print("RACE ENGINEER - LLM OUTPUT VALIDATOR v1.0")
    print("=" * 60)
    print()

    if len(
        sys.argv
    ) != 2:
        print(
            "Uso:"
        )
        print()
        print(
            'python validate_llm_analysis_output.py '
            '"archivo_llm_analysis.json"'
        )
        sys.exit(2)

    path = os.path.abspath(
        sys.argv[1]
    )

    if not os.path.exists(
        path
    ):
        print(
            f"ERROR: no existe:\n{path}"
        )
        sys.exit(2)

    print(
        f"Archivo:\n{path}"
    )
    print()

    try:
        errors, warnings = (
            validate_file(
                path
            )
        )
    except Exception as exc:
        print(
            "VALIDATOR ERROR"
        )
        print(
            str(exc)
        )
        sys.exit(2)

    if warnings:
        print(
            "WARNINGS"
        )
        print(
            "-" * 60
        )

        for warning in warnings:
            print(
                f"- {warning}"
            )

        print()

    if errors:
        print(
            "REGRESSION VALIDATION: FAIL"
        )
        print(
            "-" * 60
        )

        for error in errors:
            print(
                f"- {error}"
            )

        print()
        print(
            f"Errores: {len(errors)}"
        )

        sys.exit(1)

    print(
        "REGRESSION VALIDATION: PASS"
    )

    if warnings:
        print(
            f"Warnings: {len(warnings)}"
        )
    else:
        print(
            "Warnings: 0"
        )

    print()
    print(
        "Ground truth, contrato de episodios "
        "y render final consistentes."
    )


if __name__ == "__main__":
    main()
