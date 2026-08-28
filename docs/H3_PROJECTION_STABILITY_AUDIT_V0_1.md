# H3.2 projection stability audit v0.1

## Contrato

Este audit inspecciona las proyecciones ya presentes en los artefactos H3.1. No abre
History, no vuelve a ejecutar H2, no llama un LLM y no modifica los JSON de entrada.

Sólo acepta edges que conserven:

- `match_basis=calibrated_h2_match_to_pattern_representative`;
- `matcher_decision.decision=MATCH`;
- `matcher_decision.automatic=true`;
- contexto completo de track/layout/vehicle;
- autoridad H3 exclusivamente observacional.

Agrupa por contexto exacto más `pattern_id`. El número de sesiones proyectadas no es
un threshold y no convierte la proyección en membresía persistida.

## Uso

```powershell
python audit_h3_projection_stability.py
```

Output regenerable:

```text
data/generated/diagnostics/h3_projection_stability_audit.json
```

## Resultado real inicial

```text
edges proyectados:                       102
patrones proyectados:                     27
sesiones proyectadas:                     13
patrones en varias sesiones proyectadas:  21
también vistos como membresía exacta:       6
CORE_SPATIAL_MATCH:                        51
EXTENDED_SPATIAL_CHANNEL_MATCH:            51
violaciones de autoridad/contrato:          0
duplicados/cruces de contexto:              0
```

### Contextos

- Spa LMP2_ELMS: 96 edges, 21 patrones, 12 sesiones. Los 21 patrones aparecen en
  2–8 sesiones proyectadas; ninguno aparece todavía como membresía exacta runtime.
- Interlagos LMP2_ELMS: 6 edges y 6 patrones en una sesión proyectada; los seis
  pattern IDs aparecen además como membresía exacta runtime.

## Conclusión

Spa contiene repetición observacional suficiente para justificar una futura cola
humana de revisión de edges H3.2. Esa cola debe reutilizar la semántica de comparación
H2 y conservar snapshot/provenance exactos. No corresponde persistir, promover ni
crear thresholds a partir de este audit.
