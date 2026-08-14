# Race Engineer — Guía de usuario y calibración de circuitos

Esta guía documenta el flujo práctico del proyecto **Race Engineer** tal como está organizado en la rama 3.10.7.

El principio central del sistema es:

- **Python** posee los hechos deterministas: vueltas, deltas, eventos, recurrencia, ubicación de pista, puntos físicos y validación.
- **El LLM** interpreta, prioriza y redacta, pero no debe recalcular ni inventar hechos de telemetría.
- Los **track profiles** también son deterministas: los nombres de curvas no se delegan al LLM.

---

## 1. Estructura recomendada del proyecto

```text
raithreshzz/
├─ telemetria/                  # DuckDB crudos de LMU
├─ track_exports/               # GPS, GeoJSON y candidatos geométricos
├─ track_profiles/              # Perfiles validados de circuitos
├─ analyze_telemetry.py         # Análisis determinista v3.8
├─ llm_analysis.py              # Backend local/Ollama vigente
├─ llm_analysis_deepseek.py     # Backend DeepSeek vigente
├─ extract_lmu_track_gps.py     # DuckDB -> trayectoria GPS/Lap Dist
├─ detect_track_turns.py        # trayectoria -> candidatos de curva
├─ track_location.py            # intervalo en metros -> nombre de curva
├─ validate_llm_analysis_output.py
├─ session_history.py
└─ requirements.txt
```

### Convención importante

Los DuckDB de telemetría se guardan en `telemetria`.

Para comandos de uso normal se recomienda mantener nombres genéricos sin versión (`analyze_telemetry.py`, `llm_analysis.py`, `llm_analysis_deepseek.py`). Los archivos versionados pueden conservarse como historial/release, pero no hace falta escribir su número de versión cada vez que se ejecuta el programa.

---

# 2. Preparación inicial en Windows

Abrir PowerShell en la raíz del repositorio:

```powershell
cd C:\Users\thres\Documents\GitHub\raithreshzz
```

Opcional pero recomendado: entorno virtual.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Las dependencias principales actuales son:

- `numpy`
- `pandas`
- `duckdb`

Comprobar DuckDB:

```powershell
python -c "import duckdb; print(duckdb.__version__)"
```

Comprobar el proyecto:

```powershell
python scripts\check_project.py
python -m compileall -q .
pytest -q
```

---

# 3. Flujo normal de una sesión

## Paso 1 — Grabar la telemetría en LMU

Grabar la sesión y conservar el `.duckdb` original.

Copiarlo o moverlo a:

```text
telemetria\
```

Conviene conservar el nombre original, por ejemplo:

```text
Autódromo José Carlos Pace_P_2026-08-14T03_14_04Z.duckdb
```

El nombre ayuda a recuperar circuito, tipo de sesión y timestamp. El contenido del DuckDB sigue siendo la fuente principal para contexto del vehículo y canales.

---

## Paso 2 — Generar el análisis determinista

Ejemplo:

```powershell
python analyze_telemetry.py "telemetria\Autódromo José Carlos Pace_P_2026-08-14T03_14_04Z.duckdb"
```

Para ejecutar además el modo de validación:

```powershell
python analyze_telemetry.py --validate "telemetria\Autódromo José Carlos Pace_P_2026-08-14T03_14_04Z.duckdb"
```

El resultado se guarda en la raíz del proyecto con el mismo stem:

```text
Autódromo José Carlos Pace_P_2026-08-14T03_14_04Z.json
```

Ese JSON es el contrato determinista que consume el LLM.

---

## Paso 3 — Ejecutar DeepSeek

Configurar la API key en la sesión de PowerShell:

```powershell
$env:DEEPSEEK_API_KEY="TU_API_KEY"
$env:DEEPSEEK_MODEL="deepseek-v4-pro"
```

Ejecutar:

```powershell
python llm_analysis_deepseek.py "Autódromo José Carlos Pace_P_2026-08-14T03_14_04Z.json"
```

El programa genera:

- JSON final estructurado;
- reporte final renderizado dentro del JSON;
- carpeta `_llm` con prompts/respuestas/auditoría de la ejecución.

### Flujo recomendado de desarrollo

Actualmente conviene usar:

