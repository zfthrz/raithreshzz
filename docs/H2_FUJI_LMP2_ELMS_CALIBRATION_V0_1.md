# H2 Fuji Speedway + LMP2_ELMS Calibration — v0.1

## Resumen

Fuji Speedway (LMP2_ELMS) tiene calibración matcher H2 v0.3 con evidencia real.

**Status:** `CALIBRATED_PROVISIONAL_LOW_EVIDENCE`

## Datos del batch

| Campo | Valor |
|---|---|
| Batch hash | `b0b0f526f9` |
| Pares revisados | 24 |
| Pares calibración | 23 |
| Pares evaluación | 0 |
| Sesiones | 7, 8, 39, 44, 56 |
| Labels humanos validados | 7 SAME, 16 DIFFERENT, 1 AMBIGUOUS |
| Labels en calibration split | 7 SAME, 15 DIFFERENT, 1 AMBIGUOUS |

## Umbrales derivados

### MATCH core

| Umbral | Valor | Base |
|---|---|---|
| `match_center_max_m` | 200.0 | Máximo DIFFERENT con overlap > 0 (200m) |
| `match_overlap_shorter_min` | 0.90 | 7 SAME con overlap=1.0, con margen |
| `match_overlap_union_min` | 0.40 | 7 SAME con overlap_union=1.0, con margen |
| `match_shared_channel_min` | 1 | 7 SAME con shared_channels=2 |

### REJECT

| Umbral | Valor | Base |
|---|---|---|
| `reject_center_gt_m` | 300.0 | Mínimo DIFFERENT con zero overlap (~200-300m) |
| `reject_overlap_union_max` | 0.33 | Consistente con DIFFERENT sin overlap |

## Análisis por clase

### SAME (7)

Todos los 7 pares con etiqueta SAME tienen:

- **center_distance_abs_diff_m**: 0.0 (perfecto solapamiento)
- **overlap_over_union**: 1.0
- **overlap_over_shorter**: 1.0
- **shared_channels**: 2 (steering_magnitude + throttle)
- **channel_jaccard**: 1.0

Esto confirma el núcleo MATCH.

### DIFFERENT (15)

Todos los 15 pares con etiqueta DIFFERENT tienen:

- **overlap_over_union**: 0.0 (o cercano a cero)
- **center_distance_abs_diff_m**: desde ~200m hasta ~2990m
- El más cercano con zero overlap: ~200m

Confirma el REJECT para pares lejanos sin overlap.

### AMBIGUOUS (1)

1 par entre sesiones 39 y 56, con features en la región de frontera.

## Contradictions check

No hay contradicciones:

- Ningún par con etiqueta DIFFERENT triggería MATCH bajo estos umbrales.
- Ningún par con etiqueta SAME triggería REJECT bajo estos umbrales.

## Veredicto

A) **CALIBRATED_PROVISIONAL_LOW_EVIDENCE** — la evidencia soporta MATCH core + REJECT.

## Comparación con otros circuitos

| Circuito | Labels | MATCH | DIFFERENT | AMBIGUOUS |
|---|---|---|---|---|
| Spa | 72 | 5 | ~25 | ~420 |
| Imola | 9 | 2 | 6 | 1 |
| Interlagos | 9 | 1 | 2 | 1 |
| Fuji | 23 | 7 | 15 | 1 |
| Monza Hyper | 7 | 0 | 7 | 0 |
| Monza LMP2 | 7 | 0 | 7 | 0 |

Fuji tiene el mayor conjunto de SAME (7) además de Spa, con 15 DIFFERENT para calibrar el REJECT. Es el segundo contexto con mayor evidencia de MATCH.

## Documentación

- Fecha: 2026-08-24
- Autor: Race Engineer v0.3
- Estado: CALIBRATED_PROVISIONAL_LOW_EVIDENCE
