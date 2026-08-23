# H5.3 automatic review maintenance v0.1

## Alcance

Automatizar únicamente el trabajo mecánico posterior a la aparición de nuevos
artefactos `historical_actions.json`:

1. validar todas las fuentes;
2. reconstruir determinísticamente la cola;
3. detectar si realmente cambió;
4. crear la siguiente revisión numerada sin sobrescribir;
5. migrar solo labels con `review_id` y snapshot exactos;
6. informar casos pendientes.
7. con cero pendientes, reconstruir y validar H5.3g, H5.3h y H5.3i.

## Exclusiones

La automatización no:

- llama a un LLM;
- crea o infiere labels humanos;
- abre el labeler;
- cambia políticas o umbrales;
- autoriza acciones históricas;
- bloquea el mantenimiento de History si falla.

## Ejecución oculta

`hidden_history_ingest.py` la ejecuta después de un mantenimiento exitoso. Comparte
el mismo log sin abrir otra consola. Un error se registra como
`H5.3 REVIEW WARNING`, mientras History conserva su resultado exitoso.

## Estado

`data/local/h5_3_review_maintenance.json` contiene la revisión actual, sus paths y
`pending_review_count`. El primer checkpoint real encontró 8 artefactos y devolvió:

```text
status: UP_TO_DATE
current_revision: 5
review_item_count: 23
pending_review_count: 0
downstream_status: AUDITS_CURRENT
historical_actions_authorized: false
```

El checkpoint automático v5 reconstruyó 9 casos `current_faster + WITHHELD`, 3
candidatos locales no autorizados, 0 recurrencias exactas y 1 patrón transversal.
Si existe aunque sea un label pendiente, `downstream_status` queda
`WAITING_FOR_HUMAN_REVIEW` y no se ejecutan los auditores posteriores.
