import duckdb
import pandas as pd
from pathlib import Path


class Telemetry:
    """
    Capa de acceso y sincronización para telemetría de
    Le Mans Ultimate.

    GPS Time es el eje temporal maestro.

    Las tablas originales del DuckDB NO se modifican.

    Los canales pueden tener distintas frecuencias:

        100 Hz -> GPS Time, Engine RPM, Steering Pos, etc.
         50 Hz -> Throttle Pos, Brake Pos, etc.
         10 Hz -> Lap Dist, etc.

    La sincronización solamente se realiza en memoria.
    """

    # ==========================================================
    # INICIALIZACIÓN
    # ==========================================================

    def __init__(self, db_path=None):

        if db_path is None:
            db_path = (
                Path(__file__).resolve().parent.parent
                / "monza.duckdb"
            )

        self.db_path = Path(db_path)

        if not self.db_path.exists():
            raise FileNotFoundError(
                f"No existe la base de datos: {self.db_path}"
            )

        self.conn = duckdb.connect(
            str(self.db_path),
            read_only=True
        )

        self._tables = None
        self._channels = None
        self._timeline = None

    # ==========================================================
    # CONEXIÓN
    # ==========================================================

    def close(self):

        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback
    ):
        self.close()

    # ==========================================================
    # TABLAS
    # ==========================================================

    def list_tables(self):

        if self._tables is None:

            rows = self.conn.execute(
                "SHOW TABLES"
            ).fetchall()

            self._tables = [
                row[0]
                for row in rows
            ]

        return self._tables.copy()

    def table_exists(self, table_name):

        return table_name in self.list_tables()

    # ==========================================================
    # SCHEMA
    # ==========================================================

    def get_table_schema(self, table_name):

        if not self.table_exists(table_name):
            raise ValueError(
                f"La tabla '{table_name}' no existe."
            )

        rows = self.conn.execute(
            f'DESCRIBE "{table_name}"'
        ).fetchall()

        columns = []

        for row in rows:

            columns.append({
                "column_name": row[0],
                "column_type": row[1],
                "null": row[2],
                "key": row[3],
                "default": row[4],
                "extra": row[5],
            })

        return columns

    # ==========================================================
    # METADATA
    # ==========================================================

    def get_channels(self):

        if self._channels is not None:
            return self._channels.copy()

        if not self.table_exists("channelsList"):
            raise RuntimeError(
                "La base no contiene la tabla channelsList."
            )

        query = """
            SELECT
                channelName,
                frequency,
                unit
            FROM channelsList
            ORDER BY channelName
        """

        df = self.conn.execute(query).fetchdf()

        self._channels = df

        return df.copy()

    def get_channel_info(self, channel_name):
        """
        Devuelve:

            name
            frequency
            unit
            samples
            structure
        """

        channels = self.get_channels()

        result = channels[
            channels["channelName"] == channel_name
        ]

        if result.empty:
            return None

        if not self.table_exists(channel_name):
            return None

        row = result.iloc[0]

        samples = self.conn.execute(
            f'SELECT COUNT(*) FROM "{channel_name}"'
        ).fetchone()[0]

        structure = self.get_table_schema(
            channel_name
        )

        return {
            "name": row["channelName"],
            "frequency": row["frequency"],
            "unit": row["unit"],
            "samples": samples,
            "structure": structure,
        }

    # ==========================================================
    # LECTURA DIRECTA
    # ==========================================================

    def get_channel(self, channel_name):
        """
        Lee la tabla original del canal.

        No modifica los datos.
        """

        if not self.table_exists(channel_name):
            raise ValueError(
                f"El canal '{channel_name}' no existe."
            )

        return self.conn.execute(
            f'''
            SELECT *
            FROM "{channel_name}"
            '''
        ).fetchdf()

    # ==========================================================
    # GPS TIME
    # ==========================================================

    def get_gps_time(self):

        data = self.get_channel(
            "GPS Time"
        )

        if "value" not in data.columns:
            raise RuntimeError(
                "La tabla 'GPS Time' no contiene "
                "la columna 'value'."
            )

        gps = pd.to_numeric(
            data["value"],
            errors="coerce"
        )

        gps = gps.dropna().reset_index(
            drop=True
        )

        if gps.empty:
            raise RuntimeError(
                "GPS Time no contiene valores válidos."
            )

        return gps

    # ==========================================================
    # TIMELINE MAESTRO
    # ==========================================================

    def build_timeline(self):

        if self._timeline is not None:
            return self._timeline.copy()

        gps = self.get_gps_time()

        self._timeline = pd.DataFrame({
            "gps_idx": range(len(gps)),
            "gps_time": gps.values,
        })

        return self._timeline.copy()

    # ==========================================================
    # COMPATIBILIDAD
    # ==========================================================

    def get_timeline(
        self,
        channels=None
    ):
        """
        Función pública utilizada por los tests.

        Si channels=None devuelve solamente:

            gps_idx
            gps_time

        Si se proporciona una lista de canales,
        devuelve esos canales sincronizados sobre GPS Time.
        """

        if channels is None:
            return self.build_timeline()

        return self.build_dataframe(
            channels=channels
        )

    # ==========================================================
    # ALINEACIÓN
    # ==========================================================

    def align_channel(
        self,
        channel_name,
        method="auto"
    ):
        """
        Alinea un canal sobre GPS Time.

        El resultado siempre tiene la misma cantidad
        de filas que GPS Time.

        IMPORTANTE:

        Los canales sin timestamp propio se reconstruyen
        temporalmente usando exclusivamente:

            GPS inicial
            frecuencia declarada en channelsList

        Esto NO modifica el DuckDB.
        """

        timeline = self.build_timeline()

        channel = self.get_channel(
            channel_name
        )

        if channel.empty:

            return pd.Series(
                index=timeline.index,
                dtype=float,
                name=channel_name
            )

        if "value" not in channel.columns:
            raise ValueError(
                f"El canal '{channel_name}' "
                f"no tiene columna 'value'."
            )

        values = channel["value"]

        info = self.get_channel_info(
            channel_name
        )

        if info is None:
            raise ValueError(
                f"No existe metadata para "
                f"'{channel_name}'."
            )

        frequency = info["frequency"]

        # ------------------------------------------------------
        # Frecuencia
        # ------------------------------------------------------

        if isinstance(frequency, dict):
            frequency = frequency.get(
                "frequency"
            )

        try:
            frequency = float(frequency)

        except (
            TypeError,
            ValueError
        ):
            raise ValueError(
                f"Frecuencia inválida para "
                f"'{channel_name}': {frequency}"
            )

        if frequency <= 0:
            raise ValueError(
                f"Frecuencia inválida para "
                f"'{channel_name}': {frequency}"
            )

        gps = timeline["gps_time"]

        # ======================================================
        # TIMESTAMP PROPIO
        # ======================================================

        if "ts" in channel.columns:

            source_time = pd.to_numeric(
                channel["ts"],
                errors="coerce"
            )

        # ======================================================
        # SIN TIMESTAMP
        # ======================================================

        else:

            start_time = float(
                gps.iloc[0]
            )

            interval = 1.0 / frequency

            source_time = (
                start_time
                + pd.Series(
                    range(len(values)),
                    dtype=float
                ) * interval
            )

        # ======================================================
        # SOURCE
        # ======================================================

        source = pd.DataFrame({
            "time": source_time.values,
            "value": values.values,
        })

        source = source.dropna(
            subset=["time"]
        )

        source = source.sort_values(
            "time"
        )

        source = source.drop_duplicates(
            subset="time",
            keep="last"
        )

        # ======================================================
        # TIPO DE CANAL
        # ======================================================

        dtype = values.dtype

        is_numeric = (
            pd.api.types.is_numeric_dtype(
                dtype
            )
        )

        is_bool = (
            pd.api.types.is_bool_dtype(
                dtype
            )
        )

        discrete_names = {
            "Gear",
            "Lap",
            "Current Sector",
            "Finish Status",
            "Sector1 Flag",
            "Sector2 Flag",
            "Sector3 Flag",
            "TCLevel",
            "TCCut",
            "TCSlipAngle",
            "FuelMixtureMap",
            "TyresCompound",
            "SurfaceTypes",
            "WheelsDetached",
            "Yellow Flag State",
            "In Pits",
        }

        is_discrete = (
            channel_name in discrete_names
            or is_bool
            or not is_numeric
        )

        # ======================================================
        # NEAREST
        # ======================================================

        if (
            method == "nearest"
            or is_discrete
        ):

            result = pd.merge_asof(
                timeline[
                    ["gps_time"]
                ].sort_values("gps_time"),

                source[
                    ["time", "value"]
                ].sort_values("time"),

                left_on="gps_time",
                right_on="time",

                direction="nearest",
            )

        # ======================================================
        # CONTINUO
        # ======================================================

        else:

            result = pd.merge_asof(
                timeline[
                    ["gps_time"]
                ].sort_values("gps_time"),

                source[
                    ["time", "value"]
                ].sort_values("time"),

                left_on="gps_time",
                right_on="time",

                direction="nearest",
            )

            result = result.set_index(
                "gps_time"
            )

            result["value"] = (
                pd.to_numeric(
                    result["value"],
                    errors="coerce"
                )
                .interpolate(
                    method="index",
                    limit_direction="both"
                )
            )

            result = result.reset_index()

        # ======================================================
        # RESULTADO
        # ======================================================

        result = result["value"]

        result.index = timeline.index

        result.name = channel_name

        return result

    # ==========================================================
    # DATAFRAME SINCRONIZADO
    # ==========================================================

    def build_dataframe(
        self,
        channels=None
    ):
        """
        Construye un DataFrame sincronizado sobre GPS Time.
        """

        if channels is None:

            channels = [
                "Engine RPM",
                "Throttle Pos",
                "Brake Pos",
                "Steering Pos",
                "Ground Speed",
                "Lap Dist",
            ]

        timeline = self.build_timeline()

        result = timeline.copy()

        for channel in channels:

            if not self.table_exists(channel):

                print(
                    f"[WARN] Canal inexistente: "
                    f"{channel}"
                )

                continue

            try:

                result[channel] = (
                    self.align_channel(
                        channel
                    )
                )

            except Exception as exc:

                print(
                    f"[WARN] No se pudo alinear "
                    f"{channel}: {exc}"
                )

        return result

    # ==========================================================
    # RESUMEN
    # ==========================================================

    def summary(self):

        print("=== TELEMETRY ===")

        print(
            f"Base: {self.db_path}"
        )

        tables = self.list_tables()

        print(
            f"Tablas: {len(tables)}"
        )

        print()

        print("=== TIMELINE ===")

        timeline = self.build_timeline()

        if timeline.empty:

            print(
                "GPS Time está vacío."
            )

            return

        start = float(
            timeline["gps_time"].iloc[0]
        )

        end = float(
            timeline["gps_time"].iloc[-1]
        )

        print(
            f"Muestras: {len(timeline)}"
        )

        print(
            f"Inicio: {start}"
        )

        print(
            f"Fin: {end}"
        )

        print(
            f"Duración: "
            f"{end - start:.3f} s"
        )

    # ==========================================================
    # INFORMACIÓN DE CANALES
    # ==========================================================

    def channel_summary(self):

        channels = self.get_channels()

        print(
            "=== INFORMACIÓN DE CANALES ==="
        )

        for _, row in channels.iterrows():

            name = row["channelName"]

            info = self.get_channel_info(
                name
            )

            if info is None:
                continue

            print()
            print(
                f"## {name}"
            )

            print(
                f"Frecuencia: "
                f"{info['frequency']}"
            )

            print(
                f"Muestras: "
                f"{info['samples']}"
            )

            print(
                f"Estructura: "
                f"{info['structure']}"
            )

