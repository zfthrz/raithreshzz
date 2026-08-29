# H3 exact-context materializer v0.1

`materialize_h3_context.py` une el audit de readiness existente con el pipeline H3
oficial para eliminar la ejecución manual de varios comandos. Procesa un único
contexto exacto y nunca importa History.

El modo predeterminado es read-only:

```powershell
python materialize_h3_context.py `
  --track "Circuit de Spa-Francorchamps" `
  --track-layout "Circuit de Spa-Francorchamps" `
  --vehicle-variant LMP2_ELMS
```

La materialización requiere autorización explícita:

```powershell
python materialize_h3_context.py `
  --track "Circuit de Spa-Francorchamps" `
  --track-layout "Circuit de Spa-Francorchamps" `
  --vehicle-variant LMP2_ELMS `
  --expected-input-fingerprint "HASH_DEL_AUDIT" `
  --apply
```

## Contrato

- exige coincidencia exacta de track, layout y vehicle variant;
- acepta únicamente `MATERIALIZATION_READY`;
- el fingerprint opcional bloquea una confirmación obsoleta;
- ejecuta el pipeline oficial con `history_db=None`;
- exige tres outputs físicos y `history_mutated=false`;
- vuelve a ejecutar el readiness oficial y exige `H3_READY_TO_IMPORT`;
- no importa History ni autoriza coaching.

El bundle resultante continúa requiriendo la importación explícita separada mediante
`maintain_h3_imports.py --apply`. La GUI debe reutilizar este comando y mostrar su
resultado, no duplicar lógica de H2/H3.
