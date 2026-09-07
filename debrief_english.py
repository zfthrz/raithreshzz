"""Closed-vocabulary English presentation of an already authorized session plan.

The canonical Spanish evidence/validation contract is retained. This module does
not select cues, infer directions, create targets or read telemetry/History.
Unknown action wording fails closed instead of silently dropping an action.
"""

from __future__ import annotations

import re

from deterministic_comparison_render import format_lap_time

VERSION = "1.0"

_ACTIONS = {
    "frená": "brake", "soltá el freno": "release the brake",
    "reaplicá el acelerador": "reapply the throttle",
    "soltá el acelerador": "release the throttle",
}
_SHAPES = {
    "aplicación": "application",
    "aplicación parcial": "partial application",
    "aplicación media": "medium application",
    "aplicación alta": "high application",
    "aplicación parcial breve": "brief partial application",
    "aplicación media breve": "brief medium application",
    "aplicación alta breve": "brief high application",
    "liberación breve": "brief release",
    "acelerador liberado": "throttle released",
    "reaplicación sostenida": "sustained reapplication",
    "reaplicación sostenida sin volver a soltar dentro de la zona": "sustained reapplication without releasing again within the zone",
    "aplicación ligera de freno": "light brake application",
    "aplicación media de freno": "medium brake application",
    "aplicación alta de freno": "high brake application",
    "aplicación muy alta de freno": "very high brake application",
    "freno liberado": "brake released",
    "freno liberado hasta salir de la zona": "brake released through the end of the zone",
}
_PROFILE_ACTIONS = {
    "replicá la aplicación de acelerador": "match the throttle application",
    "usá una aplicación parcial de acelerador": "use a partial throttle application",
    "usá una aplicación media de acelerador": "use a medium throttle application",
    "usá una aplicación alta de acelerador": "use a high throttle application",
    "hacé una aplicación parcial y breve de acelerador": "make a brief partial throttle application",
    "hacé una aplicación media y breve de acelerador": "make a brief medium throttle application",
    "hacé una aplicación alta y breve de acelerador": "make a brief high throttle application",
    "hacé una liberación breve del acelerador": "briefly release the throttle",
    "soltá el acelerador": "release the throttle",
    "reaplicá y sostené el acelerador": "reapply and hold the throttle",
}
_LEVELS = {
    f"{verb} {channel}": f"{english_verb} {english_channel}"
    for verb, english_verb in (("reducí", "reduce"), ("aumentá", "increase"))
    for channel, english_channel in (
        ("el freno", "brake input"), ("el acelerador", "throttle input"),
        ("la aplicación del freno", "brake application"),
        ("la aplicación del acelerador", "throttle application"),
        ("la magnitud del volante hacia la referencia", "steering magnitude towards the reference"),
    )
}
_LEVELS["replicá la secuencia de dirección de la referencia"] = "match the reference steering sequence"


def shape_text(value: str) -> str:
    parts = value.split(" → ")
    translated = []
    for part in parts:
        if part in _SHAPES:
            translated.append(_SHAPES[part])
            continue
        shape = next((s for s in sorted(_SHAPES, key=len, reverse=True)
                      if part.startswith(s + " ")), None)
        suffix = part[len(shape):] if shape else ""
        number = r"[-+]?\d+(?:\.\d+)?"
        if shape and re.fullmatch(rf"(?: desde ~{number} m| \(~{number}–{number} m(?:; pico ~{number}%)?\))", suffix):
            translated.append(_SHAPES[shape] + suffix.replace("desde", "from").replace("pico", "peak"))
        else:
            raise ValueError(f"Unsupported English reference shape: {value!r}")
    return " → ".join(translated)


def anchor_text(value: str) -> str:
    """Translate only the positional prefix; preserve profile-owned corner names."""
    value = value.removeprefix("referencia: ")
    match = re.fullmatch(r"(~?\d+(?:\.\d+)? m) (antes de|después de|antes del ápice de|después del ápice de|antes de la salida de|después de la salida de|antes de la entrada de|después de la entrada de) (T\d+.*)", value)
    if match:
        relation = {"antes de": "before", "después de": "after", "antes del ápice de": "before the apex of", "después del ápice de": "after the apex of", "antes de la salida de": "before the exit of", "después de la salida de": "after the exit of", "antes de la entrada de": "before the entry of", "después de la entrada de": "after the entry of"}[match[2]]
        return f"{match[1]} {relation} {match[3]}"
    match = re.fullmatch(r"(?:en|cerca de) (el ápice de |la salida de )?(T\d+.*)", value)
    if match:
        prefix = {None: "", "el ápice de ": "the apex of ", "la salida de ": "the exit of "}[match[1]]
        return ("near " if value.startswith("cerca") else "at ") + prefix + match[2]
    raise ValueError(f"Unsupported English spatial reference: {value!r}")


