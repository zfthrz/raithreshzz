"""Packaged safe-analysis process for the public Windows distribution."""

from public_runtime import configure_public_runtime

configure_public_runtime()

from analyze_telemetry_file import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
