# Pair Review Calibration Tools v1.0

Estas herramientas preparan el dataset humano para calibrar el matcher histórico.

## Separación de responsabilidades

1. `episode_pair_features.py`
   - genera features objetivas;
2. `pair_review_queue.py`
   - selecciona una muestra diversa para revisión;
3. `label_episode_pairs.py`
   - guarda la decisión humana;
4. `validate_pair_labels.py`
   - valida integridad y trazabilidad.

Ninguna de estas herramientas decide automáticamente si dos episodios hacen match.

## 1. Generar pair features

Con varias sesiones del mismo circuito importadas:

```bash
python episode_pair_features.py \
  --track "Autodromo Nazionale Monza" \
  --output monza_pair_features.json
```

## 2. Crear cola de revisión

```bash
python pair_review_queue.py \
  monza_pair_features.json \
  --output monza_review_queue.json
```

Opcional:

```bash
python pair_review_queue.py \
  monza_pair_features.json \
  --per-lens 25 \
  --max-total 100 \
  --output monza_review_queue.json
```

`--per-lens` y `--max-total` controlan sólo el tamaño de la muestra humana. No son thresholds de matching.

Las perspectivas de revisión son:

- centros más cercanos;
- mayor overlap espacial;
- mayor similitud de canales;
- pares cercanos con desacuerdo de canales;
- canales similares pero espacialmente separados;
- divergencia de impacto temporal;
- baseline determinista.

Un par seleccionado por varias perspectivas aparece una sola vez y conserva todas las razones de selección.

## 3. Etiquetar

```bash
python label_episode_pairs.py \
  monza_review_queue.json \
  --labels monza_pair_labels.json \
  --reviewer zfthrz
```

Controles:

```text
s = SAME
d = DIFFERENT
a = AMBIGUOUS
k = SKIP
q = guardar y salir
```

El archivo se guarda después de cada decisión.

### SAME

Misma región y mismo tipo general de diferencia de conducción.

No significa:

- misma causa;
- mismo impacto exacto;
- misma recomendación;
- causalidad demostrada.

### DIFFERENT

Los episodios no deberían representar la misma observación histórica.

### AMBIGUOUS

La evidencia no permite decidir con suficiente seguridad.

Esta clase es deliberadamente necesaria.

### SKIP

No se revisa por ahora y no se usa como ground truth del matcher.

## 4. Validar

```bash
python validate_pair_labels.py \
  monza_review_queue.json \
  monza_pair_labels.json
```

Comprueba:

- hash de la cola;
- IDs duplicados;
- labels válidos;
- que todos los labels pertenezcan a la cola;
- feature snapshots;
- identidad de sesión/episodio;
- que sean pares cross-session;
- distribución de etiquetas.

## Tests

Copiando `test_pair_review_calibration.py` dentro de `tests/`:

```bash
pytest -q
```

## Qué no existe todavía

No hay:

- threshold de distancia;
- threshold de overlap;
- match score;
- `MATCHED` automático;
- clustering;
- `persistent_pattern`.

Todo eso espera suficientes datos reales y etiquetas humanas SAME / DIFFERENT / AMBIGUOUS.
