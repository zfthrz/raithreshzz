#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("ERROR: falta el paquete duckdb. Instalalo con: pip install duckdb")
    raise SystemExit(2)

POSITION_HINTS = ("pos", "position", "world", "local", "coord", "location", "loc", "gps", "lat", "lon", "long", "alt", "x", "y", "z")
AXIS_PATTERNS = {
    "x": [r"(^|[_\W])x($|[_\W])", r"pos.*x", r"position.*x", r"world.*x", r"local.*x", r"coord.*x", r"location.*x"],
    "y": [r"(^|[_\W])y($|[_\W])", r"pos.*y", r"position.*y", r"world.*y", r"local.*y", r"coord.*y", r"location.*y"],
    "z": [r"(^|[_\W])z($|[_\W])", r"pos.*z", r"position.*z", r"world.*z", r"local.*z", r"coord.*z", r"location.*z"],
}


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def is_numeric_type(type_name: str) -> bool:
    t = type_name.upper()
    return any(k in t for k in ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "REAL", "FLOAT", "DOUBLE", "DECIMAL"))


def classify_axis(column_name: str) -> str | None:
    n = column_name.lower()
    for axis, patterns in AXIS_PATTERNS.items():
        if any(re.search(p, n) for p in patterns):
            return axis
    return None


def positional_score(column_name: str) -> int:
    n = column_name.lower()
    score = 10 if n in {"x", "y", "z"} else 0
    if classify_axis(n):
        score += 5
    for hint in POSITION_HINTS:
        if hint in n:
            score += 1
    if any(k in n for k in ("world", "position", "pos", "coord", "location")):
        score += 5
    if any(k in n for k in ("max", "index", "axis", "gear", "rpm", "speed", "throttle", "brake", "steer", "force", "torque", "accel")):
        score -= 3
    return score


