# H5.3g — Faster-lap withholding audit v0.1

## Objetivo

Examinar, sin cambiar la política, zonas con pérdida local que fueron retenidas
porque la vuelta actual completa era más rápida que la referencia histórica.

## Contrato

- Python reconstruye la evidencia cuantitativa desde artefactos con SHA-256.
- Solo entran casos revisados `current_faster + WITHHELD`.
- Los labels humanos siguen siendo evidencia observacional.
- No se autoriza una acción automática ni histórica.
- `session_reference` continúa siendo la autoridad de coaching.

## Resultado real inicial

La cola v4 produjo seis casos con evidencia cuantitativa disponible:

- 1 `CORRECTLY_WITHHELD`;
- 1 `WITHHELD_BUT_ACTIONABLE`;
- 4 `AMBIGUOUS`.

La excepción accionable fue Interlagos T12 — Junção: pérdida local de `+0.294 s`
en una vuelta globalmente más rápida. El resultado confirma que una vuelta mejor no
es necesariamente mejor en todas sus zonas, pero una sola decisión no alcanza para
reemplazar la protección anti-regresión.

## Próximo paso seguro

Diseñar una política local experimental, todavía en shadow, que exija evidencia
cuantitativa completa, coherencia física, revisión independiente y fallback a
`WITHHELD`. No modificar producción hasta contar con cobertura multisesión y
multicircuito suficiente.