- **DeepSeek:** para iteraciones y pruebas frecuentes;
- **ingenierov3/Ollama:** para checkpoints de compatibilidad local.

Así se puede usar LMU mientras se ejecutan análisis remotos sin bloquear CPU/GPU/RAM con el modelo local.

---

## Paso 4 — Validar el resultado LLM

```powershell
python validate_llm_analysis_output.py "ARCHIVO_LLM_GENERADO.json"
```

Un resultado estable debería terminar con:

```text
REGRESSION VALIDATION: PASS
```

Además, en versiones actuales el JSON incluye auditorías de:

- intentos por episodio;
- reparaciones deterministas;
- fallbacks;
- ranking;
- síntesis global;
- `global_validation_audit`.

---

# 4. Crear un track profile nuevo

## Objetivo

Transformar coordenadas y distancia de LMU en un mapa determinista de este tipo:

```text
1320–1420 m -> T5–T6 — nombre del complejo
```

El LLM no decide esto. `track_location.py` sólo resuelve un intervalo contra un perfil previamente calibrado.

La calibración debe hacerse con **al menos dos sesiones del mismo layout** antes de marcar un perfil como `VALIDATED_MULTI_SESSION`.

---

# 5. Interlagos — preparar las dos sesiones

Archivos de esta calibración:

```text
telemetria\Autódromo José Carlos Pace_P_2026-08-14T03_03_08Z.duckdb
telemetria\Autódromo José Carlos Pace_P_2026-08-14T03_14_04Z.duckdb
```

El layout WEC de Interlagos utiliza 15 curvas numeradas. Para esta primera pasada se pide al detector **15 candidatos**.

Hay dos formas de ejecutar el proceso.

## Opción A — Script PowerShell automático

Ejecutar desde la raíz:

```powershell
powershell -ExecutionPolicy Bypass -File .\procesar_interlagos_calibracion.ps1
```

## Opción B — Manual

### Sesión 1

```powershell
python extract_lmu_track_gps.py "telemetria\Autódromo José Carlos Pace_P_2026-08-14T03_03_08Z.duckdb" --output-dir track_exports
```

Luego:

```powershell
python detect_track_turns.py "track_exports\Autódromo José Carlos Pace_P_2026-08-14T03_03_08Z_track_gps.csv" --turn-count 15 --output-dir track_exports
```

### Sesión 2

```powershell
python extract_lmu_track_gps.py "telemetria\Autódromo José Carlos Pace_P_2026-08-14T03_14_04Z.duckdb" --output-dir track_exports
```

Luego:

```powershell
python detect_track_turns.py "track_exports\Autódromo José Carlos Pace_P_2026-08-14T03_14_04Z_track_gps.csv" --turn-count 15 --output-dir track_exports
```

---

# 6. Qué genera `extract_lmu_track_gps.py`

Para cada DuckDB:

```text
*_track_gps.csv
*_track_gps.geojson
*_track_gps_summary.json
```

## CSV

Contiene la trayectoria remuestreada y la coordenada de distancia de LMU.

## GeoJSON

Permite abrir visualmente la vuelta en un visor compatible con GeoJSON, por ejemplo QGIS.

Es especialmente útil para comprobar:

- sentido de marcha;
- cierre de vuelta;
- curvas que el detector pueda haber combinado;
- candidatos geométricos que no correspondan uno-a-uno con el número oficial.

## Summary

Antes de seguir, revisar:

- `selected_lap`;
- `gps_coverage`;
- `lap_dist_max_m`;
- `gps_path_m`;
- cantidad de puntos exportados;
- bounding box.

Las dos sesiones deberían tener una longitud `Lap Dist` muy similar.

### Si eligió una vuelta mala

El extractor muestra todas las vueltas candidatas y permite forzar una:

```powershell
python extract_lmu_track_gps.py "telemetria\ARCHIVO.duckdb" --lap N --output-dir track_exports
```

No continuar con la calibración si la vuelta exportada está incompleta, es out-lap/in-lap o tiene GPS deficiente.

---

# 7. Qué genera `detect_track_turns.py`

```text
*_turn_candidates.csv
*_turn_candidates.json
```

Cada candidato contiene, entre otros:

- `start_distance_m`;
- `center_distance_m`;
- `end_distance_m`;
- `direction` (`left` / `right`);
- curvatura pico;
- cambio de heading estimado.

## Regla crítica

`candidate_number` **NO es todavía un número oficial de curva**.

El detector:

1. calcula curvatura geométrica;
2. encuentra máximos locales;
3. aplica separación espacial;
4. ordena los candidatos por distancia.

Una curva larga puede producir varios máximos y un complejo puede quedar fusionado. Por eso el propio detector advierte que los candidatos no deben recibir nombres automáticamente.

---

# 8. Asignar números y nombres de curva

Este paso es humano/verificado.

## 8.1 Abrir la geometría

Usar el `*_track_gps.geojson` de una de las sesiones.

## 8.2 Usar un mapa verificado del mismo layout

Comparar la secuencia completa desde la línea de meta, en el mismo sentido de marcha.

Para cada curva anotar:

```text
turn
name
direction
candidate/apex aproximado
```

Si una curva no tiene un nombre verificado, usar un nombre neutral:

```text
Turn 4
```

Es preferible `Turn N` a inventar un nombre.

## 8.3 Complejos de varias curvas

El perfil diferencia `name` de `group`.

Ejemplo conceptual:

```json
{
  "turn": 1,
  "name": "Nombre del complejo",
  "group": "Nombre del complejo"
},
{
  "turn": 2,
  "name": "Nombre del complejo",
  "group": "Nombre del complejo"
}
```

Cuando un episodio abarca materialmente ambas, `track_location.py` puede mostrar:

```text
T1–T2 — Nombre del complejo
```

No agrupar curvas sólo porque están cerca: el `group` debe representar un complejo realmente nombrado/entendido como una unidad.

---

# 9. Cruzar las dos sesiones

No construir el perfil final mirando una sola sesión.

Para cada curva oficial:

1. localizar el centro/ápice geométrico en sesión A;
2. localizar el mismo giro y dirección en sesión B;
3. comprobar que ambos aparecen en la misma región de `Lap Dist`;
4. medir el offset entre centros;
5. investigar cualquier diferencia grande antes de aceptar el punto.

## Convención de validación usada actualmente en los perfiles del proyecto

Como referencia práctica:

```text
|offset de ápice| <= 35 m  -> PASS
35–70 m                   -> WARNING / revisar
> 70 m                     -> FAIL / no validar
```

No es una ley física. Es una tolerancia de calibración del mapa de ubicación.

Antes de usar `VALIDATED_MULTI_SESSION`, el objetivo es:

- misma secuencia de curvas;
- misma dirección por curva;
- ningún offset inexplicable;
- cobertura consistente en ambas sesiones.

Para un perfil robusto, el `apex_m` final puede partir de la mediana de los ápices compatibles entre sesiones y luego verificarse visualmente.

---

# 10. Definir `start_m`, `apex_m` y `end_m`

Estos límites existen para **localización**, no para modelar dinámica vehicular.

## `apex_m`

Punto geométrico representativo de la curva en la coordenada `LMU Lap Dist`.

## `start_m` / `end_m`

Intervalo dentro del cual un episodio debe considerarse materialmente asociado a esa curva.

Punto de partida recomendado:

- usar las regiones `start_distance_m` / `end_distance_m` del detector;
- comparar ambas sesiones;
- ajustar límites para evitar que un máximo amplio absorba una recta o la curva vecina;
- mantener continuidad lógica en complejos de curvas.

No se debe usar el punto de frenada del piloto como límite geométrico de la curva: el perfil debe seguir siendo válido aunque cambie el piloto, setup o clase de auto.

---

# 11. Schema de un track profile

Crear, por ejemplo:

```text
track_profiles\interlagos_profile_v0_1.json
```

Durante construcción usar estado no activo, por ejemplo `DRAFT`.

Estructura mínima:

