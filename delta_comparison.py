import numpy as np
import pandas as pd


class DeltaComparison:
    """
    Compara dos vueltas del mismo vehículo.

    La comparación se realiza sobre una grilla espacial común.

    lap_a = vuelta de referencia
    lap_b = vuelta comparada contra lap_a

    Signos:

        time_delta > 0
            B está perdiendo tiempo respecto de A.

        time_delta < 0
            B está ganando tiempo respecto de A.

    IMPORTANTE:

    El delta temporal espacial se construye usando Ground Speed
    para determinar la distribución espacial del tiempo, pero cada
    vuelta se normaliza contra su duración REAL.

    De esta forma:

        time_profile_a(final) = duration_a
        time_profile_b(final) = duration_b

    y por lo tanto:

        time_delta(final)
            =
        duration_b - duration_a

    Esto permite utilizar el delta espacial para localizar dónde
    se gana o pierde tiempo sin perder la contabilidad temporal real.
    """

    def __init__(self, lap_analyzer):
        self.laps = lap_analyzer

    # ========================================================
    # PREPARAR VUELTA
    # ========================================================

    def _prepare_lap(self, lap_number):
        """
        Obtiene una vuelta y construye una distancia continua.

        También conserva la duración real de la vuelta cuando
        está disponible mediante lap_summary().
        """

        data = self.laps.get_lap_data(
            lap_number
        )

        if data.empty:
            raise ValueError(
                f"La vuelta {lap_number} no contiene datos."
            )

        if "Lap Dist" not in data.columns:
            raise ValueError(
                "La vuelta no contiene el canal 'Lap Dist'."
            )

        result = data.copy()

        distance = pd.to_numeric(
            result["Lap Dist"],
            errors="coerce",
        ).to_numpy(
            dtype=float
        )

        if len(distance) == 0:
            raise ValueError(
                f"La vuelta {lap_number} no contiene "
                "muestras de Lap Dist."
            )

        # ----------------------------------------------------
        # DISTANCIA CONTINUA
        # ----------------------------------------------------

        continuous = np.full(
            len(distance),
            np.nan,
            dtype=float
        )

        offset = 0.0

        for i in range(
            len(distance)
        ):

            current = distance[i]

            if not np.isfinite(current):
                continue

            if i > 0:

                previous = distance[
                    i - 1
                ]

                if np.isfinite(previous):

                    jump = (
                        current
                        -
                        previous
                    )

                    # Detectar reset de Lap Dist.
                    #
                    # Ejemplo:
                    #
                    # 6973 -> 0

                    if jump < -1000.0:

                        offset += previous

            continuous[i] = (
                current
                +
                offset
            )

        valid = np.flatnonzero(
            np.isfinite(continuous)
        )

        if len(valid) == 0:
            raise ValueError(
                f"No fue posible construir la distancia "
                f"de la vuelta {lap_number}."
            )

        first = valid[0]

        continuous -= continuous[first]

        result[
            "lap_distance"
        ] = continuous

        # ----------------------------------------------------
        # DURACIÓN REAL
        # ----------------------------------------------------

        real_duration = None

        try:

            summary = self.laps.lap_summary(
                lap_number
            )

            if isinstance(
                summary,
                dict
            ):

                real_duration = (
                    summary.get(
                        "duration"
                    )
                )

            else:

                try:

                    real_duration = (
                        summary[
                            "duration"
                        ]
                    )

                except (
                    KeyError,
                    TypeError,
                    IndexError,
                ):

                    real_duration = None

        except Exception:
            real_duration = None

        try:

            real_duration = float(
                real_duration
            )

        except (
            TypeError,
            ValueError,
        ):

            real_duration = None

        if (
            real_duration is None
            or
            not np.isfinite(
                real_duration
            )
            or
            real_duration <= 0
        ):

            raise ValueError(
                f"No fue posible obtener la duración real "
                f"de la vuelta {lap_number}."
            )

        result[
            "lap_duration_real"
        ] = real_duration

        # ----------------------------------------------------
        # LIMPIEZA
        # ----------------------------------------------------

        result = result.dropna(
            subset=[
                "lap_distance"
            ]
        )

        result = result.sort_values(
            "lap_distance"
        )

        result = result.drop_duplicates(
            subset=[
                "lap_distance"
            ],
            keep="first"
        )

        result = result.reset_index(
            drop=True
        )

        return result

    # ========================================================
    # INTERPOLAR VUELTA
    # ========================================================

    def _interpolate_lap(
        self,
        data,
        distance_grid,
    ):
        """
        Interpola una vuelta sobre una grilla espacial común.
        """

        result = pd.DataFrame({
            "distance": distance_grid
        })

        channels = [
            "Engine RPM",
            "Throttle Pos",
            "Brake Pos",
            "Steering Pos",
            "Ground Speed",
        ]

        source_distance = (
            data[
                "lap_distance"
            ]
            .to_numpy(
                dtype=float
            )
        )

        for channel in channels:

            if channel not in data.columns:
                continue

            values = pd.to_numeric(
                data[channel],
                errors="coerce",
            ).to_numpy(
                dtype=float
            )

            valid = (
                np.isfinite(
                    source_distance
                )
                &
                np.isfinite(
                    values
                )
            )

            if valid.sum() < 2:
                continue

            result[channel] = np.interp(
                distance_grid,
                source_distance[
                    valid
                ],
                values[
                    valid
                ],
            )

        return result

    # ========================================================
    # PERFIL TEMPORAL ESPACIAL
    # ========================================================

    def _build_time_profile(
        self,
        interpolation,
        real_duration,
    ):
        """
        Construye un perfil temporal acumulado sobre la grilla.

        Ground Speed determina la distribución relativa del tiempo.

        Después el perfil se normaliza contra la duración REAL
        de la vuelta.

        Esto evita depender de:

            dt = dx / v

        como fuente absoluta del tiempo.

        La única función de Ground Speed aquí es determinar
        proporcionalmente cuánto tiempo consume cada tramo.

        Resultado:

            time_profile[0] = 0

            time_profile[-1] = real_duration
        """

        distances = (
            interpolation[
                "distance"
            ]
            .to_numpy(
                dtype=float
            )
        )

        n = len(distances)

        if n < 2:

            raise ValueError(
                "La grilla temporal contiene muy pocas muestras."
            )

        if (
            "Ground Speed"
            not in interpolation.columns
        ):

            raise ValueError(
                "La comparación necesita "
                "'Ground Speed' para construir "
                "el perfil temporal."
            )

        speed = pd.to_numeric(
            interpolation[
                "Ground Speed"
            ],
            errors="coerce",
        ).to_numpy(
            dtype=float
        )

        # ----------------------------------------------------
        # LIMPIAR VELOCIDAD
        # ----------------------------------------------------

        valid_speed = np.isfinite(
            speed
        )

        if valid_speed.sum() < 2:

            raise ValueError(
                "No existen suficientes muestras válidas "
                "de Ground Speed."
            )

        # Interpolar huecos internos.
        #
        # np.interp también permite completar los extremos
        # utilizando el valor válido más cercano.

        valid_indices = np.flatnonzero(
            valid_speed
        )

        speed = np.interp(
            np.arange(n),
            valid_indices,
            speed[
                valid_indices
            ],
        )

        # ----------------------------------------------------
        # EVITAR VELOCIDADES NO FÍSICAS
        # ----------------------------------------------------

        speed = np.maximum(
            speed,
            0.1
        )

        # ----------------------------------------------------
        # TIEMPO RELATIVO POR SEGMENTO
        # ----------------------------------------------------

        dx = np.diff(
            distances
        )

        if np.any(
            dx < 0
        ):

            raise ValueError(
                "La distancia no es monótonamente creciente."
            )

        # ----------------------------------------------------
        # dt RELATIVO
        # ----------------------------------------------------
        #
        # La unidad absoluta de Ground Speed no importa aquí.
        #
        # Si está en km/h:
        #
        #     dx / speed
        #
        # no representa segundos.
        #
        # Pero sí representa correctamente una medida relativa
        # del tiempo consumido por cada segmento.
        #
        # Después normalizamos todo el perfil contra la duración
        # real de la vuelta.
        #
        # Usamos velocidad media armónica para evitar que un
        # cambio fuerte de velocidad quede dominado por un solo
        # extremo.

        speed_start = speed[
            :-1
        ]

        speed_end = speed[
            1:
        ]

        harmonic_speed = np.zeros_like(
            speed_start,
            dtype=float
        )

        denominator = (
            speed_start
            +
            speed_end
        )

        valid_harmonic = (
            np.isfinite(
                denominator
            )
            &
            (
                denominator
                >
                0.0
            )
        )

        harmonic_speed[
            valid_harmonic
        ] = (
            2.0
            *
            speed_start[
                valid_harmonic
            ]
            *
            speed_end[
                valid_harmonic
            ]
            /
            denominator[
                valid_harmonic
            ]
        )

        harmonic_speed[
            ~valid_harmonic
        ] = 0.1

        relative_dt = (
            dx
            /
            np.maximum(
                harmonic_speed,
                0.1
            )
        )

        # ----------------------------------------------------
        # PERFIL ACUMULADO
        # ----------------------------------------------------

        cumulative = np.zeros(
            n,
            dtype=float
        )

        if len(relative_dt) > 0:

            cumulative[1:] = np.cumsum(
                relative_dt
            )

        relative_total = float(
            cumulative[-1]
        )

        if (
            not np.isfinite(
                relative_total
            )
            or
            relative_total <= 0
        ):

            raise ValueError(
                "No fue posible construir "
                "el perfil temporal relativo."
            )

        # ----------------------------------------------------
        # NORMALIZACIÓN CONTRA TIEMPO REAL
        # ----------------------------------------------------

        time_profile = (
            cumulative
            /
            relative_total
            *
            float(
                real_duration
            )
        )

        # ----------------------------------------------------
        # FORZAR EXTREMOS
        # ----------------------------------------------------

        time_profile[0] = 0.0

        time_profile[-1] = float(
            real_duration
        )

        return time_profile

    # ========================================================
    # COMPARAR VUELTAS
    # ========================================================

    def compare(
        self,
        lap_a,
        lap_b,
        resolution=1.0,
    ):
        """
        Compara dos vueltas espacialmente.

        resolution:
            Distancia entre muestras, en metros.

        Devuelve:

            distance
            speed_a
            speed_b
            speed_delta

            rpm_a
            rpm_b
            rpm_delta

            throttle_a
            throttle_b
            throttle_delta

            brake_a
            brake_b
            brake_delta

            steering_a
            steering_b
            steering_delta

            time_a
            time_b
            time_delta

        time_delta representa la diferencia temporal acumulada
        entre ambas vueltas en cada posición de la pista.
        """

        if resolution <= 0:

            raise ValueError(
                "resolution debe ser mayor que cero."
            )

        # ----------------------------------------------------
        # PREPARAR
        # ----------------------------------------------------

        data_a = self._prepare_lap(
            lap_a
        )

        data_b = self._prepare_lap(
            lap_b
        )

        # ----------------------------------------------------
        # DISTANCIA COMÚN
        # ----------------------------------------------------

        max_distance_a = float(
            data_a[
                "lap_distance"
            ].max()
        )

        max_distance_b = float(
            data_b[
                "lap_distance"
            ].max()
        )

        max_distance = min(
            max_distance_a,
            max_distance_b,
        )

        if max_distance <= 0:

            raise ValueError(
                "No existe distancia suficiente "
                "para comparar las vueltas."
            )

        # ----------------------------------------------------
        # GRILLA ESPACIAL
        # ----------------------------------------------------

        distance_grid = np.arange(
            0.0,
            max_distance,
            resolution,
        )

        # Asegurar que la última posición común esté incluida.

        if (
            len(distance_grid) == 0
            or
            distance_grid[-1]
            <
            max_distance
        ):

            distance_grid = np.append(
                distance_grid,
                max_distance,
            )

        if len(distance_grid) < 2:

            raise ValueError(
                "La grilla espacial tiene muy pocas muestras."
            )

        # ----------------------------------------------------
        # INTERPOLACIÓN
        # ----------------------------------------------------

        interp_a = self._interpolate_lap(
            data_a,
            distance_grid,
        )

        interp_b = self._interpolate_lap(
            data_b,
            distance_grid,
        )

        result = pd.DataFrame({
            "distance":
                distance_grid
        })

        # ====================================================
        # VELOCIDAD
        # ====================================================

        if (
            "Ground Speed" in interp_a.columns
            and
            "Ground Speed" in interp_b.columns
        ):

            speed_a = (
                interp_a[
                    "Ground Speed"
                ]
                .to_numpy(
                    dtype=float
                )
            )

            speed_b = (
                interp_b[
                    "Ground Speed"
                ]
                .to_numpy(
                    dtype=float
                )
            )

            result[
                "speed_a"
            ] = speed_a

            result[
                "speed_b"
            ] = speed_b

            result[
                "speed_delta"
            ] = (
                speed_b
                -
                speed_a
            )

        # ====================================================
        # RPM
        # ====================================================

        if (
            "Engine RPM" in interp_a.columns
            and
            "Engine RPM" in interp_b.columns
        ):

            rpm_a = (
                interp_a[
                    "Engine RPM"
                ]
                .to_numpy(
                    dtype=float
                )
            )

            rpm_b = (
                interp_b[
                    "Engine RPM"
                ]
                .to_numpy(
                    dtype=float
                )
            )

            result[
                "rpm_a"
            ] = rpm_a

            result[
                "rpm_b"
            ] = rpm_b

            result[
                "rpm_delta"
            ] = (
                rpm_b
                -
                rpm_a
            )

        # ====================================================
        # THROTTLE
        # ====================================================

        if (
            "Throttle Pos" in interp_a.columns
            and
            "Throttle Pos" in interp_b.columns
        ):

            throttle_a = (
                interp_a[
                    "Throttle Pos"
                ]
                .to_numpy(
                    dtype=float
                )
            )

            throttle_b = (
                interp_b[
                    "Throttle Pos"
                ]
                .to_numpy(
                    dtype=float
                )
            )

            result[
                "throttle_a"
            ] = throttle_a

            result[
                "throttle_b"
            ] = throttle_b

            result[
                "throttle_delta"
            ] = (
                throttle_b
                -
                throttle_a
            )

        # ====================================================
        # BRAKE
        # ====================================================

        if (
            "Brake Pos" in interp_a.columns
            and
            "Brake Pos" in interp_b.columns
        ):

            brake_a = (
                interp_a[
                    "Brake Pos"
                ]
                .to_numpy(
                    dtype=float
                )
            )

            brake_b = (
                interp_b[
                    "Brake Pos"
                ]
                .to_numpy(
                    dtype=float
                )
            )

            result[
                "brake_a"
            ] = brake_a

            result[
                "brake_b"
            ] = brake_b

            result[
                "brake_delta"
            ] = (
                brake_b
                -
                brake_a
            )

        # ====================================================
        # STEERING
        # ====================================================

        if (
            "Steering Pos" in interp_a.columns
            and
            "Steering Pos" in interp_b.columns
        ):

            steering_a = (
                interp_a[
                    "Steering Pos"
                ]
                .to_numpy(
                    dtype=float
                )
            )

            steering_b = (
                interp_b[
                    "Steering Pos"
                ]
                .to_numpy(
                    dtype=float
                )
            )

            result[
                "steering_a"
            ] = steering_a

            result[
                "steering_b"
            ] = steering_b

            result[
                "steering_delta"
            ] = (
                steering_b
                -
                steering_a
            )

        # ====================================================
        # PERFIL TEMPORAL REAL
        # ====================================================

        duration_a = float(
            data_a[
                "lap_duration_real"
            ].iloc[0]
        )

        duration_b = float(
            data_b[
                "lap_duration_real"
            ].iloc[0]
        )

        time_profile_a = (
            self._build_time_profile(
                interp_a,
                duration_a,
            )
        )

        time_profile_b = (
            self._build_time_profile(
                interp_b,
                duration_b,
            )
        )

        result[
            "time_a"
        ] = time_profile_a

        result[
            "time_b"
        ] = time_profile_b

        # ----------------------------------------------------
        # DELTA
        # ----------------------------------------------------

        result[
            "time_delta"
        ] = (
            time_profile_b
            -
            time_profile_a
        )

        # ----------------------------------------------------
        # FORZAR EXTREMO FINAL
        #
        # Esto garantiza que:
        #
        # time_delta[-1]
        # =
        # duration_b - duration_a
        #
        # ----------------------------------------------------

        result.loc[
            result.index[-1],
            "time_delta"
        ] = (
            duration_b
            -
            duration_a
        )

        return result

    # ========================================================
    # ALIAS
    # ========================================================

    def compare_laps(
        self,
        lap_a,
        lap_b,
        resolution=1.0,
    ):
        """
        Alias compatible con versiones anteriores.
        """

        return self.compare(
            lap_a,
            lap_b,
            resolution,
        )

    # ========================================================
    # RESUMEN
    # ========================================================

    def summary(
        self,
        lap_a,
        lap_b,
        resolution=1.0,
        count=10,
    ):
        """
        Genera un resumen completo de la comparación.
        """

        if count <= 0:

            raise ValueError(
                "count debe ser mayor que cero."
            )

        comparison = self.compare(
            lap_a,
            lap_b,
            resolution,
        )

        if comparison.empty:

            raise ValueError(
                "La comparación no produjo datos."
            )

        # ====================================================
        # DELTA FINAL
        # ====================================================

        delta_final = float(
            comparison[
                "time_delta"
            ].iloc[-1]
        )

        # ====================================================
        # MAYOR PÉRDIDA
        # ====================================================

        loss_idx = (
            comparison[
                "time_delta"
            ]
            .idxmax()
        )

        loss_row = comparison.loc[
            loss_idx
        ]

        # ====================================================
        # MAYOR GANANCIA
        # ====================================================

        gain_idx = (
            comparison[
                "time_delta"
            ]
            .idxmin()
        )

        gain_row = comparison.loc[
            gain_idx
        ]

        # ====================================================
        # TIEMPOS REALES
        # ====================================================

        summary_a = self.laps.lap_summary(
            lap_a
        )

        summary_b = self.laps.lap_summary(
            lap_b
        )

        real_time_a = float(
            summary_a[
                "duration"
            ]
        )

        real_time_b = float(
            summary_b[
                "duration"
            ]
        )

        expected_delta = (
            real_time_b
            -
            real_time_a
        )

        calculated_error = (
            delta_final
            -
            expected_delta
        )

        # ====================================================
        # MAYORES PÉRDIDAS
        # ====================================================

        biggest_losses = (
            comparison
            .sort_values(
                "time_delta",
                ascending=False,
            )
            .head(
                count
            )
            .reset_index(
                drop=True
            )
        )

        # ====================================================
        # MAYORES GANANCIAS
        # ====================================================

        biggest_gains = (
            comparison
            .sort_values(
                "time_delta",
                ascending=True,
            )
            .head(
                count
            )
            .reset_index(
                drop=True
            )
        )

        # ====================================================
        # RESULTADO
        # ====================================================

        return {

            "lap_a":
                lap_a,

            "lap_b":
                lap_b,

            "distance":
                float(
                    comparison[
                        "distance"
                    ].iloc[-1]
                ),

            "delta_final":
                delta_final,

            "max_loss":
                float(
                    loss_row[
                        "time_delta"
                    ]
                ),

            "max_loss_distance":
                float(
                    loss_row[
                        "distance"
                    ]
                ),

            "max_gain":
                float(
                    gain_row[
                        "time_delta"
                    ]
                ),

            "max_gain_distance":
                float(
                    gain_row[
                        "distance"
                    ]
                ),

            "real_time_a":
                real_time_a,

            "real_time_b":
                real_time_b,

            "expected_delta":
                expected_delta,

            "calculated_error":
                calculated_error,

            "biggest_losses":
                biggest_losses,

            "biggest_gains":
                biggest_gains,

            "comparison":
                comparison,
        }