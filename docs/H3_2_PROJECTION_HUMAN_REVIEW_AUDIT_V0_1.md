# H3.2 projection human-review audit v0.1

`audit_h3_projection_review.py` resume las etiquetas humanas de una cola aislada
H3.2 ya completada. Es un audit read-only: no llama al matcher ni al LLM, no
busca pares nuevos y no modifica History, H3, coaching o runtime.

Uso:

```powershell
python audit_h3_projection_review.py `
  "data\local\h3_projection_review\spa_lmp2_elms_pair_review_queue.json" `
  "data\local\h3_projection_review\spa_lmp2_elms_pair_labels.json" `
  --output "data\local\h3_projection_review\spa_lmp2_elms_review_audit.json"
```

El audit exige:

- hash exacto de la queue mediante el validador humano existente;
- revisión completa;
- scope `H3_2_PROJECTION_VALIDATION_ONLY`;
- todos los flags de autoridad en `false`;
- evidencia de un `MATCH` automático existente.

Reporta dos vistas separadas:

- pares físicos únicos y su etiqueta humana;
- aristas de proyección, preservando regla, patrón y sesión.

También desglosa las etiquetas por regla del matcher y estado/patrón, y muestra
mínimo, mediana y máximo de distancia central, overlaps y Jaccard por etiqueta.
Estas distribuciones son descriptivas: no crean ni sugieren thresholds.

## Límite de interpretación

La cola se compone exclusivamente de proyecciones que el matcher ya clasificó
como `MATCH`. Por eso el porcentaje `SAME` aporta evidencia sobre los positivos
seleccionados, pero no permite estimar recall, falsos negativos ni cobertura de
pares que el matcher dejó afuera. El resultado no autoriza calibración automática,
persistencia de membresía H3, ranking ni coaching.
