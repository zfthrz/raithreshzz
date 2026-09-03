# Race Engineer GUI v1.57

GUI v1.57 makes empty and failed views actionable instead of leaving blank panels
or isolated error text.

- Summary and telemetry direct the user to select or analyze a session.
- History distinguishes a missing compatible reference from a missing comparison.
- Statistics explains how History becomes populated.
- Diagnostics identifies when no pipeline report is selected.
- Load failures retain their technical detail and recommend a safe retry path.

All messages are centralized presentation text. They do not run pipeline stages,
infer telemetry evidence, modify History or relax deterministic validation.
