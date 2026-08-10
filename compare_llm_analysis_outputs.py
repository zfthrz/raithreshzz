import json
import os
import sys


# ============================================================
# RACE ENGINEER - LLM ANALYSIS COMPARATOR v1.0
# ============================================================
#
# Compara dos archivos *_llm_analysis.json.
#
# Diseñado especialmente para comparar:
#   v3.8 / v3.8.1 / v3.8.2+
#
# No llama a Ollama.
# No modifica archivos.
#
# Uso:
#
#   python compare_llm_analysis_outputs.py old.json new.json
#
# ============================================================


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
            "La raíz debe ser un objeto JSON."
        )

    return data


def version(data):
    return str(
        data.get(
            "metadata",
            {},
        ).get(
            "llm_analysis_version",
            "unknown",
        )
    )


def source_version(data):
    return str(
        data.get(
            "metadata",
            {},
        ).get(
            "source_analysis_version",
            "unknown",
        )
    )


def track(data):
    return data.get(
        "metadata",
        {},
    ).get(
        "track"
    )


def comparison_key(
    comparison,
):
    return (
        safe_int(
            comparison.get(
                "reference_lap"
            )
        ),
        safe_int(
            comparison.get(
                "comparison_lap"
            )
        ),
    )


def comparison_map(data):
    result = {}

    comparisons = data.get(
        "comparisons",
        [],
    )

    if not isinstance(
        comparisons,
        list,
    ):
        return result

    for comparison in comparisons:
        if not isinstance(
            comparison,
            dict,
        ):
            continue

        result[
            comparison_key(
                comparison
            )
        ] = comparison

    return result


def ground_truth(
    comparison,
):
    gt = comparison.get(
        "ground_truth"
    )

    if isinstance(
        gt,
        dict,
    ):
        return {
            "reference_time_s":
                safe_float(
                    gt.get(
                        "reference_time_s"
                    )
                ),

            "comparison_time_s":
                safe_float(
                    gt.get(
                        "comparison_time_s"
                    )
                ),

            "delta_s":
                safe_float(
                    gt.get(
                        "comparison_minus_reference_s"
                    )
                ),
        }

    return {
        "reference_time_s":
            safe_float(
                comparison.get(
                    "reference_time_s"
                )
            ),

        "comparison_time_s":
            safe_float(
                comparison.get(
                    "comparison_time_s"
                )
            ),

        "delta_s":
            safe_float(
                comparison.get(
                    "comparison_minus_reference_s"
                )
            ),
    }


def episode_count(
    comparison,
):
    declared = safe_int(
        comparison.get(
            "driver_action_episode_count"
        )
    )

    if declared is not None:
        return declared

    episode_gt = comparison.get(
        "episode_ground_truth"
    )

    if isinstance(
        episode_gt,
        list,
    ):
        return len(
            episode_gt
        )

    return None


def structured_assessments(
    comparison,
):
    structured = comparison.get(
        "llm_structured"
    )

    if not isinstance(
        structured,
        dict,
    ):
        return []

    assessments = structured.get(
        "episode_assessments"
    )

    if not isinstance(
        assessments,
        list,
    ):
        return []

    return [
        item
        for item in assessments
        if isinstance(
            item,
            dict,
        )
    ]


def classification_map(
    comparison,
):
    result = {}

    for item in structured_assessments(
        comparison
    ):
        episode_id = safe_int(
            item.get(
                "episode_id"
            )
        )

        if episode_id is None:
            continue

        result[
            episode_id
        ] = item.get(
            "classification"
        )

    return result


def analysis_text(
    comparison,
):
    value = comparison.get(
        "analysis"
    )

    if isinstance(
        value,
        str,
    ):
        return value

    return ""


def has_bad_missing_data_text(
    comparison,
):
    return (
        "No disponible en datos"
        in
        analysis_text(
            comparison
        )
    )


def count_episode_mentions(
    comparison,
    count,
):
    if count is None:
        return None

    text = analysis_text(
        comparison
    )

    found = 0

    for episode_id in range(
        1,
        count + 1,
    ):
        if (
            f"Episodio #{episode_id}"
            in text
        ):
            found += 1

    return found


def print_field(
    name,
    old_value,
    new_value,
):
    changed = (
        old_value
        !=
        new_value
    )

    marker = (
        "CHANGED"
        if changed
        else
        "same"
    )

    print(
        f"{name}:"
    )

    print(
        f"  OLD: {old_value}"
    )

    print(
        f"  NEW: {new_value}"
    )

    print(
        f"  -> {marker}"
    )


