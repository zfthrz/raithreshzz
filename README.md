# Race Engineer

Proyecto de análisis de telemetría para Le Mans Ultimate.

Estado de este paquete:

- `analyze_telemetry.py`: v3.8
- `llm_analysis.py`: v3.8.2
- `session_history.py`: v1.1
- `episode_pair_features.py`: v1.0
- validadores y comparador incluidos
- Dev Container listo para GitHub Codespaces

## Abrir en GitHub Codespaces

El repositorio incluye `.devcontainer/devcontainer.json`. Al crear el Codespace,
GitHub abrirá un entorno Python y ejecutará automáticamente:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python scripts/check_project.py
```

## Qué se puede hacer online inmediatamente

Sin Ollama y sin los DuckDB originales se puede trabajar con los JSON ya generados:

```bash
python session_history.py init
python session_history.py import examples/monza_analyze_v3_8.json
python validate_history_db.py
python episode_pair_features.py
pytest -q
```

También se puede editar y validar:

- `analyze_telemetry.py`
- `llm_analysis.py`
- historial de sesiones
- matcher / features
- tests y documentación

## Qué queda local por ahora

`llm_analysis.py` usa Ollama en `localhost:11434`. En Codespaces no existirá tu
`ingenierov2` local salvo que más adelante configuremos un endpoint remoto.

La prueba real del LLM queda, por ahora, para la PC de casa.

## Módulos base faltantes en este paquete

`analyze_telemetry.py` importa cuatro módulos que no estaban disponibles en los
archivos de esta conversación:

```text
telemetry.py
laps.py
delta_comparison.py
sector_analysis.py
```

No fueron recreados ni inventados.

Cuando tengas acceso a tu PC, copiá esos cuatro archivos a la raíz del repo. En
ese momento `python scripts/check_project.py` debería dejar de mostrar esos warnings.

## Raw telemetry

No subas bases `.duckdb` privadas o pesadas al repositorio por defecto.

Usá:

```text
data/raw/
```

La carpeta está ignorada por Git.

## Flujo recomendado

```text
LMU / PC local
    ↓
DuckDB
    ↓
analyze_telemetry.py
    ↓
JSON v3.8
    ↓
GitHub / Codespaces
    ├── history
    ├── validadores
    ├── tests
    ├── desarrollo Python
    └── diseño matcher
    ↓
PC local
    └── Ollama / ingenierov2
```

## Gate actual

Antes de implementar thresholds de matching:

1. probar `llm_analysis.py v3.8.2`;
2. validar su salida;
3. importar varias sesiones v3.8;
4. validar `race_engineer_history.duckdb`;
5. generar pair features;
6. revisar pares SAME / DIFFERENT / AMBIGUOUS.

No implementar todavía thresholds ni clustering de patrones.
