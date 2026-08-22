# Race Engineer desktop GUI v1.5

GUI v1.5 completes the first H6.5 visual-polish slice without changing the
Tkinter/ttk framework or any data/analysis behavior.

## Presentation changes

- flat dark entries and readonly comboboxes with explicit focus/disabled states;
- dark combobox dropdown lists consistent with the main window;
- 10 px vertical and horizontal scrollbars with restrained hover/pressed states;
- flatter general, analysis and accent buttons with coherent disabled feedback;
- modernized session Treeview rows, headings and teal selection treatment;
- alternating rows in the session and History lists for easier scanning;
- cleaner notebook tabs with selected, hover and disabled states;
- compact 5 px progress indicator;
- consistent dark Panedwindow chrome.
- aligned text, map and telemetry surfaces with the same dark palette;
- clearer hierarchy and spacing in the backend configuration dialog.

## Preserved contracts

- session discovery, filtering and History remain unchanged;
- map and telemetry synchronization remain unchanged;
- P9/P10/P11 and `next_stint_plan` remain unchanged;
- the GUI remains downstream of validated structured data;
- no detector, threshold, ranking, action eligibility or coaching authority changed.

This is presentation-only and does not require a telemetry calibration session.
