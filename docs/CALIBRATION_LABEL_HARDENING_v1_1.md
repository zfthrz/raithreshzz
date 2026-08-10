# Calibration Label Hardening v1.1

Este patch fortalece la capa de ground truth humano sin agregar matching automático.

Cambios:
- `label_episode_pairs.py`: valida labels en `upsert_label()`.
- agrega `build_pending_items()` para probar reanudación.
- `SKIP` reaparece sólo con `--include-skipped`.
- `validate_pair_labels.py`: `unreviewed` ignora labels fuera de la cola y nunca puede ser negativo.
- nueva suite de persistencia/corrupción.

Cobertura nueva:
- SAME / DIFFERENT / AMBIGUOUS / SKIP;
- update sin duplicado;
- label inválido;
- reanudación;
- reabrir SKIP;
- hash de cola alterado;
- label duplicado;
- label fuera de cola;
- snapshot alterado;
- falso same-session.

No se implementan thresholds, score, clustering ni matching automático.
