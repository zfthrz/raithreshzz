# Roadmap de desarrollo independiente con LLM local v1.0

## Propósito

Este documento permite retomar Race Engineer más adelante con un LLM local actuando
como agente de desarrollo. No habilita un LLM dentro del producto ni cambia la
autoridad de coaching. El runtime público continúa siendo determinista y sin llamadas
automáticas a modelos.

Los documentos canónicos siguen siendo, en este orden:

1. `AGENTS.md`;
2. `PROJECT_CONTEXT.md` completo;
3. `PROJECT_STATUS.md`;
4. código y tests actuales;
5. `docs/PRODUCT_PERFECTION_ROADMAP_V1_0.md`;
6. este plan operativo.

Los handoffs fechados y `legacy/` sirven como procedencia. No definen el estado actual.

## Checkpoint de partida

Checkpoint publicado: `e71bac3 — add validated Barcelona profile`.

- `main` sincronizada con `origin/main` al crear este roadmap;
- GUI pública v1.74;
- 13 perfiles exactos de producción;
- Barcelona `barcelona-lmu-fia14-v0.1`, validado multisesión;
- suite completa: 2065 passed;
- regresiones deterministas: 55/55 passed;
- auditor público: `READY`;
- R4 abierto por pruebas manuales, lifecycle y telemetría empaquetada;
- tres perfiles objetivo todavía sin nombre ni archivos confirmados;
- ningún LLM automático en la aplicación pública.

Antes de iniciar trabajo futuro se debe verificar este checkpoint contra `git log`,
`git status`, los documentos canónicos y el código. Si el repositorio avanzó, el
estado nuevo reemplaza esta fotografía.

## Reglas de autonomía

El LLM local puede realizar sin consulta intermedia:

- inspección read-only de código, tests, JSON y telemetría cerrada;
- creación de exports nuevos bajo `track_exports/` y estado bajo `data/local/`;
- cambios pequeños y coherentes dentro de una tarea expresamente elegida;
- tests focalizados, suite completa, regresiones y auditorías read-only;
- actualización de documentación del mismo cambio;
- stage explícito y un commit coherente cuando todas las pruebas requeridas pasan.

Debe detenerse y pedir una decisión para:

- publicar, taggear, hacer push o crear una release;
- borrar datos, exports, builds, History, telemetría o artefactos locales;
- promover una política de coaching o personalización desde shadow;
- cambiar tolerancias, validators, gates o autoridad para obtener un PASS;
- adivinar los tres circuitos restantes, una identidad LMU o nombres de curvas;
- migrar estado persistente sin estrategia probada de rollback;
- firmar un artefacto o elegir identidad pública, versión o canal de soporte.

Nunca usar `git reset --hard`, `git clean`, `git checkout .`, `git restore .`,
`git stash`, `git add .`, `git add -A` ni `git add --all`.

## Unidad de trabajo recomendada

Una sesión del LLM debe cerrar una sola unidad revisable:

1. declarar objetivo y capa propietaria;
2. inspeccionar código y contratos actuales;
3. reproducir o medir el problema;
4. realizar el cambio mínimo;
5. agregar una regresión que falle por el defecto real;
6. ejecutar pruebas focalizadas;
7. ejecutar `python -m pytest -q` si cambió código;
8. ejecutar regresiones deterministas si afecta análisis o integración;
9. ejecutar `git diff --check` y revisar el diff completo;
10. stagear sólo los archivos declarados;
11. crear un commit descriptivo;
12. actualizar el checkpoint sin hacer push salvo orden explícita.

No acumular en un mismo commit un perfil, una política histórica y un rediseño visual.
Si aparece un defecto lateral reproducible, corregirlo en un commit separado antes de
volver al objetivo principal.

## Horizonte L0 — Mantener un handoff confiable

Objetivo: que cada reanudación detecte el estado real y preserve trabajo ajeno.

- Verificar branch, HEAD, upstream y working tree.
- Leer completamente los tres documentos obligatorios.
- Comparar versiones y baselines documentados con el código.
- Inventariar datos locales por nombre y hash, sin moverlos ni borrarlos.
- Registrar qué comprobaciones requieren Windows nativo, LMU o intervención humana.
- Mantener `PROJECT_STATUS.md` breve y colocar informes extensos en `docs/`.

Salida: el agente puede explicar qué está terminado, qué está bloqueado y cuál es la
próxima unidad de trabajo sin apoyarse en memoria conversacional.

## Horizonte L1 — Cerrar perfiles y release inicial

### L1a — Tres perfiles restantes