def cue_text(value: str) -> str:
    """Translate the exact authorized wording, retaining its order and numbers."""
    value = value.strip().rstrip(".")
    suffix = " y, desde ahí, sostené la reaplicación como en la referencia"
    if value.endswith(suffix):
        return cue_text(value.removesuffix(suffix)) + " and, from there, hold the reapplication as in the reference"
    separator = "; terminá esa secuencia en el punto indicado: "
    if separator in value:
        first, second = value.split(separator, 1)
        return cue_text(first) + "; end that sequence at the indicated point: " + cue_text(second)
    if ". Referencias:" in value:
        action, references = value.split(". Referencias:", 1)
        translated = []
        for reference in references.strip().split("; "):
            channel, separator, anchor = reference.partition(": ")
            channels = {"freno": "brake", "acelerador": "throttle", "frenada": "braking", "reaplicación": "reapplication", "liberación de freno": "brake release", "liberación de acelerador": "throttle release", "liberación": "release", "levantada": "lift-off"}
            if not separator or channel not in channels:
                raise ValueError(f"Unsupported English cue reference: {reference!r}")
            translated.append(channels[channel] + ": " + anchor_text(anchor))
        return cue_text(action) + ". References: " + "; ".join(translated)
    if value in _LEVELS:
        return _LEVELS[value]
    if value in _PROFILE_ACTIONS:
        return _PROFILE_ACTIONS[value]
    if value.endswith(" como en la referencia"):
        parts = value.removesuffix(" como en la referencia").split("; después, ")
        if all(p in _PROFILE_ACTIONS for p in parts):
            return "; then, ".join(_PROFILE_ACTIONS[p] for p in parts) + " as in the reference"
    for channel, english in (("freno", "brake"), ("acelerador", "throttle")):
        prefix = f"replicá la secuencia de {channel} de la referencia: "
        if value.startswith(prefix):
            return f"match the reference {english} sequence: " + shape_text(value[len(prefix):])
    pattern = r"(frená|soltá el freno|reaplicá el acelerador|soltá el acelerador) aproximadamente (\d+) m más (tarde|temprano)(?: \(([^()]*)\))?"
    match = re.fullmatch(pattern, value)
    if match:
        result = f"{_ACTIONS[match[1]]} approximately {match[2]} m " + {"tarde": "later", "temprano": "earlier"}[match[3]]
        if match[4]:
            result += " (reference: " + anchor_text(match[4]) + ")"
        return result
    # Split only outside parentheses (a profile-owned proper name can contain 'y').
    depth = 0
    for index, char in enumerate(value):
        depth += (char == "(") - (char == ")")
        if depth == 0:
            for separator, english in (("; después, ", "; then, "), (" y ", " and ")):
                if value.startswith(separator, index):
                    return cue_text(value[:index]) + english + cue_text(value[index + len(separator):])
    raise ValueError(f"Unsupported English authorized cue: {value!r}")


_OBSERVATIONS = {
    "más freno": "more brake input", "menos freno": "less brake input",
    "más acelerador": "more throttle input", "menos acelerador": "less throttle input",
    "aplicación distinta del freno": "different brake application",
    "modulación distinta del acelerador": "different throttle modulation",
    "mayor magnitud de dirección/volante": "higher steering magnitude",
    "menor magnitud de dirección/volante": "lower steering magnitude",
    "magnitud distinta de dirección/volante": "different steering magnitude",
}
_TEMPORAL = {
    "freno primero y acelerador después, sin solapamiento; separación aproximada N m": "brake first and throttle afterwards, without overlap; approximate separation N m",
    "acelerador primero y freno después, sin solapamiento; separación aproximada N m": "throttle first and brake afterwards, without overlap; approximate separation N m",
    "la relación entre freno y acelerador cambió entre comparaciones; no se trata como un patrón temporal repetido": "the brake/throttle relationship changed between comparisons; it is not treated as a repeated temporal pattern",
    "los eventos de freno y acelerador se alternaron dentro de la zona sin solapamiento directo": "brake and throttle events alternated within the zone without direct overlap",
    "los eventos de freno y acelerador se solaparon durante aproximadamente N m de recorrido": "brake and throttle events overlapped over approximately N m",
    "se repitió la secuencia freno → acelerador sin solapamiento en N comparaciones; separación aproximada N m": "the brake → throttle sequence repeated without overlap in N comparisons; approximate separation N m",
    "se repitió la secuencia freno → acelerador sin solapamiento en N comparaciones; separación entre eventos de N a N m": "the brake → throttle sequence repeated without overlap in N comparisons; separation between events from N to N m",
    "se repitió solapamiento de freno y acelerador en N comparaciones; solapamiento aproximado N m": "brake/throttle overlap repeated in N comparisons; approximate overlap N m",
    "se repitió solapamiento de freno y acelerador en N comparaciones; solapamiento observado entre N y N m": "brake/throttle overlap repeated in N comparisons; observed overlap between N and N m",
}


