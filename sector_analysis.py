import numpy as np
import pandas as pd


class SectorAnalysis:
    """
    Analiza el delta espacial producido por DeltaComparison.

    La clasificación de una zona NO depende del signo absoluto
    de time_delta.

    Se utiliza la variación del delta:

        delta aumenta   -> loss
        delta disminuye -> gain

    Ejemplo:

        -1.0 -> -1.5 = gain de 0.5 s
        -1.0 -> -0.5 = loss de 0.5 s

    Esto es independiente de que el delta sea positivo
    o negativo.
    """

    def __init__(self, delta_comparison):
        self.delta = delta_comparison

    # =====================================================
    # OBTENER COMPARACIÓN
    # =====================================================

    def _get_comparison(
        self,
        lap_a,
        lap_b,
        resolution=1.0,
    ):
        """
        Ejecuta DeltaComparison.compare().
        """

        comparison = self.delta.compare(
            lap_a,
            lap_b,
            resolution,
        )

        if comparison is None:
            raise ValueError(
                "DeltaComparison no devolvió datos."
            )

        if comparison.empty:
            raise ValueError(
                "La comparación está vacía."
            )

        required = [
            "distance",
            "time_delta",
        ]

        missing = [
            column
            for column in required
            if column not in comparison.columns
        ]

        if missing:
            raise ValueError(
                "Faltan columnas necesarias: "
                + ", ".join(missing)
            )

        return comparison.copy()

    # =====================================================
    # LIMPIAR COMPARACIÓN
    # =====================================================

    def _clean_comparison(
        self,
        comparison,
    ):
        """
        Limpia y ordena la comparación.

        También garantiza que distance sea estrictamente
        creciente.
        """

        result = comparison.copy()

        result["distance"] = pd.to_numeric(
            result["distance"],
            errors="coerce",
        )

        result["time_delta"] = pd.to_numeric(
            result["time_delta"],
            errors="coerce",
        )

        result = result.dropna(
            subset=[
                "distance",
                "time_delta",
            ]
        )

        result = result[
            np.isfinite(result["distance"])
            &
            np.isfinite(result["time_delta"])
        ]

        result = result.sort_values(
            "distance",
            kind="stable",
        )

        result = result.drop_duplicates(
            subset=["distance"],
            keep="first",
        )

        result = result.reset_index(
            drop=True
        )

        if len(result) < 2:
            raise ValueError(
                "No hay suficientes puntos "
                "para analizar sectores."
            )

        return result

    # =====================================================
    # DIFERENCIA DE VELOCIDAD
    # =====================================================

    def _add_speed_difference(
        self,
        comparison,
    ):
        """
        Agrega speed_delta si existen las velocidades.

        Convención:

            speed_delta = speed_b - speed_a
        """

        result = comparison.copy()

        if (
            "speed_a" in result.columns
            and
            "speed_b" in result.columns
        ):

            result["speed_a"] = pd.to_numeric(
                result["speed_a"],
                errors="coerce",
            )

            result["speed_b"] = pd.to_numeric(
                result["speed_b"],
                errors="coerce",
            )

            result["speed_delta"] = (
                result["speed_b"]
                -
                result["speed_a"]
            )

        return result

    # =====================================================
    # CALCULAR CAMBIO DE DELTA
    # =====================================================

    def _calculate_delta_change(
        self,
        data,
    ):
        """
        Calcula el cambio del delta entre puntos consecutivos.

        Positivo:
            el delta aumenta -> loss.

        Negativo:
            el delta disminuye -> gain.

        El primer punto siempre tiene cambio 0.
        """

        delta = data[
            "time_delta"
        ].to_numpy(
            dtype=float
        )

        change = np.diff(
            delta,
            prepend=delta[0],
        )

        change[~np.isfinite(change)] = 0.0

        return change

    # =====================================================
    # SUAVIZAR DELTA
    # =====================================================

    def _smooth_delta(
        self,
        data,
        window=5,
    ):
        """
        Suaviza el delta antes de detectar zonas.

        Se utiliza solamente para determinar la dirección
        de evolución del delta.

        Las métricas finales de cada zona se calculan siempre
        utilizando el delta original.
        """

        if window <= 1:
            return data[
                "time_delta"
            ].to_numpy(dtype=float)

        delta = data[
            "time_delta"
        ].to_numpy(dtype=float)

        return (
            pd.Series(delta)
            .rolling(
                window=window,
                center=True,
                min_periods=1,
            )
            .mean()
            .to_numpy(dtype=float)
        )

    # =====================================================
    # CREAR ZONA
    # =====================================================

    def _build_zone(
        self,
        data,
        zone_type,
        start_index,
        end_index,
        threshold,
        min_zone_distance,
    ):
        """
        Construye una zona y valida su importancia.
        """

        if end_index <= start_index:
            return None

        distance = data[
            "distance"
        ].to_numpy(dtype=float)

        delta = data[
            "time_delta"
        ].to_numpy(dtype=float)

        start_distance = float(
            distance[start_index]
        )

        end_distance = float(
            distance[end_index]
        )

        zone_length = (
            end_distance
            -
            start_distance
        )

        delta_start = float(
            delta[start_index]
        )

        delta_end = float(
            delta[end_index]
        )

        delta_change = (
            delta_end
            -
            delta_start
        )

        # -------------------------------------------------
        # Filtros
        # -------------------------------------------------

        if zone_length < min_zone_distance:
            return None

        if abs(delta_change) < threshold:
            return None

        return {
            "type": zone_type,

            "start_index": int(
                start_index
            ),

            "end_index": int(
                end_index
            ),

            "start_distance": start_distance,

            "end_distance": end_distance,

            "delta_start": delta_start,

            "delta_end": delta_end,

            "delta_change": float(
                delta_change
            ),
        }

    # =====================================================
    # DETECTAR ZONAS
    # =====================================================

    def detect_zones(
        self,
        comparison,
        threshold=0.05,
        merge_distance=50.0,
        min_zone_distance=10.0,
        smoothing_window=5,
        direction_threshold=0.001,
    ):
        """
        Detecta zonas consecutivas de ganancia y pérdida.

        La clasificación se basa exclusivamente en la
        evolución espacial del delta.

            delta aumenta   -> loss
            delta disminuye -> gain

        threshold:
            Cambio mínimo acumulado del delta necesario
            para conservar una zona.

        merge_distance:
            Distancia máxima entre dos zonas del mismo tipo
            para fusionarlas.

        min_zone_distance:
            Longitud mínima de una zona.

        smoothing_window:
            Ventana utilizada para determinar la tendencia.

        direction_threshold:
            Cambio mínimo entre muestras para considerar
            que existe una dirección.
        """

        data = self._clean_comparison(
            comparison
        )

        if threshold < 0:
            raise ValueError(
                "threshold no puede ser negativo."
            )

        if merge_distance < 0:
            raise ValueError(
                "merge_distance no puede ser negativo."
            )

        if min_zone_distance < 0:
            raise ValueError(
                "min_zone_distance no puede ser negativo."
            )

        if smoothing_window <= 0:
            raise ValueError(
                "smoothing_window debe ser "
                "mayor que cero."
            )

        if direction_threshold < 0:
            raise ValueError(
                "direction_threshold no puede "
                "ser negativo."
            )

        if len(data) < 2:
            return []

        distance = data[
            "distance"
        ].to_numpy(dtype=float)

        smooth_delta = self._smooth_delta(
            data,
            window=smoothing_window,
        )

        # -------------------------------------------------
        # Determinar dirección por segmento
        # -------------------------------------------------

        changes = np.diff(
            smooth_delta
        )

        signs = np.zeros(
            len(changes),
            dtype=int,
        )

        signs[
            changes > direction_threshold
        ] = 1

        signs[
            changes < -direction_threshold
        ] = -1

        # -------------------------------------------------
        # Rellenar pequeños intervalos neutros.
        #
        # Un cambio puntual menor al umbral no debería
        # crear artificialmente una nueva zona.
        # -------------------------------------------------

        for i in range(
            1,
            len(signs) - 1,
        ):

            if signs[i] != 0:
                continue

            if (
                signs[i - 1] != 0
                and
                signs[i - 1] == signs[i + 1]
            ):
                signs[i] = signs[i - 1]

        # -------------------------------------------------
        # Detectar runs consecutivos
        # -------------------------------------------------

        zones = []

        current_sign = 0
        current_start = None

        for i, sign in enumerate(signs):

            if sign == 0:
                continue

            if current_sign == 0:

                current_sign = sign
                current_start = i

                continue

            if sign == current_sign:
                continue

            # -------------------------------------------------
            # Cerramos la zona anterior.
            #
            # signs[i] representa el segmento:
            #
            # distance[i] -> distance[i + 1]
            #
            # Por eso la zona termina en i.
            # -------------------------------------------------

            start_index = current_start

            end_index = i

            zone_type = (
                "loss"
                if current_sign > 0
                else "gain"
            )

            zone = self._build_zone(
                data,
                zone_type,
                start_index,
                end_index,
                threshold,
                min_zone_distance,
            )

            if zone is not None:
                zones.append(zone)

            # -------------------------------------------------
            # Nueva zona
            # -------------------------------------------------

            current_sign = sign
            current_start = i

        # =====================================================
        # ÚLTIMA ZONA
        # =====================================================

        if (
            current_sign != 0
            and
            current_start is not None
        ):

            start_index = current_start

            end_index = len(
                data
            ) - 1

            zone_type = (
                "loss"
                if current_sign > 0
                else "gain"
            )

            zone = self._build_zone(
                data,
                zone_type,
                start_index,
                end_index,
                threshold,
                min_zone_distance,
            )

            if zone is not None:
                zones.append(zone)

        # =====================================================
        # FUSIONAR ZONAS CERCANAS
        # =====================================================

        merged = []

        for zone in zones:

            if not merged:
                merged.append(
                    zone.copy()
                )
                continue

            previous = merged[-1]

            gap = (
                zone["start_distance"]
                -
                previous["end_distance"]
            )

            if (
                zone["type"]
                ==
                previous["type"]
                and
                gap <= merge_distance
            ):

                previous["end_index"] = (
                    zone["end_index"]
                )

                previous["end_distance"] = (
                    zone["end_distance"]
                )

                previous["delta_end"] = (
                    zone["delta_end"]
                )

                previous["delta_change"] = (
                    previous["delta_end"]
                    -
                    previous["delta_start"]
                )

            else:

                merged.append(
                    zone.copy()
                )

        return merged

    # =====================================================
    # RESUMIR ZONA
    # =====================================================

    def summarize_zone(
        self,
        comparison,
        zone,
    ):
        """
        Genera todas las métricas de una zona.

        Las métricas temporales utilizan el delta original,
        no el delta suavizado.
        """

        data = comparison.iloc[
            zone["start_index"]:
            zone["end_index"] + 1
        ].copy()

        if data.empty:
            raise ValueError(
                "La zona no contiene datos."
            )

        delta_start = float(
            data[
                "time_delta"
            ].iloc[0]
        )

        delta_end = float(
            data[
                "time_delta"
            ].iloc[-1]
        )

        delta_change = (
            delta_end
            -
            delta_start
        )

        result = {
            "type": zone["type"],

            "start_distance": float(
                data[
                    "distance"
                ].iloc[0]
            ),

            "end_distance": float(
                data[
                    "distance"
                ].iloc[-1]
            ),

            "distance": float(
                data[
                    "distance"
                ].iloc[-1]
                -
                data[
                    "distance"
                ].iloc[0]
            ),

            "delta_start": delta_start,

            "delta_end": delta_end,

            "delta_change": float(
                delta_change
            ),

            "max_delta": float(
                data[
                    "time_delta"
                ].max()
            ),

            "min_delta": float(
                data[
                    "time_delta"
                ].min()
            ),
        }

        # =================================================
        # VELOCIDAD
        # =================================================

        if "speed_a" in data.columns:

            result["speed_a_avg"] = float(
                data[
                    "speed_a"
                ].mean()
            )

            result["speed_a_min"] = float(
                data[
                    "speed_a"
                ].min()
            )

            result["speed_a_max"] = float(
                data[
                    "speed_a"
                ].max()
            )

        if "speed_b" in data.columns:

            result["speed_b_avg"] = float(
                data[
                    "speed_b"
                ].mean()
            )

            result["speed_b_min"] = float(
                data[
                    "speed_b"
                ].min()
            )

            result["speed_b_max"] = float(
                data[
                    "speed_b"
                ].max()
            )

        if "speed_delta" in data.columns:

            result["speed_delta_avg"] = float(
                data[
                    "speed_delta"
                ].mean()
            )

            result["speed_delta_min"] = float(
                data[
                    "speed_delta"
                ].min()
            )

            result["speed_delta_max"] = float(
                data[
                    "speed_delta"
                ].max()
            )

        # =================================================
        # THROTTLE
        # =================================================

        if "throttle_a" in data.columns:

            result["throttle_a_avg"] = float(
                data[
                    "throttle_a"
                ].mean()
            )

            result["throttle_a_max"] = float(
                data[
                    "throttle_a"
                ].max()
            )

        if "throttle_b" in data.columns:

            result["throttle_b_avg"] = float(
                data[
                    "throttle_b"
                ].mean()
            )

            result["throttle_b_max"] = float(
                data[
                    "throttle_b"
                ].max()
            )

        if "throttle_delta" in data.columns:

            result["throttle_delta_avg"] = float(
                data[
                    "throttle_delta"
                ].mean()
            )

        # =================================================
        # FRENO
        # =================================================

        if "brake_a" in data.columns:

            result["brake_a_max"] = float(
                data[
                    "brake_a"
                ].max()
            )

            result["brake_a_avg"] = float(
                data[
                    "brake_a"
                ].mean()
            )

        if "brake_b" in data.columns:

            result["brake_b_max"] = float(
                data[
                    "brake_b"
                ].max()
            )

            result["brake_b_avg"] = float(
                data[
                    "brake_b"
                ].mean()
            )

        if "brake_delta" in data.columns:

            result["brake_delta_avg"] = float(
                data[
                    "brake_delta"
                ].mean()
            )

        # =================================================
        # RPM
        # =================================================

        if "rpm_a" in data.columns:

            result["rpm_a_avg"] = float(
                data[
                    "rpm_a"
                ].mean()
            )

            result["rpm_a_max"] = float(
                data[
                    "rpm_a"
                ].max()
            )

        if "rpm_b" in data.columns:

            result["rpm_b_avg"] = float(
                data[
                    "rpm_b"
                ].mean()
            )

            result["rpm_b_max"] = float(
                data[
                    "rpm_b"
                ].max()
            )

        # =================================================
        # DIRECCIÓN
        # =================================================

        if "steering_a" in data.columns:

            result["steering_a_avg"] = float(
                data[
                    "steering_a"
                ].mean()
            )

        if "steering_b" in data.columns:

            result["steering_b_avg"] = float(
                data[
                    "steering_b"
                ].mean()
            )

        if "steering_delta" in data.columns:

            result["steering_delta_avg"] = float(
                data[
                    "steering_delta"
                ].mean()
            )

        return result

    # =====================================================
    # ANALIZAR
    # =====================================================

    def analyze(
        self,
        lap_a,
        lap_b,
        resolution=1.0,
        threshold=0.05,
        merge_distance=50.0,
        min_zone_distance=10.0,
        smoothing_window=5,
        direction_threshold=0.001,
    ):
        """
        Ejecuta el análisis completo.
        """

        comparison = self._get_comparison(
            lap_a,
            lap_b,
            resolution,
        )

        comparison = self._clean_comparison(
            comparison
        )

        comparison = self._add_speed_difference(
            comparison
        )

        zones = self.detect_zones(
            comparison,
            threshold=threshold,
            merge_distance=merge_distance,
            min_zone_distance=min_zone_distance,
            smoothing_window=smoothing_window,
            direction_threshold=direction_threshold,
        )

        summaries = []

        for zone in zones:

            zone_summary = self.summarize_zone(
                comparison,
                zone,
            )

            summaries.append(
                zone_summary
            )

        return {
            "lap_a": lap_a,
            "lap_b": lap_b,

            "resolution": resolution,

            "threshold": threshold,

            "merge_distance": merge_distance,

            "min_zone_distance": min_zone_distance,

            "smoothing_window": smoothing_window,

            "direction_threshold": direction_threshold,

            "comparison": comparison,

            "zones": zones,

            "summaries": summaries,
        }

    # =====================================================
    # RESUMEN
    # =====================================================

    def summary(
        self,
        lap_a,
        lap_b,
        resolution=1.0,
        threshold=0.05,
        merge_distance=50.0,
        min_zone_distance=10.0,
        smoothing_window=5,
        direction_threshold=0.001,
    ):
        """
        Devuelve un resumen listo para imprimir.
        """

        result = self.analyze(
            lap_a,
            lap_b,
            resolution,
            threshold,
            merge_distance,
            min_zone_distance,
            smoothing_window,
            direction_threshold,
        )

        comparison = result[
            "comparison"
        ]

        summaries = result[
            "summaries"
        ]

        final_delta = float(
            comparison[
                "time_delta"
            ].iloc[-1]
        )

        return {
            "lap_a": lap_a,

            "lap_b": lap_b,

            "distance": float(
                comparison[
                    "distance"
                ].iloc[-1]
            ),

            "final_delta": final_delta,

            "zone_count": len(
                summaries
            ),

            "zones": summaries,

            "comparison": comparison,
        }