# Race Engineer GUI v1.59

GUI v1.59 completes the keyboard-accessibility slice for existing interactions.

- Tables and notebook tabs expose a high-contrast focus ring.
- Summary map and telemetry previews accept focus and open with Enter or Space.
- Next-stint priority cards open their existing inspector with Enter or Space.
- Monthly statistics and calibration rows activate with Enter.
- Global section shortcuts place focus on the selected navigation control.
- Closing shortcut help restores the control that previously held focus.

Keyboard activation delegates to the same handlers used by pointer interaction.
It does not create new pipeline actions or change deterministic authority.
