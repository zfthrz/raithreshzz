# Race Engineer 0.1.0

Status: **release candidate 1 — publication pending native visual sign-off**

Race Engineer 0.1.0 is the first portable Windows release candidate. It analyzes
closed Le Mans Ultimate DuckDB telemetry, stores each user's state separately and
produces a deterministic coaching debrief without calling an LLM.

## Included

- portable Windows x64 folder with embedded Python 3.12.10;
- public interface in Español and English;
- deterministic analysis, Summary, Telemetry, History and Statistics;
- new deterministic debriefs in the selected language;
- 13 validated exact track/layout profiles;
- per-user History, statistics, preferences and generated reports under
  `%LOCALAPPDATA%\RaceEngineer`;
- installation, update, retention, privacy and license documentation.

## Exact profile catalog

1. Algarve International Circuit;
2. Autodromo Enzo e Dino Ferrari;
3. Autodromo Nazionale Monza;
4. Autódromo José Carlos Pace;
5. Bahrain International Circuit;
6. Circuit de Barcelona;
7. Circuit de la Sarthe;
8. Circuit de Spa-Francorchamps;
9. Daytona International Speedway Road Course;
10. Fuji Speedway;
11. Sebring International Raceway;
12. Silverstone Grand Prix Circuit — WEC;
13. WeatherTech Raceway Laguna Seca.

The build manifest records the selected profile ID, version and SHA-256 for every
entry. Unsupported or non-exact layouts remain usable in metres but do not receive
named-corner localization.

## Known limitations

- LMU must be closed and the telemetry file stable before analysis.
- The public application does not provide live telemetry analysis.
- Existing reports retain their original language when the application language
  changes.
- Historical H3/H4/H5 evidence remains observational; it does not replace the current
  session as coaching authority.
- Calibration, diagnostics and operator tools are excluded from the public interface.
- The portable build is not code-signed; Windows may display publisher reputation
  warnings.
- Windows 11 x64 is the validated build platform. Other Windows/DPI combinations need
  their own native confirmation.

## Installation and data

Extract the complete folder and run `RaceEngineer.exe`; Python is included. Updates
go into a new folder. Removing the application folder preserves telemetry and user
state. See `PUBLIC_INSTALLATION.md` for the complete bilingual procedure.

Telemetry and reports stay local. The deterministic public runtime makes no automatic
network or LLM request. The project does not claim ownership of user telemetry or the
reports generated from it.

## Support

Report reproducible defects through the public repository's GitHub Issues page:
`https://github.com/zfthrz/raithreshzz/issues`.

Include the release version, Windows version, exact track/layout and the visible error.
Do not attach telemetry unless you intentionally choose to share it.
