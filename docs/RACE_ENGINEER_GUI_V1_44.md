# Race Engineer GUI v1.44 — explicit H3 materialization

GUI v1.44 integra la materialización H3 en Track Readiness sin trasladar lógica de
H2/H3 a Tkinter.

- `Materializar H3` sólo se habilita al seleccionar un contexto exacto cuyo snapshot
  scheduler-owned sea `MATERIALIZATION_READY`.
- La confirmación muestra track, layout y vehicle variant y aclara que History no se
  importa.
- La GUI pasa el fingerprint observado a `materialize_h3_context.py --apply`.
- La ejecución ocurre en background y se muestra en Diagnóstico.
- Análisis y materialización no pueden ejecutarse simultáneamente.
- Al terminar se refrescan los snapshots read-only de materialización e importación.
- La GUI nunca invoca `maintain_h3_imports.py --apply`.

La operación sigue fail-closed: si el audit cambió, el botón se deshabilita o el
backend devuelve `BLOCKED_STALE_READINESS` antes de escribir el bundle.
