# Roadmap de desarrollo independiente con LLM local v1.1

## Propósito

Este documento permite retomar Race Engineer con un LLM local actuando como agente de
desarrollo. No habilita un LLM dentro del producto ni cambia la autoridad de coaching.
El runtime público continúa siendo determinista y sin llamadas automáticas a modelos.

Los documentos canónicos siguen siendo, en este orden:

1. `AGENTS.md`;
2. `PROJECT_CONTEXT.md` completo;
3. `PROJECT_STATUS.md`;
4. código y tests actuales;
5. `docs/PRODUCT_PERFECTION_ROADMAP_V1_0.md`;
6. este plan operativo.

Los handoffs fechados y `legacy/` sirven como procedencia. No definen el estado actual.

## Cambios respecto a v1.0

Este v1.1 preserva íntegramente los horizontes L0–L10 del v1.0 y agrega:

- **L11 — Cierre semi-automático de evidencia shadow.** Detección determinista de
  qué evidencia falta para promover una política shadow, priorización de la cola
  humana de revisión y proyección de proximidad a la puerta. Sin auto-promoción,
  sin auto-labeling, sin LLM.
- **L12 — Ciclo de vida de la base analítica.** Tratamiento del análisis como activo
  permanente de la app (no caché), con tiering caliente/tibio/frío, proyección de
  crecimiento a 5–10 años y política de retención explícita. Nada se borra.

Sub-fases tácticas incorporadas dentro de horizontes existentes:

- **L0.x** — Integridad del baseline (skip markers para tests platform-dependent y
  fixture ausente, actualización de `PROJECT_STATUS.md`).
- **L1.x** — Checks nativos pendientes de R4 (DPI, LMU coexistencia, sesión UI,
  FOCUS, clipboard, clean-account).
- **L4.x** — Refuerzo de priorización de la cola de revisión H5.3 (anotación por
  dimensión de evidencia).
- **L7.x** — Extensiones analíticas deterministas (stints, combustible, sectores,
  comparación intra-sesión, tabla personal, exportación CSV/JSON).

Las fases B, C, D, F, G, H, I, J del borrador táctico v0.2 quedan disueltas en
L0–L9 y no tienen horizonte propio. La visualización 3D queda como extensión futura
de L7 sin horizonte propio ni fecha.

## Checkpoint de partida

Checkpoint verificado al 2026-09-11:

- HEAD `423707f — prepare Race Engineer 0.1.0 release candidate`;
- `main` sincronizada con `origin/main`;
- working tree limpio;
- 219 archivos de test trackeados, 2070 tests colectables;
- en Codespaces: 2063 passed, 3 failed (platform-dependent: `tasklist` de Windows y
  separador de path), 4 errors (fixture ausente: `audit_dataset_full.json`);
- regresiones deterministas: 55/55 passed;
- recovery check: READY;
- `git diff --check`: limpio;
- 19 perfiles de producción, 6 perfiles `shadow_v2`;
- RC 0.1.0 funcional, pendiente sólo de firma visual nativa R4.

Antes de iniciar trabajo futuro, verificar este checkpoint contra `git log`,
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

---

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

### L0.x — Integridad del baseline

Objetivo: que el conteo de tests sea honesto y portable entre entornos.

Problema observado al HEAD `423707f`:

- 3 tests fallan en Codespaces/Linux por dependencia de `tasklist` de Windows y por
  separador de path (`tests/test_auto_ingest_telemetry.py` ×2,
  `tests/test_cross_session_context.py` ×1);
- 4 tests de `tests/test_historical_candidate_eligibility.py::TestRetrospectiveReplay`
  error porque requieren `data/generated/h5_3/audit_dataset_full.json`, un artefacto
  runtime ausente en un checkout sin telemetría.

Trabajo:

- añadir markers explícitos `requires_windows` y `requires_local_fixture` en
  `pytest.ini`;
- decorar los tests afectados para que se salteen en el entorno incorrecto;
- actualizar `PROJECT_STATUS.md` con el conteo real (2070 colectables, no 2065).

Puerta: Codespaces reporta `2063 passed / 7 skipped`; Windows nativo reporta
`2070 passed`; `git diff --check` limpio.

Sin bloqueo. Ejecutable ya.

---

## Horizonte L1 — Cerrar perfiles y release inicial

### L1a — Perfiles restantes

Para cada perfil pendiente:

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

### L1.x — Checks nativos pendientes

Objetivo: cerrar los checks de R4 que requieren Windows nativo y LMU.

Bloqueo: el propietario, con acceso a Windows + LMU.

Trabajo:

- otra escala DPI;
- coexistencia con LMU mientras el scheduler corre;
- sesión nativa corta y larga en español e inglés;
- navegación Detail → Telemetry;
- apertura de FOCUS y verificación del plan completo debajo;
- clipboard (copiar checklist, solo acciones);
- instalación en cuenta limpia y desinstalación preservando datos retenidos.

Puerta: `PUBLIC_RELEASE_R4_QA_2026_09_09.md` sin bloqueos pendientes.

Sin bloqueo de código. Requiere intervención humana.

