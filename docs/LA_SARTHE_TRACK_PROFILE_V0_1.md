# Circuit de la Sarthe track profile v0.1

## Result

`track_profiles/la_sarthe_profile_v0_1.json` is a
`VALIDATED_MULTI_SESSION` LMU-distance profile for the exact identity:

```text
track  = Circuit de la Sarthe
layout = Circuit de la Sarthe
```

It is suitable for deterministic location resolution and H5.2 profile localization.
It does not alter the current-session coaching authority or authorize historical
actions.

## Evidence

The calibration uses five complete GPS laps from three independent LMU Practice
sessions, all recorded with `IDEC Sport 2025 #18:LM` in class `LMP2`:

| Session | Lap | Lap Dist max | GPS path | Role |
|---|---:|---:|---:|---|
| `2026-08-17T20_14_09Z` | 1 | 13,617.5 m | 13,560.1 m | calibration |
| `2026-08-17T20_14_09Z` | 2 | 13,617.9 m | 13,547.0 m | same-session repeat |
| `2026-08-17T20_14_09Z` | 3 | 13,621.8 m | 13,563.1 m | same-session repeat |
| `2026-08-17T21_15_39Z` | 1 | 13,616.7 m | 13,547.7 m | independent validation |
| `2026-08-17T21_28_06Z` | 1 | 13,618.5 m | 13,550.8 m | independent validation |

Across the 19 representative profile points, the two independent sessions produced
median absolute offsets of 4 m and 8 m and maximum offsets of 22 m and 24 m.

## Nomenclature

Corner names follow the Automobile Club de l'Ouest article
“Explore the 24 Hours of Le Mans circuit, turn by turn” published on 7 June 2026.
The FIA WEC 2026 media guide describes the circuit as 33 turns, 13 left and 20 right.

The profile deliberately does not pretend that detector candidates map one-to-one to
those 33 official turns. Long sections such as the Porsche Curves produce many nearby
curvature maxima, while gentle official turns may not enter the strongest-candidate
ranking. The profile therefore uses a project-local 19-segment sequence and makes ACO
names authoritative in downstream rendering.

Primary named locations:

- Dunlop Curve and Dunlop Chicane;
- Forest Esses;
- Tertre Rouge Corner;
- Daytona and Michelin chicanes;
- Mulsanne Corner;
- Indianapolis and Arnage;
- Porsche Curves;
- Karting Esses;
- Ford Chicanes and Motul Turn.

## Deterministic contract

- Python owns every distance boundary and profile lookup.
- The LLM cannot rename a segment or invent a circuit location.
- Exact track and layout identity are required.
- Profile segment numbers are secondary and must not be presented as official FIA
  turn numbers.
- H5.1 `session_reference` remains coaching authority.
- H5.2 remains observational and historical actions remain disabled.

## Official sources

- ACO / 24 Hours of Le Mans, 2026 turn-by-turn guide:
  <https://www.24h-lemans.com/en/news/explore-the-24-hours-of-le-mans-circuit-turn-by-turn-60679>
- FIA WEC 2026 Media Guide:
  <https://press.fiawec.com/assets/fileuploads/69/d4/69d4b6ffa267a.pdf>
