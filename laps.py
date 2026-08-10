import pandas as pd
import numpy as np


class LapAnalyzer:
    """
    Analizador de vueltas para telemetría de Le Mans Ultimate.

    GPS Time es el timeline maestro.

    La tabla "Lap" contiene eventos de cambio de vuelta.
    No debe tratarse como un canal de frecuencia constante.
    """

    def __init__(self, telemetry):
        self.telemetry = telemetry

    # ============================================================
    # GPS TIME
    # ============================================================

    def get_gps_time(self):
        """
        Obtiene el timeline completo de GPS Time.

        Devuelve:

            gps_idx
            gps_time

        gps_idx conserva el índice original de cada muestra.
        """

        data = self.telemetry.get_channel("GPS Time")

        if data.empty:
            raise ValueError(
                "El canal 'GPS Time' no contiene datos."
            )

        if "value" not in data.columns:
            raise ValueError(
                "La tabla 'GPS Time' no contiene la columna 'value'."
            )

        gps = pd.to_numeric(
            data["value"],
            errors="coerce"
        )

        gps = gps.dropna().reset_index(drop=True)

        if gps.empty:
            raise ValueError(
                "GPS Time no contiene valores numéricos válidos."
            )

        return pd.DataFrame({
            "gps_idx": np.arange(len(gps), dtype=int),
            "gps_time": gps.to_numpy(),
        })

    # ============================================================
    # EVENTOS DE LAP
    # ============================================================

    def get_lap_events(self):
        """
        Obtiene los eventos reales de la tabla "Lap".

        La tabla Lap tiene timestamps propios, por lo que
        NO se utiliza align_channel() para este canal.
        """

        if not self.telemetry.table_exists("Lap"):
            raise ValueError(
                "La base no contiene la tabla 'Lap'."
            )

        lap_table = self.telemetry.get_channel("Lap")

        if lap_table.empty:
            raise ValueError(
                "El canal 'Lap' no contiene eventos."
            )

        if "ts" not in lap_table.columns:
            raise ValueError(
                "La tabla 'Lap' no contiene la columna 'ts'."
            )

        if "value" not in lap_table.columns:
            raise ValueError(
                "La tabla 'Lap' no contiene la columna 'value'."
            )

        df = lap_table[
            ["ts", "value"]
        ].copy()

        df["ts"] = pd.to_numeric(
            df["ts"],
            errors="coerce"
        )

        df["lap"] = pd.to_numeric(
            df["value"],
            errors="coerce"
        )

        df = df.dropna(
            subset=[
                "ts",
                "lap"
            ]
        )

        if df.empty:
            raise ValueError(
                "La tabla 'Lap' no contiene eventos válidos."
            )

        df["lap"] = df["lap"].astype(int)

        df = df.sort_values(
            "ts"
        ).reset_index(
            drop=True
        )

        df = df.drop_duplicates(
            subset=["ts"],
            keep="last"
        ).reset_index(
            drop=True
        )

        return df[
            ["ts", "lap"]
        ]

    # ============================================================
    # DETECTAR VUELTAS
    # ============================================================

    def detect_laps(self):
        """
        Construye los intervalos temporales de las vueltas.

        El inicio de cada vuelta viene de la tabla Lap.

        El final es:

            - timestamp de la siguiente vuelta
            - o último GPS Time para la última vuelta
        """

        lap_events = self.get_lap_events()
        gps = self.get_gps_time()

        if gps.empty:
            raise ValueError(
                "No existe timeline GPS."
            )

        gps_values = gps[
            "gps_time"
        ].to_numpy()

        gps_start = float(
            gps_values[0]
        )

        gps_end = float(
            gps_values[-1]
        )

        laps = []

        for i in range(
            len(lap_events)
        ):

            lap_number = int(
                lap_events.iloc[i]["lap"]
            )

            start_time = float(
                lap_events.iloc[i]["ts"]
            )

            # ----------------------------------------------------
            # FINAL DE LA VUELTA
            # ----------------------------------------------------

            if i + 1 < len(lap_events):

                end_time = float(
                    lap_events.iloc[i + 1]["ts"]
                )

            else:

                end_time = gps_end

            # ----------------------------------------------------
            # VALIDACIONES
            # ----------------------------------------------------

            if end_time <= start_time:
                continue

            if end_time < gps_start:
                continue

            if start_time > gps_end:
                continue

            # ----------------------------------------------------
            # LIMITAR AL TIMELINE REAL
            # ----------------------------------------------------

            start_time = max(
                start_time,
                gps_start
            )

            end_time = min(
                end_time,
                gps_end
            )

            if end_time <= start_time:
                continue

            # ----------------------------------------------------
            # ÍNDICES GPS
            # ----------------------------------------------------

            start_idx = int(
                np.searchsorted(
                    gps_values,
                    start_time,
                    side="left"
                )
            )

            end_idx = int(
                np.searchsorted(
                    gps_values,
                    end_time,
                    side="left"
                )
            )

            # ----------------------------------------------------
            # LIMITAR ÍNDICES
            # ----------------------------------------------------

            start_idx = max(
                0,
                min(
                    start_idx,
                    len(gps_values) - 1
                )
            )

            end_idx = max(
                start_idx + 1,
                min(
                    end_idx,
                    len(gps_values)
                )
            )

            laps.append({
                "lap": lap_number,
                "start_idx": start_idx,
                "end_idx": end_idx,
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
            })

        return pd.DataFrame(
            laps,
            columns=[
                "lap",
                "start_idx",
                "end_idx",
                "start_time",
                "end_time",
                "duration",
            ]
        )

    # ============================================================
    # DATAFRAME COMPLETO
    # ============================================================

    def get_full_dataframe(self):
        """
        Construye una única vez el DataFrame sincronizado completo.

        Primero se sincronizan todos los canales sobre GPS Time.
        Después get_lap_data() corta por tiempo.

        Esto evita reutilizar las primeras muestras del timeline
        para todas las vueltas.
        """

        return self.telemetry.build_dataframe([
            "Engine RPM",
            "Throttle Pos",
            "Brake Pos",
            "Steering Pos",
            "Ground Speed",
            "Lap Dist",
        ])

    # ============================================================
    # DATOS DE UNA VUELTA
    # ============================================================

    def get_lap_data(self, lap_number):
        """
        Obtiene las muestras sincronizadas correspondientes
        exclusivamente a una vuelta.
        """

        laps = self.detect_laps()

        if laps.empty:
            raise ValueError(
                "No se detectaron vueltas."
            )

        matching = laps[
            laps["lap"] == lap_number
        ]

        if matching.empty:
            raise ValueError(
                f"No existe la vuelta {lap_number}. "
                f"Disponibles: {laps['lap'].tolist()}"
            )

        lap_info = matching.iloc[0]

        start_time = float(
            lap_info["start_time"]
        )

        end_time = float(
            lap_info["end_time"]
        )

        # --------------------------------------------------------
        # DATAFRAME COMPLETO SINCRONIZADO
        # --------------------------------------------------------

        dataframe = self.get_full_dataframe()

        # --------------------------------------------------------
        # CORTE TEMPORAL
        #
        # Inicio incluido.
        # Final excluido.
        # --------------------------------------------------------

        mask = (
            (dataframe["gps_time"] >= start_time)
            &
            (dataframe["gps_time"] < end_time)
        )

        timeline = dataframe.loc[
            mask
        ].copy()

        if timeline.empty:
            raise ValueError(
                f"No hay muestras de telemetría entre "
                f"{start_time} y {end_time}."
            )

        # --------------------------------------------------------
        # IMPORTANTE:
        #
        # NO modificar gps_idx.
        #
        # Debe seguir representando el índice original dentro
        # del timeline completo.
        # --------------------------------------------------------

        timeline = timeline.reset_index(
            drop=True
        )

        return timeline

    # ============================================================
    # RESUMEN DE VUELTAS
    # ============================================================

    def summary(self):
        """
        Muestra y devuelve el resumen de vueltas.
        """

        laps = self.detect_laps()

        print()
        print(
            "============================================================"
        )
        print(
            "VUELTAS DETECTADAS"
        )
        print(
            "============================================================"
        )

        if laps.empty:
            print(
                "No se detectaron vueltas."
            )
            return laps

        print(
            laps.to_string(
                index=False
            )
        )

        return laps

    # ============================================================
    # RESUMEN DE UNA VUELTA
    # ============================================================

    def lap_summary(self, lap_number):
        """
        Calcula métricas básicas de una vuelta.
        """

        data = self.get_lap_data(
            lap_number
        )

        laps = self.detect_laps()

        matching = laps[
            laps["lap"] == lap_number
        ]

        if matching.empty:
            raise ValueError(
                f"No existe la vuelta {lap_number}."
            )

        lap_info = matching.iloc[0]

        result = {
            "lap": int(lap_number),

            "start_time": float(
                lap_info["start_time"]
            ),

            "end_time": float(
                lap_info["end_time"]
            ),

            "duration": float(
                lap_info["duration"]
            ),

            "samples": int(
                len(data)
            ),
        }

        # ========================================================
        # ENGINE RPM
        # ========================================================

        if "Engine RPM" in data.columns:

            rpm = pd.to_numeric(
                data["Engine RPM"],
                errors="coerce"
            ).dropna()

            if not rpm.empty:

                result["max_rpm"] = float(
                    rpm.max()
                )

        # ========================================================
        # GROUND SPEED
        # ========================================================

        if "Ground Speed" in data.columns:

            speed = pd.to_numeric(
                data["Ground Speed"],
                errors="coerce"
            ).dropna()

            if not speed.empty:

                result["max_speed"] = float(
                    speed.max()
                )

        # ========================================================
        # THROTTLE
        # ========================================================

        if "Throttle Pos" in data.columns:

            throttle = pd.to_numeric(
                data["Throttle Pos"],
                errors="coerce"
            ).dropna()

            if not throttle.empty:

                result["avg_throttle"] = float(
                    throttle.mean()
                )

                result["max_throttle"] = float(
                    throttle.max()
                )

        # ========================================================
        # BRAKE
        # ========================================================

        if "Brake Pos" in data.columns:

            brake = pd.to_numeric(
                data["Brake Pos"],
                errors="coerce"
            ).dropna()

            if not brake.empty:

                result["max_brake"] = float(
                    brake.max()
                )

        # ========================================================
        # STEERING
        # ========================================================

        if "Steering Pos" in data.columns:

            steering = pd.to_numeric(
                data["Steering Pos"],
                errors="coerce"
            ).dropna()

            if not steering.empty:

                result["max_steering"] = float(
                    steering.abs().max()
                )

        # ========================================================
        # LAP DISTANCE
        # ========================================================

        if "Lap Dist" in data.columns:

            distance = pd.to_numeric(
                data["Lap Dist"],
                errors="coerce"
            ).dropna()

            if not distance.empty:

                diff = distance.diff()

                positive_diff = diff[
                    diff > 0
                ]

                if not positive_diff.empty:

                    result["lap_distance"] = float(
                        positive_diff.sum()
                    )

                else:

                    result["lap_distance"] = 0.0

        return result

    # ============================================================
    # RESUMEN DE TODAS LAS VUELTAS
    # ============================================================

    def all_lap_summaries(self):
        """
        Calcula el resumen de todas las vueltas.

        Devuelve una lista de diccionarios.
        """

        laps = self.detect_laps()

        summaries = []

        for lap_number in laps["lap"].tolist():

            try:

                summaries.append(
                    self.lap_summary(
                        int(lap_number)
                    )
                )

            except Exception as exc:

                print(
                    f"[WARN] No se pudo analizar "
                    f"la vuelta {lap_number}: {exc}"
                )

        return summaries