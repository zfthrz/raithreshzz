# Creación y validación de track profiles LMU

Esta guía define el procedimiento reproducible para incorporar un circuito o layout
nuevo. Puede ejecutarse manualmente o delegarse a un LLM local, pero el LLM nunca es
autoridad de geometría, nomenclatura ni promoción.

## 1. Contrato y autoridad

```text
DuckDB LMU
  -> export GPS determinista
  -> candidatos de curvatura deterministas
  -> asignación verificada de nombres y numeración
  -> VALIDATED_SINGLE_SESSION (provisional, fail closed)
  -> sesión LMU independiente
  -> audit geométrico read-only
  -> promoción explícita
  -> VALIDATED_MULTI_SESSION (producción)
```

Reglas obligatorias:

- `TrackName` y `TrackLayout` deben coincidir exactamente. Un layout distinto exige
  otro perfil aunque comparta circuito o nombre comercial.
- La coordenada autoritativa es `LMU Lap Dist`; el GPS reconstruye la forma y prueba
  la estabilidad geométrica.
- Nombres y números de curva provienen de fuentes oficiales o de una convención
  local documentada. Nunca se inventan desde texto de un LLM.
- `candidate_number` de `detect_track_turns.py` no es un número oficial.
- Un perfil `VALIDATED_SINGLE_SESSION` no se activa en producción.
- Sólo `VALIDATED` y `VALIDATED_MULTI_SESSION` pueden activarse automáticamente.
- Ningún audit promueve automáticamente un perfil.
- No se relajan intervalos, direcciones ni tolerancias para obtener un PASS.
- Un coche o ritmo diferente es aceptable: importan el mismo layout, la vuelta
  completa y una trazada limpia.

## 2. Evidencia mínima

Para crear un perfil provisional se recomienda una sesión estable y cerrada con tres
vueltas completas y limpias: una vuelta fuente y una o más vueltas de control. Para
promoverlo hace falta otra sesión físicamente independiente y al menos una vuelta
completa utilizable.

Conviene auditar todas las vueltas completas de la segunda sesión y conservar la
mejor evidencia geométrica, no necesariamente la vuelta más rápida. Una vuelta lenta
pero limpia sirve; una vuelta con trompo, corte, salida o GPS incompleto no.

## 3. Estabilidad del DuckDB

No exportar mientras Le Mans Ultimate pueda seguir escribiendo. El flujo automático
usa 600 segundos de estabilidad. Manualmente, cerrar LMU o esperar ese intervalo.
Superar un tamaño mínimo no demuestra que la última vuelta haya terminado.

## 4. Exportar GPS

Inspección y selección automática:

```powershell
python extract_lmu_track_gps.py `
  "C:\ruta\Telemetry\Circuito_P_FECHA.duckdb" `
  --output-dir "track_exports\circuito_profile"
```

Genera CSV, GeoJSON y summary, y muestra duración, cobertura GPS, `Lap Dist`,
recorrido GPS y muestras de cada vuelta. Para una vuelta concreta, usar un directorio
separado para no sobrescribir evidencia:

```powershell
python extract_lmu_track_gps.py `
  "C:\ruta\Telemetry\Circuito_P_FECHA.duckdb" `
  --lap 3 `
  --output-dir "track_exports\circuito_profile_lap3"
```

Una vuelta completa debe tener `Lap Dist` y recorrido GPS cercanos a
`lap_length_m`. El detector de candidatos exige conservadoramente al menos 90% en
ambas medidas.

## 5. Detectar curvas y asignar nomenclatura

```powershell
python detect_track_turns.py `
  "track_exports\circuito_profile\SESION_track_gps.csv" `
  --turn-count N `
  --output-dir "track_exports\circuito_profile"
```

Construir `track_profiles/<circuito>_profile_v0_1.json` con:

- identidad LMU exacta y `lap_length_m`;
- sesión y vuelta fuente;
- método geométrico y esquema de numeración;
- `turns` ordenados y no solapados, con `start_m <= apex_m <= end_m`;
- dirección verificada, nombres, aliases y complejos documentados;
- fuentes en `provenance.reference_urls` y exports en `provenance.gps_exports`.

Estado inicial obligatorio:

```json
{
  "status": "VALIDATED_SINGLE_SESSION",
  "calibration": {
    "requires_cross_session_validation": true,
    "validation_status": "PASS_SINGLE_SESSION"
  }
}
```

Las curvas suaves o complejos con varios máximos se documentan explícitamente. No se
agregan o eliminan curvas sólo para coincidir con el top-N del detector.

## 6. Comprobar el perfil provisional

```powershell
python validate_track_profiles_v0_2.py
python -m pytest -q tests\test_<circuito>_track_profile.py
python track_location.py "track_profiles\<perfil>.json" 1200 1280
```

El test específico debe confirmar que el perfil provisional falla cerrado en
`find_validated_track_profile()`.

## 7. Encontrar una segunda sesión

```powershell
python discover_track_profile_validation_candidates.py
```

