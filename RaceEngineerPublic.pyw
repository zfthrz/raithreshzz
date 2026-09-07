"""Public Windows entrypoint with an embedded-runtime-compatible data layout."""

from public_runtime import configure_public_runtime

configure_public_runtime()

from race_engineer_gui import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(public_release=True))
