# H3.2 projection human review v0.1

## Propósito

Revisar humanamente pares que el matcher calibrado ya proyectó de forma observacional
hacia patrones H3, sin convertir ese resultado en nueva autoridad.

## Preparación

`prepare_h3_projection_review.py`:

- lee artefactos H3.2 ya generados;
- exige MATCH automático y contrato observacional válido;
- filtra sólo por contexto exacto solicitado por el operador;
- abre History con `read_only=True`;
- reconstruye el par representante ↔ episodio actual con
  `episode_pair_features.build_pair_record()`;
- incluye todos los edges válidos, sin threshold ni sampling;
- deduplica sólo el mismo par físico y conserva toda su provenance;
- escribe bajo `data/local/h3_projection_review/`.

La cola es compatible con la presentación H2 existente, pero declara:

```text
review_scope = H3_2_PROJECTION_VALIDATION_ONLY
labels_authorize_matcher_calibration = false
labels_authorize_h3_membership = false
```

## Etiquetado

`label_h3_projection_pairs.py` reutiliza:

- `SAME`: misma región y mismo tipo general de diferencia de conducción;
- `DIFFERENT`: no deben agruparse;
- `AMBIGUOUS`: evidencia insuficiente o conflictiva;
- `SKIP`: no revisar ahora.

El entry point rechaza queues o labels de otro scope y preserva el hash exacto de la
cola. El etiquetado es reanudable. Ninguna etiqueta altera producción.

## Primer corpus

Spa LMP2_ELMS produjo:

```text
proyecciones válidas: 96
pares únicos:         96
sampling:             ninguno
thresholds:           ninguno
```

Comandos:

```powershell
python prepare_h3_projection_review.py `
  --track "Circuit de Spa-Francorchamps" `
  --track-layout "Circuit de Spa-Francorchamps" `
  --vehicle-variant LMP2_ELMS `
  --output "data\local\h3_projection_review\spa_lmp2_elms_pair_review_queue.json"

python label_h3_projection_pairs.py `
  "data\local\h3_projection_review\spa_lmp2_elms_pair_review_queue.json" `
  --labels "data\local\h3_projection_review\spa_lmp2_elms_pair_labels.json"
```

Los resultados humanos requieren un audit posterior separado antes de formular
cualquier hipótesis de persistencia o ajuste del matcher.