El audit busca perfiles `VALIDATED_SINGLE_SESSION`, exige identidad exacta, excluye
la sesión fuente y comprueba estabilidad, canales GPS y cobertura. Puede escribirse
un reporte sin mutar producción:

```powershell
python discover_track_profile_validation_candidates.py `
  --telemetry-dir "C:\ruta\Telemetry" `
  --output "C:\ruta\candidate_report.json"
```

Estados:

- `READY_FOR_GPS_EXPORT`: independiente, estable y completa;
- `WAITING_STABILITY`: todavía puede estar escribiéndose;
- `NOT_USABLE_FOR_GPS_EXPORT`: canales ausentes o vuelta parcial;
- sin candidato: todavía no hay sesión de identidad exacta.

El reporte entrega comandos, pero conserva `AUDIT_READ_ONLY`, no exporta, no promueve
y no modifica perfiles.

## 8. Auditar todas las vueltas completas

Exportar cada vuelta en su propio directorio y ejecutar:

```powershell
python validate_track_profile_session.py `
  "track_profiles\<perfil>.json" `
  "track_exports\<validacion_lapN>\SESION_track_gps.csv" `
  --output "track_exports\<validacion_lapN>\validation_report.json"
```

Contrato determinista vigente:

- resampling de 2 m;
- ventana de heading de 20 m;
- smoothing de 14 m;
- extremo local de igual dirección dentro del intervalo calibrado;
- PASS hasta 35 m de offset absoluto;
- WARNING entre 35 m y 70 m;
- FAIL por encima de 70 m o sin extremo válido.

`PASS` con `READY_FOR_EXPLICIT_PROMOTION` es evidencia limpia.
`PASS_WITH_WARNINGS` debe compararse con las otras vueltas antes de promover.
`FAIL` o `BLOCKED_CONTRACT` bloquean la promoción.

Caso real: en Laguna Seca la selección automática tuvo un warning de 50 m en T3,
pero las vueltas 1, 3 y 4 dieron 11/11 PASS. Se eligió la vuelta 1: mediana 2.001 m
y máximo 10.001 m. Esto prueba por qué no se debe aceptar la primera vuelta sin
comparar el resto.

## 9. Promoción explícita

La promoción es una edición revisada, nunca una consecuencia automática del exit
code:

```json
{
  "status": "VALIDATED_MULTI_SESSION",
  "calibration": {
    "requires_cross_session_validation": false,
    "validation_status": "PASS",
    "validation_summary": {"independent_sessions": []}
  }
}
```

Registrar sesión/vuelta, tiempo y métricas GPS, método, tolerancias, conteos
PASS/WARNING/FAIL, mediana, máximo y resultado general. Agregar CSV, summary y reporte
a `provenance.gps_exports`. Otras vueltas limpias de la misma sesión pueden quedar en
`additional_complete_laps`, sin contarlas como sesiones independientes.

Actualizar el test para comprobar estado multi-sesión, gate desactivado,
`validation_status`, disponibilidad productiva e invariancia de turnos, direcciones,
intervalos y nombres. Nunca mover ápices para reducir offsets; si la evidencia revela
un problema, el perfil vuelve a revisión geométrica.

## 10. Verificación y commit

```powershell
python -m pytest -q `
  tests\test_<circuito>_track_profile.py `
  tests\test_validate_track_profile_session.py `
  tests\test_discover_track_profile_validation_candidates.py `
  tests\test_track_readiness.py `
  tests\test_project_contract.py

python -m pytest -q
git diff --check
git status --short --branch
```

Stagear sólo perfil, test, documentación, herramientas implicadas y evidencia elegida.
No usar `git add .`, `git add -A` ni incluir exports exploratorios descartados.

## 11. Prompt mínimo para un LLM local

```text
Trabajá directo sobre main y preservá el working tree existente.
No uses git reset/clean/restore/checkout/stash.
No uses git add . ni git add -A.
No inventes nombres, números, direcciones, intervalos ni tolerancias.
TrackName y TrackLayout deben coincidir exactamente.
No uses texto del LLM como autoridad geométrica.
No promociones automáticamente un perfil.
Auditá todas las vueltas completas antes de aceptar warnings.
No cambies H5.1/H5.2/H5.3, ranking, coaching ni validators para hacer pasar un perfil.
Mostrá diff, tests y evidencia antes del commit.
No hagas push salvo autorización explícita.
```

## 12. Estado al 1 de septiembre de 2026

- Portimão: `VALIDATED_MULTI_SESSION`, 15/15 PASS, máximo 22 m.
- Silverstone WEC: `VALIDATED_MULTI_SESSION`, 18/18 PASS, máximo 26 m.
- Laguna Seca: `VALIDATED_MULTI_SESSION`, 11/11 PASS, máximo 10.001 m en
  la evidencia elegida; otras dos vueltas también pasan.
- Bahrain: `VALIDATED_MULTI_SESSION`; cinco vueltas independientes dieron 15/15
  PASS sin warnings, con máximo 13.038 m en la evidencia elegida.
- Sebring: `VALIDATED_MULTI_SESSION`; dos vueltas independientes dieron 17/17 PASS
  sin warnings, con máximo 10 m en la evidencia elegida.
