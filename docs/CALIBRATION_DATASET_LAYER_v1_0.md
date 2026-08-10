# Calibration / Evaluation Dataset Layer v1.0

Esta capa prepara el ground truth humano para calibrar y evaluar el matcher
sin implementar todavía ninguna decisión automática.

## Principios

### Split por sesión

El split se hace por sesión, no por pair_id.

Una sesión pertenece exclusivamente a:

- `calibration`, o
- `evaluation`.

Si un par conecta una sesión de calibración con una de evaluación, el par se
guarda en `excluded_cross_split` y no se usa en ninguno de los dos datasets.

Esto evita que episodios de la misma sesión aparezcan indirectamente a ambos
lados del split.

### Labels

Se usan como ground truth:

- `SAME`
- `DIFFERENT`
- `AMBIGUOUS`

`SKIP` queda fuera.

`AMBIGUOUS` se conserva deliberadamente. No se fuerza a binario.

## 1. Construir dataset

```bash
python build_calibration_dataset.py \
  monza_review_queue.json \
  monza_pair_labels.json \
  --evaluation-fraction 0.25 \
  --seed 20260810 \
  --output monza_calibration_dataset.json
```

El output contiene:

- metadata y hashes;
- assignment de cada sesión;
- calibration pairs;
- evaluation pairs;
- pares cross-split excluidos;
- SKIP ignorados;
- conteos por label.

El split es reproducible con el mismo seed.

## 2. Reporte descriptivo de features

```bash
python calibration_feature_report.py \
  monza_calibration_dataset.json \
  --output monza_calibration_feature_report.json
```

El reporte mantiene calibration y evaluation completamente separados.

### Features descriptivas

Se agrupan por rol:

- `spatial_absolute`
- `spatial_normalized`
- `channel_identity`
- `channel_shape`
- `secondary_impact`

Para cada feature y label se calcula:

- n válido / missing;
- mínimo;
- p10;
- p25;
- mediana;
- media;
- p75;
- p90;
- máximo;
- IQR.

También se reportan contrastes descriptivos de medianas entre:

- SAME vs DIFFERENT
- SAME vs AMBIGUOUS
- DIFFERENT vs AMBIGUOUS

El campo `median_gap_over_pooled_iqr` sirve solamente para observar separación
de distribuciones. No es:

- un peso;
- un score;
- una probabilidad;
- un threshold;
- una regla de matching.

## Regla de evaluación

Las estadísticas de `evaluation` son para evaluación futura.

No deben usarse para elegir:

- thresholds;
- pesos;
- features;
- reglas de matching.

Las decisiones futuras se calibrarán solamente con `calibration`, y después se
medirán una vez sobre `evaluation`.

## Impacto temporal

`action_time_loss_similarity` aparece como `secondary_impact`.

Esto preserva la regla de diseño existente: el impacto temporal puede aportar
evidencia secundaria, pero no debe dominar la identidad del patrón.

## Qué sigue bloqueado

Todavía NO implementar:

- distance threshold;
- overlap threshold;
- channel_jaccard threshold;
- weighted match score;
- MATCHED / REJECTED automático;
- clustering;
- persistent_pattern.

Antes necesitamos varias sesiones reales, labels humanas y el reporte
descriptivo resultante.
