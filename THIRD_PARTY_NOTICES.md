# Third-party notices

Race Engineer distributions may include the components below. They remain under
their respective licenses; the Race Engineer Personal Use License does not replace
or restrict those terms.

| Component | Release baseline | License | Official source |
|---|---:|---|---|
| Python | 3.12 | Python Software Foundation License Version 2 and incorporated-software notices | [Python 3.12 license](https://docs.python.org/3.12/license.html) |
| NumPy | 2.5.2 | BSD-3-Clause plus licenses for bundled components | [NumPy license](https://numpy.org/doc/stable/license.html) |
| pandas | 3.0.5 | BSD-3-Clause | [pandas license](https://github.com/pandas-dev/pandas/blob/v3.0.5/LICENSE) |
| DuckDB | 1.5.5 | MIT | [DuckDB license](https://github.com/duckdb/duckdb/blob/v1.5.5/LICENSE) |
| python-dateutil | 2.9.0.post0 | Apache-2.0 or BSD-3-Clause | [python-dateutil license](https://github.com/dateutil/dateutil/blob/2.9.0.post0/LICENSE) |
| tzdata | 2026.3 | Apache-2.0 plus upstream timezone-data notices | [tzdata package](https://pypi.org/project/tzdata/2026.3/) |
| six | 1.17.0 | MIT | [six license](https://github.com/benjaminp/six/blob/1.17.0/LICENSE) |
| PyInstaller | 6.22.2 (build tool) | GPL-2.0-or-later with the PyInstaller bootloader exception; some files use Apache-2.0 | [PyInstaller license](https://pyinstaller.org/en/stable/license.html) |

The final Windows artifact must include the complete license and notice files from
the exact Python runtime and dependency wheels used by that build. NumPy in
particular contains separately licensed bundled components. The packaging manifest
must identify the exact versions and hashes; this summary is not a substitute for
those complete texts.

PyInstaller's exception permits executables built from non-free application code to
be distributed under the application's chosen license. PyInstaller is a build
dependency and is not intended to be shipped as an importable application feature.

Le Mans Ultimate and related names and marks belong to their respective owners.
Race Engineer is an independent project and is not affiliated with or endorsed by
the game publisher or developers.
