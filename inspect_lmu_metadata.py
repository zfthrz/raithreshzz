from __future__ import annotations

import argparse
import json
from pathlib import Path

from vehicle_context import extract_lmu_context_from_duckdb


def inspect_file(db_path: Path) -> dict:
    context = extract_lmu_context_from_duckdb(db_path)
    vehicle = context["vehicle_identity"]
    session = context["session_context"]

    return {
        "file": db_path.name,
        "path": str(db_path.resolve()),
        "track_name": session.get("lmu_track_name"),
        "session_type": session.get("lmu_session_type"),
        "vehicle_family": vehicle.get("family"),
        "vehicle_variant": vehicle.get("variant"),
        "car_class_raw": vehicle.get("car_class_raw"),
        "car_name_raw": vehicle.get("car_name_raw"),
        "weather_conditions": session.get("weather_conditions"),
        "setup_sha256": session.get("setup_sha256"),
        "setup_raw_sha256": session.get("setup_raw_sha256"),
        "setup_available": session.get("setup_available"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", default=".")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument(
        "--json-output",
        default="lmu_metadata_inventory.json",
    )
    args = parser.parse_args()

    root = Path(args.directory).resolve()
    pattern = "**/*.duckdb" if args.recursive else "*.duckdb"
    files = sorted(root.glob(pattern))

    rows = []
    errors = 0

    for db_path in files:
        try:
            rows.append(inspect_file(db_path))
        except Exception as exc:
            errors += 1
            rows.append({
                "file": db_path.name,
                "path": str(db_path.resolve()),
                "error": str(exc),
            })

    headers = (
        "FILE",
        "TRACK",
        "SESSION",
        "FAMILY",
        "VARIANT",
        "CAR CLASS",
        "CAR NAME",
        "WEATHER",
        "SETUP",
    )

    printable = []
    for row in rows:
        setup = row.get("setup_sha256")
        printable.append((
            row.get("file") or "",
            row.get("track_name") or "",
            row.get("session_type") or "",
            row.get("vehicle_family") or "",
            row.get("vehicle_variant") or "",
            row.get("car_class_raw") or "",
            row.get("car_name_raw") or "",
            row.get("weather_conditions") or "",
            setup[:10] if setup else "-",
        ))

    if printable:
        widths = [
            max(len(headers[i]), *(len(str(row[i])) for row in printable))
            for i in range(len(headers))
        ]

        def fmt(values):
            return " | ".join(
                str(values[i]).ljust(widths[i])
                for i in range(len(values))
            )

        print(fmt(headers))
        print("-+-".join("-" * width for width in widths))
        for row in printable:
            print(fmt(row))
    else:
        print("No se encontraron archivos .duckdb.")

    variants = sorted({
        row.get("vehicle_variant")
        for row in rows
        if row.get("vehicle_variant")
    })

    print()
    print("VEHICLE VARIANTS")
    print("----------------")
    for variant in variants:
        count = sum(1 for row in rows if row.get("vehicle_variant") == variant)
        print(f"{variant}: {count}")

    output_path = Path(args.json_output).resolve()
    output_path.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "source_directory": str(root),
                "files": rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print(f"JSON guardado en: {output_path}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
