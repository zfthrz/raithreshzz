# Race Engineer desktop GUI v1.19

GUI v1.19 hace visible si el scheduler está trabajando normalmente o si la cola
dejó de progresar.

## Señales

- `Scheduler · procesando`: existe un ciclo RUNNING reciente.
- `Scheduler · posible bloqueo`: el ciclo continúa RUNNING después de 15 minutos.
- `Scheduler · último ciclo falló`: el proceso oculto terminó con exit code no cero.
- `Scheduler · sin actividad`: no existe heartbeat durante más de 5 minutos.
- `Scheduler · cola bloqueada`: el primer debrief pendiente acumuló al menos tres
  intentos fallidos con error registrado.

Al hacer clic en el indicador se abre el panel B3. Presenta el archivo afectado,
cantidad de intentos, último error, conteos de cola, tiempos del ciclo y último
ciclo exitoso, con botones para copiar el diagnóstico o abrir el log local.

## Contrato de seguridad

`hidden_history_ingest.py` escribe atómicamente el estado local
`data/local/telemetry_scheduler_runtime.json` al comenzar y terminar cada ciclo.
La GUI sólo lee esa evidencia y `telemetry_auto_ingest.json`: no marca elementos
como completados, no salta fallos y no cambia el orden FIFO.

El bloqueo de LMU y la ventana de estabilidad siguen siendo independientes del
watchdog y permanecen activos para proteger DuckDB que todavía puede estar en uso.

Validación del checkpoint: `1327 passed` en la suite completa.