def compare_comparison(
    key,
    old,
    new,
):
    print()
    print(
        "-" * 60
    )

    print(
        f"COMPARACIÓN {key[0]} -> {key[1]}"
    )

    print(
        "-" * 60
    )

    old_gt = ground_truth(
        old
    )

    new_gt = ground_truth(
        new
    )

    print_field(
        "Ground truth",
        old_gt,
        new_gt,
    )

    old_count = episode_count(
        old
    )

    new_count = episode_count(
        new
    )

    print_field(
        "Episodios declarados",
        old_count,
        new_count,
    )

    old_assessments = (
        structured_assessments(
            old
        )
    )

    new_assessments = (
        structured_assessments(
            new
        )
    )

    print_field(
        "Assessments estructurados",
        len(
            old_assessments
        ),
        len(
            new_assessments
        ),
    )

    print_field(
        "Clasificaciones",
        classification_map(
            old
        ),
        classification_map(
            new
        ),
    )

    print_field(
        "Validation attempts",
        old.get(
            "validation_attempts"
        ),
        new.get(
            "validation_attempts"
        ),
    )

    print_field(
        "Status",
        old.get(
            "status"
        ),
        new.get(
            "status"
        ),
    )

    print_field(
        "Texto 'No disponible en datos'",
        has_bad_missing_data_text(
            old
        ),
        has_bad_missing_data_text(
            new
        ),
    )

    print_field(
        "Episodios mencionados en informe",
        count_episode_mentions(
            old,
            old_count,
        ),
        count_episode_mentions(
            new,
            new_count,
        ),
    )

    print()

    if (
        new_count is not None
        and
        len(
            new_assessments
        )
        ==
        new_count
    ):
        print(
            "NEW coverage estructurada: COMPLETE"
        )
    else:
        print(
            "NEW coverage estructurada: INCOMPLETE"
        )

    if (
        new.get(
            "status"
        )
        ==
        "VALID"
    ):
        print(
            "NEW status: VALID"
        )
    else:
        print(
            "NEW status: legacy/no structured status"
        )


def main():
    print()
    print("=" * 60)
    print(
        "RACE ENGINEER - LLM ANALYSIS COMPARATOR v1.0"
    )
    print("=" * 60)
    print()

    if len(
        sys.argv
    ) != 3:
        print(
            "Uso:"
        )
        print()
        print(
            "python compare_llm_analysis_outputs.py "
            "old.json new.json"
        )
        sys.exit(2)

    old_path = os.path.abspath(
        sys.argv[1]
    )

    new_path = os.path.abspath(
        sys.argv[2]
    )

    if not os.path.exists(
        old_path
    ):
        print(
            f"No existe OLD:\n{old_path}"
        )
        sys.exit(2)

    if not os.path.exists(
        new_path
    ):
        print(
            f"No existe NEW:\n{new_path}"
        )
        sys.exit(2)

    old_data = load_json(
        old_path
    )

    new_data = load_json(
        new_path
    )

    print(
        f"OLD: v{version(old_data)} "
        f"(analyze v{source_version(old_data)})"
    )

    print(
        f"NEW: v{version(new_data)} "
        f"(analyze v{source_version(new_data)})"
    )

    print()

    print_field(
        "Circuito",
        track(old_data),
        track(new_data),
    )

    old_map = comparison_map(
        old_data
    )

    new_map = comparison_map(
        new_data
    )

    all_keys = sorted(
        set(
            old_map.keys()
        )
        |
        set(
            new_map.keys()
        )
    )

    print()
    print(
        f"Comparaciones OLD: {len(old_map)}"
    )

    print(
        f"Comparaciones NEW: {len(new_map)}"
    )

    for key in all_keys:
        old = old_map.get(
            key
        )

        new = new_map.get(
            key
        )

        if old is None:
            print()
            print(
                f"Comparación {key}: "
                "sólo existe en NEW."
            )
            continue

        if new is None:
            print()
            print(
                f"Comparación {key}: "
                "sólo existe en OLD."
            )
            continue

        compare_comparison(
            key,
            old,
            new,
        )

    print()
    print("=" * 60)
    print(
        "GLOBAL"
    )
    print("=" * 60)
    print()

    print_field(
        "Structured validation metadata",
        old_data.get(
            "metadata",
            {},
        ).get(
            "structured_validation"
        ),
        new_data.get(
            "metadata",
            {},
        ).get(
            "structured_validation"
        ),
    )

    print_field(
        "Global structured presente",
        isinstance(
            old_data.get(
                "global_structured"
            ),
            dict,
        ),
        isinstance(
            new_data.get(
                "global_structured"
            ),
            dict,
        ),
    )

    print()
    print(
        "COMPARISON COMPLETE"
    )


if __name__ == "__main__":
    main()