```json
{
  "schema_version": 1,
  "profile_id": "interlagos-lmu-15turn-v0.1",
  "status": "DRAFT",
  "track": "Autódromo José Carlos Pace",
  "layout": "Autódromo José Carlos Pace",
  "distance_coordinate": "LMU Lap Dist",
  "calibration": {
    "source_session": "...",
    "source_lap_internal_index": 0,
    "geometry_method": "GPS trajectory + signed curvature + verified 15-turn sequence",
    "numbering_scheme": "LMU/WEC Interlagos 15-turn numbering",
    "requires_cross_session_validation": true,
    "validation_status": "PENDING"
  },
  "turns": [
    {
      "turn": 1,
      "name": "Turn 1",
      "aliases": [],
      "group": "Turn 1",
      "direction": "left",
      "start_m": 0.0,
      "apex_m": 0.0,
      "end_m": 0.0
    }
  ]
}
```

Los `0.0` son sólo placeholders de documentación: nunca activar el perfil hasta reemplazarlos por distancias calibradas.

---

# 12. Validar manualmente el mapeo con `track_location.py`

Aunque el perfil siga en `DRAFT`, se puede consultar directamente:

```powershell
python track_location.py "track_profiles\interlagos_profile_v0_1.json" 1200 1280
```

La salida muestra:

- `label`;
- `location_type`;
- overlaps;
- participación de cada curva;
- fase geométrica (`entry`, `apex`, `exit`).

Probar intervalos:

- contenidos completamente dentro de una curva;
- sobre el límite entre dos curvas del mismo complejo;
- salidas de curva;
- rectas entre curvas.

El objetivo es que el nombre sea útil y no engañoso para episodios de telemetría reales.

---

# 13. Activar el perfil

Cuando haya pasado la comprobación de las dos sesiones:

```json
"status": "VALIDATED_MULTI_SESSION"
```

Actualizar también la sección `calibration` con el resumen de validación y usar un `profile_id` de revisión validada, por ejemplo:

```text
interlagos-lmu-15turn-v0.2
```

Guardar en:

```text
track_profiles\
```

## No hace falta modificar `llm_analysis`

El loader actual busca automáticamente `track_profiles\*.json` y sólo activa perfiles cuyo estado sea:

```text
VALIDATED
VALIDATED_MULTI_SESSION
```

La identidad del circuito se compara de forma normalizada (mayúsculas, separadores y acentos no deberían ser un problema). Si existe `layout` tanto en la sesión como en el perfil, también debe coincidir.

---

# 14. Comprobar que el perfil quedó activo

Ejecutar un análisis LLM de ese circuito.

En consola debería aparecer algo equivalente a:

```text
Ubicación de pista: interlagos-lmu-15turn-v0.2 [VALIDATED_MULTI_SESSION]
```

Y en el JSON:

```json
"track_location_profile": {
  "status": "ACTIVE",
  "profile_id": "interlagos-lmu-15turn-v0.2"
}
```

Si aparece:

```text
NO_VALIDATED_PROFILE
```

revisar:

1. `status`;
2. campo `track`;
3. campo `layout`;
4. que el JSON esté en `track_profiles`;
5. que exista `track_location.py` junto al analizador.

---

# 15. Qué archivos conviene conservar por cada calibración

Para reproducibilidad:

```text
telemetria/
  sesión_A.duckdb
  sesión_B.duckdb

track_exports/
  sesión_A_track_gps.csv
  sesión_A_track_gps.geojson
  sesión_A_track_gps_summary.json
  sesión_A_turn_candidates.csv
  sesión_A_turn_candidates.json
  sesión_B_...

track_profiles/
  circuito_profile_v0_2.json
```

No hace falta conservar infinitos outputs temporales en Git, pero sí las dos fuentes de calibración o al menos una referencia clara a ellas y los summaries/candidatos usados para crear el perfil.

---

# 16. Troubleshooting de calibración

## `ERROR: falta el paquete 'duckdb'`

```powershell
python -m pip install -r requirements.txt
```

O, como corrección mínima:

```powershell
python -m pip install duckdb
```

## Faltan `GPS Latitude` / `GPS Longitude`

Ese DuckDB no contiene los canales obligatorios para reconstrucción GPS con la herramienta actual.

No inventar geometría a partir de steering si existe otra sesión con GPS correcto.

## La vuelta automática no sirve

Usar `--lap N` tras revisar la tabla de vueltas que imprime el extractor.

## Los 15 candidatos no parecen corresponder a 15 curvas

No renombrarlos a la fuerza.

Revisar:

