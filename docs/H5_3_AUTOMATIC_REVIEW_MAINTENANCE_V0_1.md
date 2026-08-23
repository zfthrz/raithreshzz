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
historical_actions_authorized: false
```
