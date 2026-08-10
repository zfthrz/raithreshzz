# History Neutral Accounting Fix v1.0

`analyze_telemetry.py v3.8` define la contabilidad temporal como:

```text
net_from_components =
    gross_loss
    - gross_gain
    + neutral_delta
```

`session_history.py` ya persiste `neutral_delta_s` en `comparisons`.

El validator anterior omitía ese término y podía producir falsos FAIL cuando
`neutral_delta_s != 0`.

Este parche corrige exclusivamente la validación. No modifica ni reconstruye
la History DB.