Para cada perfil:

- esperar nombre exacto y al menos una sesión real;
- leer `docs/TRACK_PROFILE_CREATION_AND_VALIDATION.md`;
- confirmar `TrackName`, `TrackLayout`, categoría, coche y sesiones independientes;
- exportar todas las vueltas completas a directorios nuevos;
- construir primero `VALIDATED_SINGLE_SESSION`;
- auditar otra sesión sin relajar tolerancias;
- promover explícitamente sólo con evidencia `READY_FOR_EXPLICIT_PROMOTION`;
- ejecutar test específico, validadores, suite completa y regresiones;
- confirmar que el auditor público incorpora la nueva identidad exacta.

No usar una categoría distinta para afirmar independencia cuando existan las sesiones
del contexto solicitado. Diferentes coches o categorías pueden validar geometría sólo
cuando el contrato existente lo permite y la procedencia queda declarada.

### L1b — R4

- Mantener `docs/PUBLIC_RELEASE_R4_QA_2026_09_09.md` como matriz de evidencia.
- Usar un DuckDB retenido exclusivamente para QA empaquetada, siempre read-only.
- Completar estados de sesión cortos/largos, no-debrief, History-only y error.
- Completar FOCUS, Detail a Telemetry, clipboard y saltos del debrief.
- Probar otra escala DPI, clean-account lifecycle y coexistencia con LMU.
- Repetir tests y reconstruir el RC después del último perfil o defecto.

### L1c — R5

- Preparar nombre, versión semántica, soporte, privacidad y limitaciones como propuesta.
- Esperar decisión del propietario antes de fijarlos.
- Construir desde un commit limpio y taggeado sólo con autorización.
- Comparar catálogo, checksums, dependencias y notices contra el manifest final.
- Publicar únicamente después de firmar R4.

Salida: primera release pública reproducible con el catálogo objetivo congelado.

## Visión de mediano y largo plazo

La release pública es un hito temprano, no el destino del proyecto. La evolución se
organiza en siete líneas permanentes:

1. **verdad telemétrica:** ampliar lo que Python puede medir sin inventar hechos;
2. **calidad del coaching:** convertir evidencia autorizada en acciones más precisas,
   estables y fáciles de ejecutar;
3. **aprendizaje longitudinal:** adaptar la presentación y prioridad al historial real
   del usuario sin crear autoridad opaca;
4. **cobertura:** sumar circuitos, variantes, categorías y condiciones con gates
   explícitos;
5. **experiencia:** hacer que análisis, comparación y debrief sean claros, rápidos y
   accesibles en Español e inglés;
6. **plataforma:** reducir costo de mantenimiento, mejorar diagnóstico, rendimiento y
   reproducibilidad;
7. **distribución:** sostener releases, datos y migraciones sin comprometer el estado
   del usuario.

Cada ciclo trimestral debe elegir como máximo una iniciativa principal y una de
mantenimiento. No se mide progreso por cantidad de features sino por evidencia nueva,
menor tasa de error o una tarea de usuario claramente mejor resuelta.

Orden sugerido, contado desde la reanudación futura y sujeto a la evidencia disponible:

| Ventana orientativa | Prioridad principal | Trabajo secundario | Gate para avanzar |
| --- | --- | --- | --- |
| 0–3 meses | cerrar L1 y establecer L2 | defectos y perfiles confirmados | release recuperable y métricas base |
| 3–9 meses | L3 motor determinista | L6 cobertura y L7 fricción crítica | corpus estable y mejoras medidas |
| 9–18 meses | L4 calidad de coaching | L5 personalización en shadow | scorecard y revisión humana suficientes |
| 18–30 meses | promoción mínima de L5 | L8 arquitectura surgida de problemas reales | rollback y fallback probados |
| más de 30 meses | L9 ecosistema y L10 investigación | mantenimiento continuo | demanda y datos que justifiquen complejidad |

Las ventanas no son deadlines. Si no existe evidencia suficiente, se mantiene el
horizonte actual o se cierra una hipótesis como no útil.

## Horizonte L2 — Estabilización y observabilidad

Objetivo: conocer el comportamiento real antes de ampliar el motor.

- Mantener un registro local y exportable de versión, error y contexto no sensible.
- Clasificar cada reporte como reproducido, información insuficiente o no reproducido.
- Corregir primero crashes, pérdida de datos, fallos de carga y errores de coaching.
- Instrumentar tiempos de startup, ingestión, análisis, cambio de sesión, render de
  telemetría y scheduler, con medición desactivable y exclusivamente local.
