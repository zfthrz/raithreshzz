# Race Engineer GUI v1.56

GUI v1.56 unifies secondary navigation across the workspaces that contain more
than one view.

- History exposes `Referencia` and `Comparación` through the same notebook seam.
- Statistics separates `General` summaries from the `Mensual` session table.
- Diagnostics keeps `Pipeline` and `Ejecución` under the same contract.
- `Ctrl+PageUp` and `Ctrl+PageDown` cycle the current workspace subview.
- The last valid subview per workspace is restored from local GUI preferences.
- Invalid or corrupt preferences are ignored without changing runtime state.

This is presentation-only. It does not alter telemetry, History contents,
coaching, H3 automation, calibration, validators or deterministic authority.