def list_user_tables(con) -> list[str]:
    rows = con.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """).fetchall()
    return [r[0] for r in rows]


def numeric_stats(con, table: str, column: str):
    qt, qc = qident(table), qident(column)
    return con.execute(f"""
        SELECT COUNT(*), COUNT({qc}), COUNT(DISTINCT {qc}),
               MIN({qc}), MAX({qc}), AVG(CAST({qc} AS DOUBLE)),
               STDDEV_POP(CAST({qc} AS DOUBLE))
        FROM {qt}
    """).fetchone()


def common_prefix_for_axis(name: str, axis: str) -> str:
    n = name.lower()
    for pattern in (rf"[_\-. ]?{axis}$", rf"{axis}[_\-. ]?$"):
        cleaned = re.sub(pattern, "", n)
        if cleaned != n:
            return cleaned.rstrip("_-. ")
    return re.sub(rf"\b{axis}\b", "", n).strip("_-. ")


def detect_coordinate_groups(candidates):
    result = []
    by_table = defaultdict(lambda: defaultdict(list))
    for item in candidates:
        if item["axis"]:
            prefix = common_prefix_for_axis(item["column"], item["axis"])
            by_table[item["table"]][prefix].append(item)

    for table, prefix_groups in by_table.items():
        for prefix, items in prefix_groups.items():
            axes = {i["axis"] for i in items}
            if {"x", "y", "z"}.issubset(axes):
                selected = {}
                for axis in ("x", "y", "z"):
                    opts = sorted((i for i in items if i["axis"] == axis), key=lambda x: x["score"], reverse=True)
                    selected[axis] = opts[0]
                result.append({"table": table, "prefix": prefix or "(sin prefijo)", "x": selected["x"]["column"], "y": selected["y"]["column"], "z": selected["z"]["column"], "confidence": "HIGH"})

    table_axis = defaultdict(lambda: defaultdict(list))
    for item in candidates:
        if item["axis"] and item["score"] >= 5:
            table_axis[item["table"]][item["axis"]].append(item)
    existing = {(g["table"], g["x"], g["y"], g["z"]) for g in result}
    for table, axes in table_axis.items():
        if all(len(axes[a]) == 1 for a in ("x", "y", "z")):
            x, y, z = axes["x"][0], axes["y"][0], axes["z"][0]
            key = (table, x["column"], y["column"], z["column"])
            if key not in existing:
                result.append({"table": table, "prefix": "(agrupación automática por ejes)", "x": x["column"], "y": y["column"], "z": z["column"], "confidence": "MEDIUM"})
    return result


def fmt(value):
    if value is None:
        return "NULL"
    try:
        f = float(value)
    except Exception:
        return str(value)
    if not math.isfinite(f):
        return str(value)
    if abs(f) >= 100000 or (0 < abs(f) < 0.001):
        return f"{f:.6g}"
    return f"{f:.6f}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Busca posibles coordenadas espaciales X/Y/Z en un DuckDB de telemetría LMU.")
    ap.add_argument("duckdb_file")
    ap.add_argument("--sample-rows", type=int, default=5)
    ap.add_argument("--all-columns", action="store_true")
    args = ap.parse_args()

    db = Path(args.duckdb_file).expanduser().resolve()
    if not db.exists():
        print(f"ERROR: no existe el archivo:\n  {db}")
        return 2

    print("=" * 72)
    print("LMU TRACK POSITION INSPECTOR")
    print("=" * 72)
    print(f"Archivo: {db}\n")

    con = duckdb.connect(str(db), read_only=True)
    try:
        tables = list_user_tables(con)
        print(f"Tablas encontradas: {len(tables)}")
        for t in tables:
            try:
                count = con.execute(f"SELECT COUNT(*) FROM {qident(t)}").fetchone()[0]
                print(f"  - {t}: {count} filas")
            except Exception:
                print(f"  - {t}")
        print()

        candidates = []
        for table in tables:
            cols = con.execute(f"DESCRIBE {qident(table)}").fetchall()
            if args.all_columns:
                print("-" * 72)
                print(f"TABLA: {table}")
                for row in cols:
                    print(f"  {row[0]:40s} {row[1]}")
            for row in cols:
                col_name, col_type = row[0], row[1]
                if not is_numeric_type(col_type):
                    continue
                score = positional_score(col_name)
                axis = classify_axis(col_name)
                if score <= 0 and axis is None:
                    continue
                candidates.append({"table": table, "column": col_name, "type": col_type, "axis": axis, "score": score})

        candidates.sort(key=lambda x: (x["score"], x["table"], x["column"]), reverse=True)
        print("=" * 72)
        print("COLUMNAS CANDIDATAS DE POSICIÓN")
        print("=" * 72)
        if not candidates:
            print("No encontré columnas numéricas con nombres compatibles con posición.")
            return 0
        for c in candidates:
            print(f"[score={c['score']:>2}] {c['table']}.{c['column']} type={c['type']} axis={c['axis'] or '-'}")
        print()

        groups = detect_coordinate_groups(candidates)
        print("=" * 72)
        print("POSIBLES TRÍOS DE COORDENADAS X/Y/Z")
        print("=" * 72)
        if not groups:
            print("No se detectó automáticamente un trío X/Y/Z convincente.")
        else:
            for i, g in enumerate(groups, 1):
                print(f"{i}. [{g['confidence']}] tabla={g['table']} grupo={g['prefix']}")
                print(f"   X = {g['x']}")
                print(f"   Y = {g['y']}")
                print(f"   Z = {g['z']}")
        print()

        print("=" * 72)
        print("ESTADÍSTICAS DE CANDIDATOS")
        print("=" * 72)
        for c in candidates[:30]:
            try:
                total, nonnull, distinct, min_v, max_v, avg_v, std_v = numeric_stats(con, c["table"], c["column"])
                print(f"{c['table']}.{c['column']}: rows={total} nonnull={nonnull} distinct={distinct} min={fmt(min_v)} max={fmt(max_v)} avg={fmt(avg_v)} std={fmt(std_v)}")
            except Exception as exc:
                print(f"{c['table']}.{c['column']}: ERROR stats: {exc}")
        print()

        if groups:
            print("=" * 72)
            print("MUESTRAS DE LOS GRUPOS X/Y/Z")
            print("=" * 72)
            for i, g in enumerate(groups, 1):
                cols = [g["x"], g["y"], g["z"]]
                print(f"\nGrupo {i}: {g['table']} ({', '.join(cols)})")
                select_list = ", ".join(qident(c) for c in cols)
                where = " OR ".join(f"{qident(c)} IS NOT NULL" for c in cols)
                rows = con.execute(f"SELECT {select_list} FROM {qident(g['table'])} WHERE {where} LIMIT {max(1, args.sample_rows)}").fetchall()
                print(f"  {'X':>16} {'Y':>16} {'Z':>16}")
                for row in rows:
                    print(f"  {fmt(row[0]):>16} {fmt(row[1]):>16} {fmt(row[2]):>16}")

        print("\n" + "=" * 72)
        print("DIAGNÓSTICO")
        print("=" * 72)
        if groups:
            print("Se detectó al menos un posible sistema X/Y/Z. Pasame esta salida completa; el siguiente paso será determinar qué dos ejes forman el plano del circuito y reconstruir la trayectoria 2D.")
        else:
            print("No apareció un X/Y/Z automático. Pasame igualmente esta salida completa; revisaremos nombres no convencionales o reconstruiremos la geometría desde distancia + steering + speed + brake.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