def observation_text(value: str) -> str:
    label, separator, detail = value.partition(": ")
    if label not in _OBSERVATIONS:
        raise ValueError(f"Unsupported English observation: {value!r}")
    if not separator:
        return _OBSERVATIONS[label]
    number = r"[-+]?\d+(?:\.\d+)?"
    unit = r"(?:pp|unidades de input de volante)"
    if not re.fullmatch(rf"(?:promedio {number} {unit}; pico {number} {unit}|(?:promedio|medias por evento) entre {number} {unit} y {number} {unit}; pico de mayor magnitud {number} {unit})", detail):
        raise ValueError(f"Unsupported English quantitative observation: {value!r}")
    for source, target in (("unidades de input de volante", "steering input units"), ("medias por evento", "event means"), ("pico de mayor magnitud", "largest-magnitude peak"), ("promedio", "mean"), ("pico", "peak"), (" entre ", " between "), (" y ", " and ")):
        detail = detail.replace(source, target)
    return _OBSERVATIONS[label] + ": " + detail


def temporal_text(value: str) -> str:
    numbers = iter(re.findall(r"[-+]?\d+(?:\.\d+)?", value))
    template = re.sub(r"[-+]?\d+(?:\.\d+)?", "N", value)
    if template not in _TEMPORAL:
        raise ValueError(f"Unsupported English temporal observation: {value!r}")
    return re.sub(r"\bN\b", lambda _: next(numbers), _TEMPORAL[template])


def location_text(item: dict) -> str:
    location = item.get("track_location") or {}
    label = str(location.get("label") or "") if location.get("status") == "RESOLVED" else ""
    for source, target in (("Entre ", "Between "), ("Antes de ", "Before "), ("Después de ", "After ")):
        if label.startswith(source):
            return target + label[len(source):].replace(" y T", " and T")
    return label


