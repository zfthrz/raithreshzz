# H3 exact-context importer v0.1

`import_h3_context.py` importa en History un único contexto exacto que el gate
oficial ya clasificó como `H3_READY_TO_IMPORT`. No procesa en bloque otros
contextos listos.

El modo predeterminado es read-only. La mutación requiere `--apply`, una identidad
exacta `track + track_layout + vehicle_variant` y, desde la GUI, el fingerprint
observado al pedir confirmación.

Antes del import el comando ejecuta `CHECKPOINT`, crea una copia física en
`data/local/history_backups/` y verifica SHA-256 del origen antes y después de la
copia y del backup. Si History cambia durante esa ventana, falla cerrado. Después
llama al importador oficial transaccional e idempotente y exige `H3_IMPORTED` para
el contexto exacto.

GUI v1.45 agrega `Importar H3` en Track Readiness. Sólo se habilita para la fila
exacta `H3_READY_TO_IMPORT`, no corre en paralelo con análisis o materialización y
refresca ambos audits al terminar. Persiste evidencia observacional: no autoriza
coaching ni modifica ranking o H5.1/H5.2/H5.3.
