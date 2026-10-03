"""
Tests de la auditoría adaptada a Open-Meteo (M5c Bloque 5.3).

Se corren con:
    cd engine
    python -m unittest services.test_auditoria -v

IMPORTANTE: estos tests escriben en la base local de Docker. Todas las
filas que crean llevan el prefijo `TEST_M5C_AUDIT_` en el id_externo de
la estación (y por lo tanto en cascada). El setUp y el tearDown borran
TODO lo que tenga ese prefijo: no hay riesgo de tocar datos reales.

Los datos son SINTÉTICOS: fechas fijas (2026-09-15), valores redondos
(90, 100), inventados a mano para que el error se pueda verificar
mentalmente. Ningún test depende de la red ni de la API real: la única
verificación con datos reales es el Bloque 6.

Sobre los conteos del resumen: `calcular_auditorias` opera sobre TODAS
las filas pendientes de la base, no solo las de este test. Los tests que
verifican el estado de una fila lo hacen por id (`leer_auditoria`); los
que necesitan mirar el resumen global usan `assertGreaterEqual` en vez
de `assertEqual`, para no depender de cuántas filas reales haya en la
base en el momento de correr.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import delete, select

from database.models import (
    AuditoriaPronostico,
    Estacion,
    Lectura,
    Pronostico,
    utcnow,
)
from database.session import SessionLocal
from services.auditoria import (
    MIN_HORAS_CON_LECTURA_AUDITORIA,
    OFFSET_COLOMBIA,
    calcular_auditorias,
)

PREFIJO_TEST = "TEST_M5C_AUDIT_"

# Un "hoy" fijo, en hora local Colombia: 2026-10-03 12:00 -05 = 17:00 UTC.
# Cualquier fecha_objetivo anterior a 2026-10-03 es pasado y se procesa.
HOY_FIJO = datetime(2026, 10, 3, 17, 0, tzinfo=timezone.utc)
DIA_PASADO = date(2026, 9, 15)  # muy anterior a HOY_FIJO
DIA_FUTURO = date(2026, 10, 10)  # muy posterior a HOY_FIJO


def _utc_de_hora_local(fecha_local: date, hora: int) -> datetime:
    """Hora H del día local Colombia, en UTC. La hora 0 local = 05:00 UTC
    del mismo día."""
    local = datetime.combine(fecha_local, time(hour=hora), tzinfo=OFFSET_COLOMBIA)
    return local.astimezone(timezone.utc)


def _limpiar_todo(db) -> None:
    """Borra cualquier residuo de tests. Se llama al inicio y al final de
    cada test para que un fallo a mitad no ensucie el siguiente.

    Orden por las FK RESTRICT: primero las auditorías (que apuntan a los
    pronósticos con CASCADE, pero las borramos explícitas), después los
    pronósticos y las lecturas, y por último las estaciones.
    """
    ids_estacion = list(
        db.execute(
            select(Estacion.id).where(Estacion.id_externo.like(f"{PREFIJO_TEST}%"))
        ).scalars()
    )
    if not ids_estacion:
        return
    ids_pron = list(
        db.execute(
            select(Pronostico.id).where(Pronostico.estacion_id.in_(ids_estacion))
        ).scalars()
    )
    if ids_pron:
        db.execute(delete(AuditoriaPronostico).where(
            AuditoriaPronostico.pronostico_id.in_(ids_pron)
        ))
    db.execute(delete(Pronostico).where(Pronostico.estacion_id.in_(ids_estacion)))
    db.execute(delete(Lectura).where(Lectura.estacion_id.in_(ids_estacion)))
    db.execute(delete(Estacion).where(Estacion.id.in_(ids_estacion)))
    db.commit()


class _BaseTestAuditoria(unittest.TestCase):
    """Clase base: abre la sesión, limpia antes y después, y da helpers
    para crear estación / lecturas / pronóstico de prueba."""

    def setUp(self) -> None:
        self.db = SessionLocal()
        _limpiar_todo(self.db)

    def tearDown(self) -> None:
        _limpiar_todo(self.db)
        self.db.close()

    def crear_estacion(self, sufijo: str) -> Estacion:
        """Estación AQICN de prueba, con id_externo marcado como TEST."""
        est = Estacion(
            fuente="aqicn",
            id_externo=f"{PREFIJO_TEST}{sufijo}",
            nombre=f"Estación de prueba M5c ({sufijo})",
            latitud=4.65,
            longitud=-74.09,
            activa=True,
        )
        self.db.add(est)
        self.db.flush()
        return est

    def crear_lecturas_horarias(
        self, estacion_id: int, contaminante: str, valor: float, n_horas: int,
        fecha_local: date = DIA_PASADO,
    ) -> None:
        """N lecturas, una por hora local, todas con el mismo valor.

        Por defecto 24 horas (día completo). Con `n_horas` < 24 el día
        queda con horas insuficientes (D66) y la auditoría debe dejarlo
        pendiente.
        """
        for h in range(n_horas):
            self.db.add(Lectura(
                estacion_id=estacion_id,
                contaminante=contaminante,
                valor=valor,
                unidad="AQI",
                medido_en=_utc_de_hora_local(fecha_local, h),
            ))
        self.db.flush()

    def crear_pronostico_y_auditoria(
        self,
        estacion_id: int,
        contaminante: str,
        valor_promedio: float,
        unidad: str,
        fecha_objetivo: date = DIA_PASADO,
    ) -> tuple[int, int]:
        """Un pronóstico 'open-meteo' + su auditoría 'pendiente'.
        Devuelve (pronostico_id, auditoria_id)."""
        p = Pronostico(
            fuente="open-meteo",
            estacion_id=estacion_id,
            contaminante=contaminante,
            fecha_objetivo=fecha_objetivo,
            valor_promedio=valor_promedio,
            valor_min=valor_promedio,
            valor_max=valor_promedio,
            unidad=unidad,
            fecha_captura=date(2026, 9, 14),
        )
        self.db.add(p)
        self.db.flush()
        a = AuditoriaPronostico(pronostico_id=p.id, estado="pendiente")
        self.db.add(a)
        self.db.flush()
        return p.id, a.id

    def leer_auditoria(self, auditoria_id: int) -> AuditoriaPronostico:
        """Refresca la auditoría desde la base para ver cambios persistidos."""
        self.db.expire_all()
        return self.db.get(AuditoriaPronostico, auditoria_id)


class TestErrorCalculadoAManoConAqi(_BaseTestAuditoria):
    """`aqi` no se convierte: se compara `us_aqi` del pronóstico con el
    promedio de las lecturas tal cual (D64)."""

    def test_error_aqi_directo(self) -> None:
        est = self.crear_estacion("aqi_directo")
        # 24 lecturas reales con valor 100 -> promedio 100.
        self.crear_lecturas_horarias(est.id, "aqi", 100.0, n_horas=24)
        # Pronóstico: 80. Diferencia esperada: 20. Sesgo: -20 (quedó BAJO).
        _, aud_id = self.crear_pronostico_y_auditoria(
            est.id, "aqi", 80.0, unidad="AQI"
        )
        calcular_auditorias(self.db, ahora=HOY_FIJO)
        a = self.leer_auditoria(aud_id)
        self.assertEqual(a.estado, "resuelta")
        self.assertAlmostEqual(a.valor_real or 0.0, 100.0, places=6)
        self.assertAlmostEqual(a.error_abs or 0.0, 20.0, places=6)
        self.assertAlmostEqual(a.sesgo or 0.0, -20.0, places=6)
        self.assertAlmostEqual(a.error_rel or 0.0, 0.2, places=6)
        self.assertEqual(a.fuente_real, "aqicn")
        self.assertEqual(a.n_lecturas_real, 24)
        self.assertEqual(a.horas_con_lectura, 24)


class TestErrorCalculadoAManoConPm25(_BaseTestAuditoria):
    """`pm25` SÍ se convierte: pronóstico µg/m³ -> AQI con la tabla EPA
    (services/aqi_escala). Verificamos un valor que cae en un breakpoint
    exacto de la tabla."""

    def test_error_pm25_con_conversion(self) -> None:
        est = self.crear_estacion("pm25_conv")
        # Real: 24 horas a 90 AQI -> promedio 90.
        self.crear_lecturas_horarias(est.id, "pm25", 90.0, n_horas=24)
        # Pronóstico: 35.4 µg/m³. Por tabla EPA (tramo 9.1-35.4 -> 51-100),
        # 35.4 µg/m³ = exactamente AQI 100. Diferencia esperada: 10.
        # Sesgo: +10 (pronóstico quedó ALTO).
        _, aud_id = self.crear_pronostico_y_auditoria(
            est.id, "pm25", 35.4, unidad="\u00b5g/m\u00b3"
        )
        calcular_auditorias(self.db, ahora=HOY_FIJO)
        a = self.leer_auditoria(aud_id)
        self.assertEqual(a.estado, "resuelta")
        self.assertAlmostEqual(a.valor_real or 0.0, 90.0, places=6)
        self.assertAlmostEqual(a.error_abs or 0.0, 10.0, places=4)
        self.assertAlmostEqual(a.sesgo or 0.0, 10.0, places=4)


class TestHorasInsuficientes(_BaseTestAuditoria):
    """D66: menos de MIN_HORAS_CON_LECTURA_AUDITORIA horas con lectura
    deja la fila pendiente. No se calcula con datos parciales."""

    def test_dia_con_pocas_horas_queda_pendiente(self) -> None:
        est = self.crear_estacion("horas_insuf")
        # 5 horas de lecturas (muy por debajo del mínimo de 16).
        self.crear_lecturas_horarias(est.id, "aqi", 100.0, n_horas=5)
        _, aud_id = self.crear_pronostico_y_auditoria(
            est.id, "aqi", 80.0, unidad="AQI"
        )
        calcular_auditorias(self.db, ahora=HOY_FIJO)
        a = self.leer_auditoria(aud_id)
        # La fila sigue pendiente; se guardaron las horas y n_lecturas
        # para que quede el rastro de por qué no se calculó, pero NO se
        # escribió el error.
        self.assertEqual(a.estado, "pendiente")
        self.assertEqual(a.horas_con_lectura, 5)
        self.assertEqual(a.n_lecturas_real, 5)
        self.assertIsNone(a.error_abs)
        self.assertIsNone(a.valor_real)

    def test_justo_en_el_minimo_se_resuelve(self) -> None:
        """El criterio es `>= MIN_HORAS...`. Justo en el umbral, resuelve."""
        est = self.crear_estacion("horas_justas")
        self.crear_lecturas_horarias(
            est.id, "aqi", 100.0, n_horas=MIN_HORAS_CON_LECTURA_AUDITORIA
        )
        _, aud_id = self.crear_pronostico_y_auditoria(
            est.id, "aqi", 80.0, unidad="AQI"
        )
        calcular_auditorias(self.db, ahora=HOY_FIJO)
        a = self.leer_auditoria(aud_id)
        self.assertEqual(a.estado, "resuelta")
        self.assertEqual(a.horas_con_lectura, MIN_HORAS_CON_LECTURA_AUDITORIA)


class TestContaminanteNoAuditable(_BaseTestAuditoria):
    """D64: o3/no2/so2/co se capturan pero no se auditan (M5a no convierte
    µg/m³ → ppb/ppm). La fila pasa a 'no_auditable' sin inventar un número."""

    def test_o3_no_es_auditable(self) -> None:
        est = self.crear_estacion("o3_no_aud")
        self.crear_lecturas_horarias(est.id, "o3", 50.0, n_horas=24)
        _, aud_id = self.crear_pronostico_y_auditoria(
            est.id, "o3", 60.0, unidad="\u00b5g/m\u00b3"
        )
        calcular_auditorias(self.db, ahora=HOY_FIJO)
        a = self.leer_auditoria(aud_id)
        self.assertEqual(a.estado, "no_auditable")
        self.assertIsNone(a.valor_real)
        self.assertIsNone(a.error_abs)

    def test_co_no_es_auditable(self) -> None:
        est = self.crear_estacion("co_no_aud")
        self.crear_lecturas_horarias(est.id, "co", 5.0, n_horas=24)
        _, aud_id = self.crear_pronostico_y_auditoria(
            est.id, "co", 3.0, unidad="\u00b5g/m\u00b3"
        )
        calcular_auditorias(self.db, ahora=HOY_FIJO)
        a = self.leer_auditoria(aud_id)
        self.assertEqual(a.estado, "no_auditable")


class TestHorizonte(_BaseTestAuditoria):
    """D54: el horizonte debe ser >= 1 día. Un pronóstico para hoy o
    futuro no se toca: la auditoría lo deja pendiente."""

    def test_pronostico_para_manana_no_se_toca(self) -> None:
        est = self.crear_estacion("horizonte_futuro")
        self.crear_lecturas_horarias(est.id, "aqi", 100.0, n_horas=24)
        _, aud_id = self.crear_pronostico_y_auditoria(
            est.id, "aqi", 80.0, unidad="AQI", fecha_objetivo=DIA_FUTURO
        )
        # El resumen incluye TODAS las pendientes de la base (hoy: las 324
        # reales del Bloque 4, que también caen en días futuros). No
        # contamos el total: verificamos que NUESTRA fila sigue pendiente.
        calcular_auditorias(self.db, ahora=HOY_FIJO)
        a = self.leer_auditoria(aud_id)
        self.assertEqual(a.estado, "pendiente")
        self.assertIsNone(a.valor_real)
        self.assertIsNone(a.horas_con_lectura)


class TestIdempotencia(_BaseTestAuditoria):
    """Correr la auditoría dos veces seguidas: la segunda no debe tocar
    nada. El SELECT solo ve pendientes; las resueltas no vuelven a entrar."""

    def test_segunda_corrida_no_cambia_nada(self) -> None:
        est = self.crear_estacion("idempotencia")
        self.crear_lecturas_horarias(est.id, "aqi", 100.0, n_horas=24)
        _, aud_id = self.crear_pronostico_y_auditoria(
            est.id, "aqi", 80.0, unidad="AQI"
        )
        calcular_auditorias(self.db, ahora=HOY_FIJO)
        a = self.leer_auditoria(aud_id)
        self.assertEqual(a.estado, "resuelta")
        error_primera = a.error_abs
        self.assertAlmostEqual(error_primera or 0.0, 20.0, places=6)

        # Segunda corrida: no debe tocar la fila ya resuelta.
        calcular_auditorias(self.db, ahora=HOY_FIJO)
        a = self.leer_auditoria(aud_id)
        self.assertEqual(a.estado, "resuelta")
        self.assertEqual(a.error_abs, error_primera)


if __name__ == "__main__":
    unittest.main()