- Medir memoria, tamaño de History y degradación con catálogos y sesiones grandes.
- Crear fixtures sanitizados para errores reales que no dependan del equipo original.
- Verificar cada arreglo en Español e inglés cuando afecte presentación pública.
- Probar dos ciclos completos de actualización y recuperación de estado.

Salida: presupuestos de rendimiento documentados, fallos reproducibles y al menos dos
actualizaciones que preservan preferencias, History, estadísticas y debriefs.

## Horizonte L3 — Evolución del motor determinista

Objetivo: aumentar la calidad de la evidencia antes de agregar nuevas conclusiones.

### L3a — Calidad de entrada

- Detectar sesiones parciales, outlaps, inlaps, pausas, saltos de muestreo y canales
  ausentes con estados explícitos.
- Separar calidad del archivo, calidad de vuelta y elegibilidad para comparación.
- Explicar en UI por qué una sesión o vuelta fue excluida.
- Validar unidades, frecuencia, monotonía temporal y coherencia de identidad LMU.

### L3b — Comparaciones más robustas

- Auditar selección de referencia en stint, combustible, neumático, tráfico y clima
  sólo donde existan canales confiables.
- Mejorar alineación espacial y tratamiento de vueltas con trazados incompletos sin
  cambiar la autoridad del delta acumulado.
- Evaluar estabilidad de zonas y eventos entre frecuencias de muestreo diferentes.
- Crear un corpus de regresión multícircuito con casos normales y límites conocidos.

### L3c — Nuevas señales

- Inventariar canales disponibles por coche/categoría antes de diseñar features.
- Incorporar una señal por vez, primero como observación shadow.
- Exigir definición física, unidad, validador, ausencia segura y utilidad demostrada.
- Mantener velocidad como contexto y conservar Python como única fuente de hechos.

Salida: una versión nueva del analizador sólo cuando mejora casos reales sin degradar
el corpus existente y sus límites quedan documentados.

## Horizonte L4 — Calidad y evaluación del coaching

Objetivo: medir si las recomendaciones ayudan, además de comprobar que son válidas.

- Construir un corpus anónimo de debriefs con evidencia, acciones autorizadas y revisión
  humana, separado por circuito, categoría y tipo de problema.
- Evaluar precisión factual, prioridad, estabilidad entre ejecuciones, claridad,
  accionabilidad, carga cognitiva y ausencia de contradicciones.
- Registrar falsos positivos, acciones omitidas y cambios de recomendación sin evidencia
  nueva.
- Probar políticas nuevas en shadow contra la política productiva usando exactamente la
  misma entrada.
- Mantener un conjunto holdout que no se use para ajustar reglas.
- Promover sólo una regla pequeña por vez, con versión, rollback y explicación del cambio.
- Investigar relaciones entre acción recomendada y mejora posterior sin atribuir causalidad
  cuando la telemetría sólo demuestra correlación.

El LLM local puede ayudar a programar, agrupar y preparar revisión. No puede etiquetar
su propia salida como ground truth ni decidir una promoción.

Salida: scorecard repetible por versión del coaching y decisiones de promoción con
casos favorables, fallos y límites visibles.

## Horizonte L5 — Personalización histórica

Objetivo: comprobar utilidad longitudinal antes de cambiar recomendaciones.

- Leer el roadmap H5.3 y los invariantes H3/H4/H5 completos.
- Definir identidades de acción y contexto usando códigos deterministas existentes.
- Construir estados nuevo, repetido, mejorando, estable, empeorando y no disponible.
- Exigir sesiones independientes y contexto compatible.
- Mantener la prioridad productiva intacta y calcular una alternativa shadow.
- Medir acuerdo, diferencias útiles, inestabilidad y casos retenidos.
- Crear una cola de revisión humana sin reutilizarla como ground truth automático.
- Probar que History corrupto, vacío o incompatible vuelve al plan actual sin cambios.
- Mantener estadísticas por instalación: una instalación pública nueva comienza en cero;
  importar historial previo debe ser una acción explícita y validada.

No usar cantidad de repeticiones como severidad, no considerar una ausencia aislada
como resolución y no autorizar una acción que no exista en la sesión actual.

Si la evidencia lo permite, promover en este orden:

1. etiqueta visible “repetido”, “mejorando” o “estable”;
2. explicación de por qué History fue relevante;
3. reordenamiento entre acciones actuales ya autorizadas;
4. selección de foco histórico mediante un gate adicional aprobado.

