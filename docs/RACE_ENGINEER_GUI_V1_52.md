# Race Engineer GUI v1.52

`Circuitos → Readiness` ahora consume el estado operativo unificado
`data/local/h3_automation_status.json`.

La cabecera muestra si ambos audits H3 están vigentes y resume cuántos contextos
requieren materialización o importación explícita. Si el estado falta, es inválido,
está vencido o declara autoridad/mutación, la interfaz falla cerrada.

Los botones conservan dos gates independientes:

1. el estado unificado debe autorizar la próxima acción exacta;
2. el snapshot específico de materialización/importación debe seguir válido y
   coincidir con el mismo track, layout y variante.

Después de una operación explícita exitosa, la GUI recompone inmediatamente el
estado unificado desde los audits recién actualizados. Un fallo marca el flujo como
vencido y retiene nuevas acciones hasta refrescar los audits.

La versión no ejecuta `--apply` automáticamente, no modifica thresholds, patrones,
History ni autoridad de coaching fuera de las acciones explícitamente confirmadas
que ya existían en v1.44/v1.45.
