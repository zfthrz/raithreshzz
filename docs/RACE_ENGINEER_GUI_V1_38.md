# Race Engineer GUI v1.38 — Track Readiness hierarchy

The `Circuitos → Readiness` view remains a read-only consumer of
`track_readiness.py`. It does not reproduce readiness rules in Tkinter.

The view distinguishes:

- exact variant calibration (`CURRENT_REQUIREMENTS_SATISFIED`);
- promoted track/layout MATCH-only coverage (`COVERED_BY_TRACK_MATCH_BASELINE`);
- unpromoted MATCH baseline shadow (`TRACK_MATCH_BASELINE_SHADOW`);
- contexts waiting for another variant to establish the track baseline;
- missing profile, sessions, queue, labels or evaluation;
- candidate and conflict states.

Promoted coverage has its own color and label and is never displayed as fully
calibrated. Its tooltip states that only MATCH is inherited and REJECT remains
variant-specific and fail-closed. The summary counts exact contexts separately from
MATCH-only covered contexts.

No readiness state changes matcher authority, calibration artifacts, History or
coaching. The GUI only renders the payload returned by `build_track_readiness()`.
