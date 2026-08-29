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

## Evidencia real inicial

- Spa LMP2_ELMS: 96 pares / 21 patrones; 94 `SAME`, 2 `AMBIGUOUS`,
  0 `DIFFERENT`. `CORE_SPATIAL_MATCH` obtuvo 45/45 `SAME` y
  `EXTENDED_SPATIAL_CHANNEL_MATCH` 49 `SAME` más 2 `AMBIGUOUS`.
- Interlagos LMP2_ELMS: 6 pares / 6 patrones / 3 sesiones; 6/6 `SAME`, todos
  mediante `CORE_SPATIAL_MATCH`.

Ambos conjuntos siguen siendo positivos seleccionados por el matcher. La
consistencia entre contextos aumenta la evidencia de precisión observada, pero no
elimina el sesgo de selección ni habilita promoción automática.