Cada paso necesita policy versionada, validator, feature flag, fallback determinista,
opción de desactivar y prueba de rollback.

Salida: adaptación auditable que nunca crea hechos ni acciones y que puede desactivarse
sin perder datos.

## Horizonte L6 — Cobertura de circuitos y contextos

Objetivo: ampliar utilidad sin convertir un perfil aproximado en verdad exacta.

- Completar los perfiles pendientes sólo con identidad y telemetría confirmadas.
- Priorizar perfiles según uso real, falta de cobertura y calidad de las sesiones.
- Mantener gates single-session, multisesión y exact-context separados.
- Auditar variantes, cambios de layout y actualizaciones de LMU como identidades nuevas
  cuando el contrato lo requiera.
- Crear reportes de cobertura por circuito, variante, clase y canales disponibles.
- Evaluar perfiles comunitarios en cuarentena antes de cualquier promoción.
- Automatizar tareas mecánicas de exportación y validación sin automatizar la decisión
  de que un perfil es correcto.

Salida: crecimiento del catálogo con trazabilidad por perfil, evidencia recuperable y
cero fallback silencioso entre variantes.

## Horizonte L7 — Experiencia de usuario completa

Objetivo: que la aplicación ayude a decidir la próxima acción con menos esfuerzo.

- Hacer pruebas de uso con tareas concretas: encontrar el mayor problema, entender la
  evidencia, navegar a telemetría y copiar el plan.
- Medir tiempo y errores por tarea, no sólo apariencia visual.
- Perfeccionar estados vacío, carga, error, History-only y sesiones incompatibles.
- Mantener paridad funcional Español/inglés mediante claves estables y pruebas de
  cobertura; el idioma elegido debe gobernar UI y nuevos debriefs.
- Mejorar accesibilidad: teclado, foco, contraste, escalado DPI y lectores de pantalla
  donde el toolkit lo permita.
- Diseñar comparaciones entre sesiones y tendencias sin saturar la pantalla principal.
- Permitir exportar un informe portable con procedencia, versión y limitaciones.
- Mantener calibración, auditorías y herramientas operator-only fuera del flujo público.

Salida: pruebas manuales repetibles y métricas de tareas para los flujos esenciales en
ambos idiomas.

## Horizonte L8 — Arquitectura y mantenibilidad

Objetivo: sostener la evolución sin reescrituras amplias ni contratos implícitos.

- Identificar dependencias reales entre ingestión, hechos, selección, coaching, History
  y presentación antes de extraer módulos.
- Definir contratos serializables y versionados en los límites que ya causen fricción.
- Separar estado de usuario, datos distribuidos, cache regenerable y herramientas de
  desarrollo.
- Agregar migraciones idempotentes, backups verificados y rollback antes de cambiar
  esquemas persistentes.
- Reducir trabajo del hilo de UI y mantener tareas costosas cancelables y observables.
- Auditar scheduler con LMU cuando el entorno lo permita y conservar deferencia total
  de procesos caros mientras el simulador esté activo.
- Revisar compatibilidad al actualizar Python, DuckDB, NumPy, pandas o PyInstaller.
- Actualizar locks, notices y reproducibilidad de builds en el mismo cambio.
- Refactorizar sólo después de caracterizar conducta con tests; no perseguir cobertura
  porcentual sin riesgo concreto.

Salida: límites claros, tiempos previsibles y recuperación probada ante fallos de estado.

## Horizonte L9 — Distribución de datos y ecosistema

Objetivo: decidir con evidencia si los perfiles necesitan paquetes independientes.

Primero medir:

- frecuencia real de perfiles nuevos;
- tamaño y costo de reconstruir la aplicación completa;
- errores de instalación observados;
- compatibilidad del esquema a través de varias versiones.

Si el costo justifica paquetes, implementar por commits separados:

1. schema de manifest y compatibilidad;
2. verificación SHA-256 y firma del publicador;
3. instalación temporal y validación completa;
4. reemplazo atómico sin downgrade;
5. recuperación tras interrupción;
6. interfaz pública de estado y error;
7. pruebas de actualización, rollback y corrupción.

El instalador nunca modifica los perfiles incluidos en el ejecutable. Los paquetes
viven en estado por usuario y el catálogo resuelve de forma determinista cuál versión
válida usar.

Salida: paquete de prueba firmado, reversible y sin autoridad fuera del perfil validado.

## Horizonte L10 — Investigación opcional

Estas iniciativas sólo empiezan con una pregunta medible y datos suficientes:

