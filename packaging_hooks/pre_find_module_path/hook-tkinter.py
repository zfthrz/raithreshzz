"""Keep stdlib tkinter discoverable for the isolated local build toolchain."""

# PyInstaller probes Tcl through ``python -I``. The project build toolchain is an
# isolated per-user MSI install whose Tcl registry lookup is unavailable in that
# probe, although the runtime itself is valid. RaceEngineer.spec supplies the
# exact Tcl/Tk data and binaries explicitly.


def pre_find_module_path(hook_api):
    """Retain the standard-library search directories already on the hook API."""
    return None