---

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
| 0–3 meses | cerrar L0.x, L1 y establecer L2 | L11.1–L11.4 (manifest y clasificador) | release recuperable, snapshot de cobertura |
| 3–9 meses | L3 motor determinista | L6 cobertura, L7, L12.1–L12.3 | corpus estable, política de storage |
| 9–18 meses | L4 calidad de coaching | L5 personalización shadow, L11.5–L11.6, L12.4–L12.6 | scorecard y revisión humana suficientes |
| 18–30 meses | L5 promoción mínima | L8 arquitectura, L9 distribución, L12.7 | rollback y fallback probados |
| más de 30 meses | L10 investigación y L11 cierre de gaps | mantenimiento continuo | demanda y datos que justifiquen complejidad |

Las ventanas no son deadlines. Si no existe evidencia suficiente, se mantiene el
horizonte actual o se cierra una hipótesis como no útil.

---

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

---

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

---

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

### L4.x — Priorización de la cola de revisión H5.3

Objetivo: que la revisión humana no tenga que recorrer la cola entera para descubrir
qué ítems son relevantes a gaps abiertos.

Trabajo:

- cuando `maintain_h5_3_action_review.py` crea o expande una revisión numerada, un
  clasificador determinista anota cada ítem pendiente con:
  - `contributes_to_gaps`: lista de dimensiones de evidencia que el ítem toca;
  - `redundant_coverage`: si el ítem no agrega dimensión nueva;
  - `priority`: `HIGH` si toca un gap abierto, `NORMAL` si agrega cobertura, `LOW`
    si es redundante;
- el labeler interactivo muestra esos tags;
- la semántica de `SAME / DIFFERENT / AMBIGUOUS / SKIP` no cambia;
- el validador de labels no cambia;
- los tests existentes de H5.3 siguen pasando.

Es priorización, no auto-labeling. El humano decide igual que antes.

Puerta: el labeler muestra los tags; los tests existentes pasan sin cambios; no se
introduce ninguna autoridad nueva.

Depende de L4 maduro. No requiere L11 completo.

---

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

---

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

---

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

### L7.x — Extensiones analíticas deterministas

Objetivo: agregar valor analítico al piloto sin tocar coaching, autoridad ni LLM.

Todas las extensiones son deterministas puras, con contrato propio, validator y tests.

- **L7.x.1 — Análisis de stint y degradación.** Consumo de combustible por vuelta,
  degradación por sector, consistencia de tiempos de stint. Extensión de
  `analyze_telemetry.py`, sin LLM.
- **L7.x.2 — Calculadora de combustible y estrategia.** Consumo medio, vueltas
  restantes, margen de seguridad. Determinista puro.
- **L7.x.3 — Comparación intra-sesión (vuelta A vs B).** Reutiliza `DeltaComparison`
  y alineación por distancia. Distinta de H5.2 (que es cross-session).
- **L7.x.4 — Sectores y consistencia.** Descomposición en sectores deterministas,
  comparación entre vueltas válidas. No requiere perfil de circuito validado.
- **L7.x.5 — Tabla de clasificación personal.** Mejores vueltas por circuito,
  categoría y variante dentro del propio History. Extiende
  `race_engineer_statistics.py`. Sin backend, sin comunidad.
- **L7.x.6 — Exportación CSV/JSON.** Tablas de vueltas, canales y eventos.

Cada sub-extensión se cierra por separado con su propia puerta: contrato determinista,
validator, tests, UI sin cambio de autoridad.

Paralelizable con L5, L6, L8 cuando sus dependencias internas lo permitan.

---

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

---

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

---

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

---

## Horizonte L11 — Cierre semi-automático de evidencia shadow

Objetivo: que el sistema sepa qué evidencia falta para promover una política shadow,
detecte cuando la telemetría nueva la aporta y priorice la revisión humana. Sin
auto-promoción, sin auto-labeling, sin LLM.

Contexto: hoy la puerta de promoción H5.3f v0.2 evalúa requisitos codificados dentro
del propio gate. Cuando la evidencia está incompleta, el operador debe revisar la cola
manualmente para descubrir qué falta. L11 automatiza esa detección sin cambiar la
autoridad del gate.

Principio rector:

- read-only;
- determinista;
- sin auto-promoción;
- sin auto-labeling;
- sin LLM;
- el humano sigue decidiendo.

### L11.1 — Manifest explícito de requisitos

Externalizar los requisitos del gate H5.3f v0.2 a una estructura nombrada y legible:

- `required_tracks`;
- `required_delta_signs`;
- `required_isolated_branches`;
- `max_non_affirmative_labels`;
- `min_reviewed_items`.

El gate sigue siendo la autoridad; el manifest sólo hace explícito qué evalúa.

Puerta: el gate consume el manifest en vez de tener las listas duplicadas; tests
existentes pasan sin cambios.

### L11.2 — Clasificador de cobertura

Script nuevo (`audit_h5_3f_coverage.py` o nombre equivalente) que lee queue, labels y
veredicto vigente, y emite por requisito: `SATISFIED / MISSING / BLOCKING`, con
conteos y `next_priority`.

Snapshot ejemplo:

```json
{
  "gate_verdict": "EVIDENCE_INCOMPLETE",
  "requirements": {
    "isolated_increase_brake": {"status": "MISSING", "queue_candidates": 0},
    "isolated_reduce_brake": {"status": "MISSING", "queue_candidates": 0},
    "current_faster_coverage": {"status": "SATISFIED", "reviewed": 5}
  },
  "next_priority": "Need sessions producing isolated brake-only actions",
  "authority": "OBSERVATIONAL_ONLY"
}