- comparación de stints bajo condiciones compatibles;
- tendencias por coche, categoría o circuito sin mezclar contextos;
- detección de cambios de técnica a lo largo del tiempo;
- explicaciones interactivas que conecten acción, zona y evidencia;
- evaluación de un modelo local opcional como narrador de evidencia autorizada.

Un modelo dentro del producto, si alguna vez se evalúa, debe ser opcional, local,
reproducible, limitado a códigos/evidencia autorizados y acompañado por una salida
determinista equivalente. Esta posibilidad no forma parte del runtime actual ni queda
autorizada por este roadmap.

Salida: experimento shadow reproducible o una decisión documentada de no continuar.

## Cadencia de planificación

Al comenzar cada ciclo:

1. elegir un problema observado y una métrica de salida;
2. registrar baseline sobre datos existentes;
3. dividirlo en unidades que entren en una sesión del agente;
4. identificar qué decisión sigue siendo humana;
5. fijar criterios de abandono además de criterios de éxito.

Cada cuatro a seis hitos, revisar si el orden sigue siendo correcto. El siguiente
horizonte no se activa por fecha: se activa cuando sus dependencias y evidencia existen.
Archivar roadmaps cerrados como procedencia y crear una nueva versión cuando cambie la
visión, sin reescribir resultados anteriores.

## Comandos mínimos por tipo de cambio

Cambio de código general:

```powershell
python -m pytest -q tests\TEST_FOCAL.py
python -m pytest -q
git diff --check
```

Análisis, orquestación o autoridad determinista:

```powershell
python -m pytest -q
python run_race_engineer_regressions.py --analyzer analyze_telemetry.py
python apply_objective_python_recovery_2026_08_13.py --check analyze_telemetry.py
git diff --check
```

Perfil de circuito:

```powershell
python validate_track_profiles_v0_2.py
python -m pytest -q tests\test_NOMBRE_track_profile.py
python -m pytest -q
python run_race_engineer_regressions.py --analyzer analyze_telemetry.py
python public_release_contract.py
git diff --check
```

Release:

```powershell
python public_release_contract.py
python -m pytest -q
python run_race_engineer_regressions.py --analyzer analyze_telemetry.py
.\build_public_release.ps1 -OutputRoot "data\local\public_builds\RC-NUEVO" -WorkRoot ".test-tmp\pyinstaller-RC-NUEVO"
python public_build_manifest.py "data\local\public_builds\RC-NUEVO\RaceEngineer" --verify
git diff --check
```

Usar `.venv\Scripts\python.exe` si `python` no está disponible en `PATH`.

## Prompt maestro para iniciar una sesión futura

```text
Continuá el desarrollo de raithreshzz directamente sobre main.

Antes de trabajar, leé completamente AGENTS.md, PROJECT_CONTEXT.md y
PROJECT_STATUS.md. Después leé docs/PRODUCT_PERFECTION_ROADMAP_V1_0.md y
docs/LOCAL_LLM_DEVELOPMENT_ROADMAP_V1_0.md. Inspeccioná código y tests actuales;
los documentos legacy no son fuente de verdad.

No llames ningún LLM como parte del producto. Python conserva toda autoridad
determinista. No debilites validators ni gates. No inventes telemetría, identidades
LMU, nombres de curvas, tolerancias o resultados visuales.

Preservá todos los datos locales y cambios ajenos. No borres nada sin autorización.
No uses git reset --hard, git clean, git checkout ., git restore ., git stash,
git add ., git add -A ni git add --all.

Objetivo de esta sesión: [UNA SOLA UNIDAD DEL ROADMAP].

Reproducí o medí antes de editar. Implementá el cambio mínimo en la capa propietaria,
agregá una regresión significativa, ejecutá pruebas focalizadas y todos los checks que
correspondan. Revisá el diff, stageá sólo archivos explícitos y creá un commit
coherente. No hagas push, tag, publicación ni promoción de una política shadow sin
orden explícita.

Reportá evidencia, archivos modificados, pruebas, commit y pendientes reales.
```

## Plantilla de cierre de cada sesión

```text
Objetivo:
Resultado:
Evidencia real usada:
Archivos modificados:
Datos locales creados y preservados:
Pruebas focalizadas:
Suite completa:
Regresiones deterministas:
Auditorías adicionales:
Commit:
Push/tag/release:
Pendientes y bloqueos:
Próxima unidad segura:
```

Si el modelo no puede comprobar una UI nativa, una sesión LMU o un dato externo, debe
marcarlo pendiente y entregar pasos manuales exactos. Nunca debe simular un resultado.