def build_english_presentation(document: dict) -> dict:
    facts = document.get("session_coaching_facts") or {}
    plan = facts.get("next_stint_plan") or []
    metadata = document.get("metadata") or {}
    comparisons = document.get("comparisons") or []
    lines = [f"# Engineering debrief — {metadata.get('track') or 'Session'}", "", "## Session summary", ""]
    reference = metadata.get("reference_lap")
    if reference is not None:
        lines += [f"Working reference: lap {reference}.", ""]
    if comparisons and comparisons[0].get("reference_time_s") is not None:
        lines += [f"Reference lap time: {format_lap_time(comparisons[0]['reference_time_s'])}.", ""]
    zone_word = "zone" if len(plan) == 1 else "zones"
    lines += [f"The next-stint plan contains {len(plan)} priority {zone_word}.", ""]
    focus = facts.get("next_stint_focus") or {}
    labels = [str(i.get("plan_label")) for i in (focus.get("items") or [])]
    plan_labels = {str(i.get("plan_label")) for i in plan}
    if not (focus.get("status") == "ACTIVE" and len(labels) in (1, 2) and len(set(labels)) == len(labels) and set(labels) <= plan_labels and focus.get("focus_count") == len(labels)):
        labels = [str(i.get("plan_label")) for i in plan]
    lines += ["## Main focus", ""]
    by_label = {str(item.get("plan_label")): item for item in plan}
    for label in labels:
        item = by_label[label]
        lines.append(f"- Zone {item['plan_label']} — {location_text(item) or 'Unlocalized zone'}: see the complete actions in the plan.")
    lines += ["", "## Next-stint plan", ""]
    presented_plan = []
    for index, item in enumerate(plan, 1):
        title = location_text(item) or "Unlocalized zone"
        lines += [f"### {index}. Zone {item['plan_label']} — {title}", ""]
        cues = []
        for cue_index, cue in enumerate(item.get("driver_cues") or []):
            text = cue_text(cue["text"])
            sequence = cue.get("coaching_sequence") or {}
            events = sequence.get("events") or []
            if not (cue_index == 0 and cue.get("kind") == "combined_spatial_sequence"
                    and sequence.get("status") == "COMBINED" and len(events) >= 2):
                events = []
            steps = [cue_text(event["text"]) for event in events]
            cues.append({"text": text, "steps": steps})
            heading = "What to change" if cue_index == 0 else "Second cue"
            if steps:
                lines += [f"**Action · {heading} — sequence:**", ""]
                lines += [f"{n}. {step[0].upper() + step[1:]}." for n, step in enumerate(steps, 1)]
            else:
                action, marker, references = text.partition(". References: ")
                lines.append(f"**Action · {heading}:** {action[0].upper() + action[1:]}.")
                if marker:
                    lines.append(f"**Action · References:** {references}.")
            lines.append("")
            count = cue.get("point_comparison_count")
            if isinstance(count, int) and count >= 2:
                lines += [f"**Evidence · Physical point support:** {count} comparisons.", ""]
            for evidence in cue.get("precision_evidence") or []:
                parts = []
                if evidence.get("reference_lap") is not None:
                    parts.append(f"reference lap {evidence['reference_lap']}")
                if evidence.get("supporting_laps"):
                    parts.append("supporting laps " + ", ".join(map(str, evidence["supporting_laps"])))
                for key, label in (("observed_delta_min_m", "minimum observed difference"), ("observed_delta_max_m", "maximum observed difference"), ("representative_delta_m", "representative difference")):
                    if evidence.get(key) is not None:
                        parts.append(f"{label}: {evidence[key]} m")
                if parts:
                    lines += ["**Evidence · Physical point:** " + "; ".join(parts) + ".", ""]
        if not cues:
            lines += ["No authorized driving cue is available for this zone.", ""]
        for profile in item.get("reference_action_profiles") or []:
            if profile.get("shape_summary"):
                description = profile.get("shape_summary_detailed") or profile["shape_summary"]
                lines += [f"**Context · Reference {profile['channel']} shape:** {shape_text(description)}.",
                          "_Descriptive shape only; numeric driving targets remain limited to authorized event points._", ""]
        if item.get("comparison_count") is not None:
            comparison_word = "comparison" if item["comparison_count"] == 1 else "comparisons"
            lines += [f"**Evidence · Zone support:** {item['comparison_count']} {comparison_word}.", ""]
        if item.get("comparisons"):
            lines += ["**Evidence · Comparisons:** " + ", ".join(map(str, item["comparisons"])) + ".", ""]
        observations = list(item.get("quantitative_observations") or [])
        for observation in item.get("observed_differences") or []:
            if not any(q.startswith(observation + ":") or q == observation for q in observations):
                observations.append(observation)
        if observations:
            lines += ["**Context · Observed differences:**", ""]
            lines += ["- " + observation_text(value) + "." for value in observations]
            lines.append("")
        for temporal in item.get("temporal_relationships") or []:
            lines += ["**Context · Measured sequence:** " + temporal_text(temporal) + ".", ""]
        directions = set(item.get("speed_directions") or [])
        speed = {frozenset({"lower_in_comparison_lap"}): "lower", frozenset({"higher_in_comparison_lap"}): "higher", frozenset({"lower_in_comparison_lap", "higher_in_comparison_lap"}): "variable across comparisons"}.get(frozenset(directions))
        if speed:
            lines += [f"**Context · Speed:** {speed} relative to the reference; observational only.", ""]
        start, end = item.get("start_distance_m"), item.get("end_distance_m")
        if start is not None and end is not None:
            lines += [f"**Context · Zone interval:** {start}–{end} m. This interval is not a new driving target.", ""]
        presented_plan.append({"plan_label": str(item["plan_label"]), "location": title, "cues": cues})
    if not plan:
        lines += ["There is not enough authorized evidence to build a prioritized driving plan.", ""]
    lines += ["## Technical support", "", "The current-session reference remains the coaching authority. Speed is observational context, not a driving target.", ""]
    for comparison in comparisons:
        lines.append(f"- Reference lap {comparison.get('reference_lap')} → comparison lap {comparison.get('comparison_lap')}: current minus reference {comparison.get('comparison_minus_reference_s')} s; session-plan eligible: {comparison.get('session_plan_eligible') is True}.")
    excluded = (facts.get("comparison_quality_gate") or {}).get("excluded_comparisons") or []
    if excluded:
        noun, verb = ("comparison", "remains") if len(excluded) == 1 else ("comparisons", "remain")
        lines += ["", f"{len(excluded)} {noun} excluded by the session quality gate {verb} in the source artifact."]
    return {"version": VERSION, "language": "en", "global_analysis": "\n".join(lines).strip(), "plan": presented_plan}


def validate_presentation(document: dict) -> None:
    language = (document.get("metadata") or {}).get("debrief_language", "es")
    presentation = document.get("localized_presentation")
    if language == "es" and presentation is None:
        return
    if language != "en" or presentation != build_english_presentation(document):
        raise ValueError("Localized debrief does not match the authorized deterministic presentation")
