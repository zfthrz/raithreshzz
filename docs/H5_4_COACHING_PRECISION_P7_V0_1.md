# H5.4 Coaching Precision — P7 v0.1

## Cue consolidation

P7 adds an additive deterministic `coaching_sequence` for plan zones that contain at least two already-authorized physical-point cues. Original patterns remain untouched.

Rules:
- require 2+ physical events with precision evidence and absolute coordinates;
- reject duplicate/non-increasing coordinates;
- require braking onset before brake release when both exist;
- require throttle release before throttle onset when both exist;
- sort the final sequence by `event_distance_m`;
- preserve each event's original precision evidence;
- consolidate brake + throttle spatial driver cues into one presentation cue only when both channels are present.

No detector, threshold, ranking, action direction/magnitude, authority, historical policy, P4 turn selection, P5 locality, or P6 anchor selection is changed.