- GeoJSON;
- dirección de giro;
- centros en ambas sesiones;
- curvas largas con varios máximos;
- curvas suaves que puedan quedar absorbidas por otra región.

Los parámetros disponibles del detector son:

```text
--step-m
--heading-window-m
--smooth-window-m
--min-separation-m
--threshold-percentile
--turn-count
```

No conviene retunearlos sólo para que el número visual “parezca correcto”. Primero determinar cuál es la causa geométrica del mismatch.

## El perfil existe pero el reporte sigue mostrando metros

El analizador no lo activó. Revisar `status`, `track` y `layout`.

---

# 17. Historial persistente

El proyecto ya contiene una base histórica separada de los DuckDB crudos de LMU.

Inicializar:

```powershell
python session_history.py init
```

Importar un JSON de `analyze_telemetry.py`:

```powershell
python session_history.py import "ARCHIVO.json"
```

Importar una carpeta:

```powershell
python session_history.py import-dir . --recursive
```

Consultar:

```powershell
python session_history.py list
python session_history.py stats
```

Validar:

```powershell
python validate_history_db.py
```

### Importante

La persistencia existe, pero la selección automática de una `historical_reference` y el matcher cross-session todavía deben mantenerse separados del coaching operativo hasta que estén suficientemente calibrados.

---

# 18. Qué revisar antes de considerar buena una nueva versión

## Análisis determinista

- tiempos de vuelta correctos;
- referencia correcta;
- validación temporal `OK`;
- validación objetiva `OK`;
- eventos de freno/acelerador razonables;
- ninguna anomalía inesperada.

## LLM

- sin targets derivados de velocidad;
- sin estabilidad/understeer/oversteer/trayectoria inventados;
- sin causalidad no observada;
- targets espaciales sólo cuando Python los autoriza;
- recurrencia independiente del ranker;
- `next_stint_plan` estable entre backends;
- `global_validation_audit` comprensible.

## Track location

- perfil activo correcto;
- curva correcta en episodios conocidos;
- complejos agrupados correctamente;
- ninguna curva de otro layout/circuito.

---

# 19. Checklist rápido para crear un circuito desde cero

```text
[ ] Tener >= 2 DuckDB del mismo layout
[ ] Instalar duckdb
[ ] Extraer GPS de sesión A
[ ] Extraer GPS de sesión B
[ ] Revisar summaries y vueltas seleccionadas
[ ] Detectar candidatos geométricos en ambas
[ ] Abrir GeoJSON y verificar sentido/geometría
[ ] Confirmar número oficial de curvas del layout
[ ] Asignar números y nombres verificados
[ ] Cruzar dirección + ápice entre sesiones
[ ] Definir start/apex/end en LMU Lap Dist
[ ] Crear profile DRAFT
[ ] Probar intervalos con track_location.py
[ ] Validar segunda sesión
[ ] Documentar offsets y método
[ ] Cambiar a VALIDATED_MULTI_SESSION
[ ] Ejecutar análisis real del circuito
[ ] Confirmar track_location_profile = ACTIVE
[ ] Hacer una segunda sesión de regresión
```

---

# 20. Flujo recomendado para Interlagos ahora

1. Ejecutar `procesar_interlagos_calibracion.ps1`.
2. Revisar los dos `*_track_gps_summary.json`.
3. Comparar los dos `*_turn_candidates.json`.
4. No modificar todavía el analizador LLM.
5. Construir `interlagos_profile_v0_1.json` como `DRAFT`.
6. Mapear T1–T15 contra una referencia verificada del layout.
7. Validar offsets de la segunda sesión.
8. Crear `interlagos_profile_v0_2.json` como `VALIDATED_MULTI_SESSION`.
9. Recién entonces ejecutar la nueva telemetría de Interlagos con DeepSeek y evaluar la generalización de 3.10.7.

---

## Filosofía de mantenimiento

Cuando aparezca un error de análisis, no se debe “hacer pasar” la salida relajando validadores sin entenderlo.

Orden preferido:

```text
hecho determinista
    -> representación estructurada
        -> validación
            -> interpretación LLM
                -> render
```

Cuanto más crítica sea una decisión de coaching, más cerca del inicio de esa cadena debería estar su fuente de verdad.
