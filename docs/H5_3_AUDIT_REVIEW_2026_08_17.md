# H5.3b audit review — 2026-08-17

## Criterio aplicado

`ACTIONABLE` si la pérdida de la zona supera 0.08 s. Los canales mixtos quedan como
nota de verificación y no bloquean. Ganacias y pérdidas <= 0.08 s quedan como
`OBSERVATIONAL_ONLY`. Un segmento multi-curva largo queda `NOT_COMPARABLE` y la
evidencia de canales anómala queda `AMBIGUOUS`.

Reviewer: `usuario-2026-08-17` (criterio definido por el usuario y aplicado con el
flujo `label_h5_3_audit_candidates.py`).

## Dataset auditado

55 candidatos sobre 4 circuitos con ambos signos de delta:

| Contexto | Delta | Candidatos | ACTIONABLE | OBSERVATIONAL_ONLY | AMBIGUOUS | NOT_COMPARABLE |
|---|---:|---:|---:|---:|---:|---:|
| Imola (`Autodromo Enzo e Dino Ferrari`) | +0.600 s | 11 | 6 | 4 | 1 | 0 |
| Monza (`Autodromo Nazionale Monza`) | -1.940 s | 15 | 0 | 14 | 0 | 1 |
| Fuji (`Fuji Speedway`) | +1.280 s | 15 | 7 | 8 | 0 | 0 |
| Interlagos (`Autódromo José Carlos Pace`) | -0.180 s | 14 | 3 | 11 | 0 | 0 |
| **Total** | | **55** | **16** | **37** | **1** | **1** |

## Validación

```text
validate_h5_3_audit_labels.py: PASS (55/55, unreviewed=0)
```

Fuentes: `data/generated/h5_3/audit_dataset_full.json` y
`data/generated/h5_3/audit_labels_full.json` (ambas ignoradas por Git).

Esta revisión documenta la evidencia humana de H5.3b; no autoriza acciones
históricas (`historical_actions_authorized=false`).
