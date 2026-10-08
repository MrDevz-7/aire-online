"""
Tests de los jobs del scheduler (M10 Bloques 2–5 + M10.1 Bloques 1–2).

Puros: mockean las funciones de servicio y la sesión de base. No arrancan
el scheduler real, no tocan red, no tocan Postgres.

Se corren con:
    cd engine
    python -m unittest scheduler.test_jobs -v
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from scheduler.jobs import (
    _ejecutar_una_fuente,
    _fuentes_ingesta,
    ejecutar_ingesta,
    job_auditoria,
    job_ingesta,
    job_pronosticos,
    job_purgas,
    job_purgas_sesiones,
    job_reconciliacion,
    job_reportes,
)


def _resumen_mock(nombre_fuente: str) -> MagicMock:
    """Crea un mock de ResumenIngestion con a_dict() y los campos que
    `_ejecutar_una_fuente` usa para loguear."""
    r = MagicMock()
    r.estaciones_nuevas = 1
    r.lecturas_insertadas = 10
    r.lecturas_duplicadas = 0
    r.lecturas_invalidas = 0
    r.a_dict.return_value = {"fuente": nombre_fuente, "lecturas_insertadas": 10}
    return r


def _resumen_generacion_vacio() -> MagicMock:
    """Mock de ResumenGeneracion con todos los campos que `job_reportes`
    lee para loguear. `reportes` vacío = 0 llamadas_ia."""
    r = MagicMock()
    r.totales = 0
    r.nuevos = 0
    r.reutilizados = 0
    r.por_origen = {}
    r.por_motivo_fallback = {}
    r.reportes = []
    return r


class TestFuentesIngesta(unittest.TestCase):
    def test_devuelve_las_4_fuentes_en_orden(self) -> None:
        fuentes = _fuentes_ingesta()
        nombres = [nombre for nombre, _ in fuentes]
        self.assertEqual(nombres, ["openaq", "aqicn", "iboca", "siata"])

    def test_se_reconstruye_en_cada_llamada(self) -> None:
        # Este es el motivo por el que NO es constante de módulo: un
        # patch de `scheduler.jobs.ejecutar_openaq` tiene que verse
        # reflejado. Si fuera constante, capturaría la referencia previa.
        with patch("scheduler.jobs.ejecutar_openaq") as m:
            fuentes = dict(_fuentes_ingesta())
            self.assertIs(fuentes["openaq"], m)


class TestEjecutarUnaFuente(unittest.TestCase):
    def test_ok_guarda_a_dict(self) -> None:
        resumen: dict[str, dict] = {}
        mock_resumen = _resumen_mock("openaq")
        _ejecutar_una_fuente("openaq", lambda db: mock_resumen, MagicMock(), resumen)
        self.assertEqual(resumen["openaq"], {"fuente": "openaq", "lecturas_insertadas": 10})

    def test_fallo_guarda_error_y_no_propaga(self) -> None:
        resumen: dict[str, dict] = {}

        def funcion_que_falla(db):
            raise RuntimeError("fuente caída")

        # No debe lanzar:
        _ejecutar_una_fuente("aqicn", funcion_que_falla, MagicMock(), resumen)
        self.assertIn("error", resumen["aqicn"])
        self.assertIn("fuente caída", resumen["aqicn"]["error"])


class TestEjecutarIngesta(unittest.TestCase):
    def test_todas_ok_devuelve_4_entradas(self) -> None:
        with patch("scheduler.jobs.ejecutar_openaq") as m_oq, \
             patch("scheduler.jobs.ejecutar_aqicn") as m_aq, \
             patch("scheduler.jobs.ejecutar_iboca") as m_ib, \
             patch("scheduler.jobs.ejecutar_siata") as m_si:
            m_oq.return_value = _resumen_mock("openaq")
            m_aq.return_value = _resumen_mock("aqicn")
            m_ib.return_value = _resumen_mock("iboca")
            m_si.return_value = _resumen_mock("siata")
            db = MagicMock()
            resumen = ejecutar_ingesta(db)

        self.assertEqual(set(resumen.keys()), {"openaq", "aqicn", "iboca", "siata"})
        for fuente in ("openaq", "aqicn", "iboca", "siata"):
            self.assertNotIn("error", resumen[fuente])
            self.assertEqual(resumen[fuente]["fuente"], fuente)

    def test_fallo_de_una_fuente_no_interrumpe_a_las_demas(self) -> None:
        with patch("scheduler.jobs.ejecutar_openaq") as m_oq, \
             patch("scheduler.jobs.ejecutar_aqicn") as m_aq, \
             patch("scheduler.jobs.ejecutar_iboca") as m_ib, \
             patch("scheduler.jobs.ejecutar_siata") as m_si:
            m_oq.return_value = _resumen_mock("openaq")
            m_aq.side_effect = RuntimeError("AQICN se cayó")
            m_ib.return_value = _resumen_mock("iboca")
            m_si.return_value = _resumen_mock("siata")
            db = MagicMock()
            resumen = ejecutar_ingesta(db)

        # Las 4 se intentaron (una no se saltea a las otras):
        m_oq.assert_called_once_with(db)
        m_aq.assert_called_once_with(db)
        m_ib.assert_called_once_with(db)
        m_si.assert_called_once_with(db)
        # Solo aqicn tiene error:
        self.assertIn("error", resumen["aqicn"])
        self.assertNotIn("error", resumen["openaq"])
        self.assertNotIn("error", resumen["iboca"])
        self.assertNotIn("error", resumen["siata"])

    def test_todas_fallan_devuelve_4_errores(self) -> None:
        with patch("scheduler.jobs.ejecutar_openaq") as m_oq, \
             patch("scheduler.jobs.ejecutar_aqicn") as m_aq, \
             patch("scheduler.jobs.ejecutar_iboca") as m_ib, \
             patch("scheduler.jobs.ejecutar_siata") as m_si:
            m_oq.side_effect = RuntimeError("a")
            m_aq.side_effect = RuntimeError("b")
            m_ib.side_effect = RuntimeError("c")
            m_si.side_effect = RuntimeError("d")
            resumen = ejecutar_ingesta(MagicMock())

        for fuente in ("openaq", "aqicn", "iboca", "siata"):
            self.assertIn("error", resumen[fuente])


class TestJobIngestaAbreYCierraSesion(unittest.TestCase):
    def test_abre_sesion_llama_y_cierra(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.ejecutar_ingesta") as m_ejecutar:
            m_session.return_value = MagicMock()
            m_ejecutar.return_value = {}
            job_ingesta()
            # Se abrió una sesión:
            m_session.assert_called_once()
            # Se le pasó a ejecutar_ingesta:
            m_ejecutar.assert_called_once_with(m_session.return_value)
            # Se cerró pese a todo:
            m_session.return_value.close.assert_called_once()

    def test_cierra_la_sesion_aunque_ejecutar_ingesta_falle(self) -> None:
        # `ejecutar_ingesta` no debería lanzar, pero si por un bug
        # lanzara, la sesión igual tiene que cerrarse (`finally`).
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.ejecutar_ingesta") as m_ejecutar:
            m_session.return_value = MagicMock()
            m_ejecutar.side_effect = RuntimeError("bug inesperado")
            with self.assertRaises(RuntimeError):
                job_ingesta()
            m_session.return_value.close.assert_called_once()


class TestJobPronosticos(unittest.TestCase):
    """Tests del job de captura de pronósticos (M10 Bloque 3)."""

    def test_exito_loguea_sin_error(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.capturar_pronosticos") as m_capturar:
            m_session.return_value = MagicMock()
            m_resumen = MagicMock()
            m_resumen.pronosticos_insertados = 5
            m_resumen.pronosticos_ya_existian = 0
            m_resumen.auditorias_creadas = 5
            m_resumen.requests = 2
            m_resumen.por_horizonte = {1: 3, 2: 2}
            m_capturar.return_value = m_resumen

            # No debe lanzar:
            job_pronosticos()

        m_capturar.assert_called_once_with(m_session.return_value)
        m_session.return_value.close.assert_called_once()

    def test_falla_no_propaga(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.capturar_pronosticos") as m_capturar:
            m_session.return_value = MagicMock()
            m_capturar.side_effect = RuntimeError("Open-Meteo caído")

            # No debe lanzar: el scheduler no debe morir por esto.
            job_pronosticos()

        # Y la sesión igual se cerró (finally):
        m_session.return_value.close.assert_called_once()

    def test_cierra_sesion_aunque_exito(self) -> None:
        # Idempotente con el test de éxito, pero separado para que quede
        # explícito el contrato de "siempre cierra".
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.capturar_pronosticos") as m_capturar:
            m_session.return_value = MagicMock()
            m_capturar.return_value = MagicMock()
            job_pronosticos()
        m_session.return_value.close.assert_called_once()


class TestJobAuditoria(unittest.TestCase):
    """Tests del job de auditoría (M10 Bloque 4)."""

    def test_exito_loguea_sin_error(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.calcular_auditorias") as m_calc:
            m_session.return_value = MagicMock()
            m_resumen = MagicMock()
            m_resumen.resueltas = 10
            m_resumen.sin_datos = 2
            m_resumen.no_auditables = 3
            m_resumen.todavia_no_vencen = 5
            m_resumen.pendientes_por_horas_insuficientes = 1
            m_resumen.pendientes_antes = 21
            m_calc.return_value = m_resumen

            # No debe lanzar:
            job_auditoria()

        m_calc.assert_called_once_with(m_session.return_value)
        m_session.return_value.close.assert_called_once()

    def test_falla_no_propaga(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.calcular_auditorias") as m_calc:
            m_session.return_value = MagicMock()
            m_calc.side_effect = RuntimeError("db caída")

            # No debe lanzar: el scheduler no debe morir por esto.
            job_auditoria()

        # Y la sesión igual se cerró (finally):
        m_session.return_value.close.assert_called_once()

    def test_cierra_sesion_aunque_exito(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.calcular_auditorias") as m_calc:
            m_session.return_value = MagicMock()
            m_calc.return_value = MagicMock()
            job_auditoria()
        m_session.return_value.close.assert_called_once()


class TestPurgaLecturas(unittest.TestCase):
    """Tests del job de purga de lecturas (M10 Bloque 5, D90)."""

    def test_exito_ejecuta_delete_y_commitea(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session:
            db = MagicMock()
            m_session.return_value = db
            # El DELETE devuelve un rowcount.
            db.execute.return_value.rowcount = 42

            job_purgas()

        # Se ejecutó UN delete (el de lecturas):
        self.assertEqual(db.execute.call_count, 1)
        db.commit.assert_called_once()
        db.close.assert_called_once()
        # No debe haber rollback en un caso de éxito:
        db.rollback.assert_not_called()

    def test_sin_filas_borradas_no_falla(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session:
            db = MagicMock()
            m_session.return_value = db
            # rowcount = 0 (no había nada para borrar)
            db.execute.return_value.rowcount = 0

            job_purgas()  # no debe lanzar

        db.commit.assert_called_once()
        db.close.assert_called_once()

    def test_falla_hace_rollback_y_no_propaga(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session:
            db = MagicMock()
            m_session.return_value = db
            db.execute.side_effect = RuntimeError("db caída")

            # No debe lanzar:
            job_purgas()

        # Se intentó hacer rollback:
        db.rollback.assert_called_once()
        # No se commiteó:
        db.commit.assert_not_called()
        # Igual se cerró:
        db.close.assert_called_once()


class TestPurgaSesiones(unittest.TestCase):
    """Tests del job de purga de sesiones (M10 Bloque 5, D91)."""

    def test_exito_dos_deletes_y_commit(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session:
            db = MagicMock()
            m_session.return_value = db
            # El primer execute (vencidas) devuelve 3; el segundo (revocadas) devuelve 5.
            db.execute.side_effect = [
                MagicMock(rowcount=3),
                MagicMock(rowcount=5),
            ]

            job_purgas_sesiones()

        # Se hicieron DOS deletes (vencidas + revocadas):
        self.assertEqual(db.execute.call_count, 2)
        db.commit.assert_called_once()
        db.close.assert_called_once()
        db.rollback.assert_not_called()

    def test_sin_filas_borradas_no_falla(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session:
            db = MagicMock()
            m_session.return_value = db
            db.execute.side_effect = [
                MagicMock(rowcount=0),
                MagicMock(rowcount=0),
            ]
            job_purgas_sesiones()
        db.commit.assert_called_once()

    def test_falla_hace_rollback_y_no_propaga(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session:
            db = MagicMock()
            m_session.return_value = db
            db.execute.side_effect = RuntimeError("db caída")

            job_purgas_sesiones()  # no debe lanzar

        db.rollback.assert_called_once()
        db.commit.assert_not_called()
        db.close.assert_called_once()


class TestJobReconciliacion(unittest.TestCase):
    """Tests del job de reconciliación diaria (M10.1 Bloque 1, D92)."""

    def test_llama_emparejar_antes_que_comparar(self) -> None:
        # El orden importa: comparar necesita que emparejar ya haya
        # corrido. Este test lo verifica con un grabador de orden.
        orden: list[str] = []

        def fake_emp(db):
            orden.append("emparejar")
            return MagicMock()

        def fake_cmp(db):
            orden.append("comparar")
            return MagicMock()

        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.calcular_emparejamientos", side_effect=fake_emp), \
             patch("scheduler.jobs.calcular_comparaciones", side_effect=fake_cmp):
            m_session.return_value = MagicMock()
            job_reconciliacion()

        self.assertEqual(orden, ["emparejar", "comparar"])

    def test_ambas_funciones_reciben_la_misma_sesion(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.calcular_emparejamientos") as m_emp, \
             patch("scheduler.jobs.calcular_comparaciones") as m_cmp:
            m_session.return_value = MagicMock()
            m_emp.return_value = MagicMock()
            m_cmp.return_value = MagicMock()

            job_reconciliacion()

        db = m_session.return_value
        m_emp.assert_called_once_with(db)
        m_cmp.assert_called_once_with(db)
        db.close.assert_called_once()

    def test_falla_emparejar_no_llama_comparar(self) -> None:
        # Si emparejar falla, no tiene sentido correr comparar contra
        # pares viejos. El job se corta sin llamar al segundo.
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.calcular_emparejamientos") as m_emp, \
             patch("scheduler.jobs.calcular_comparaciones") as m_cmp:
            m_session.return_value = MagicMock()
            m_emp.side_effect = RuntimeError("db caída")

            # No debe lanzar (el logger.exception lo absorbe):
            job_reconciliacion()

        m_emp.assert_called_once()
        m_cmp.assert_not_called()
        m_session.return_value.close.assert_called_once()

    def test_falla_comparar_no_propaga(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.calcular_emparejamientos") as m_emp, \
             patch("scheduler.jobs.calcular_comparaciones") as m_cmp:
            m_session.return_value = MagicMock()
            m_emp.return_value = MagicMock()
            m_cmp.side_effect = RuntimeError("db caída")

            # No debe lanzar:
            job_reconciliacion()

        m_emp.assert_called_once()
        m_cmp.assert_called_once()
        m_session.return_value.close.assert_called_once()


class TestJobReportes(unittest.TestCase):
    """Tests del job de reportes diarios (M10.1 Bloque 2, D73/D92)."""

    def test_llama_generar_reportes_con_defaults(self) -> None:
        """El job NO pasa `tipo` ni `alcance`: delega a
        `generar_reportes` con sus defaults, que recorre AMBOS tipos
        (estado_ciudad + auditoria_pronostico) y todos los alcances
        disponibles. Verificar que los kwargs quedan vacíos es equivalente
        a verificar 'genera todo'."""
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.generar_reportes") as m_gen:
            m_session.return_value = MagicMock()
            m_gen.return_value = _resumen_generacion_vacio()

            job_reportes()

        args, kwargs = m_gen.call_args
        self.assertEqual(args, (m_session.return_value,))
        self.assertEqual(kwargs, {})
        m_session.return_value.close.assert_called_once()

    def test_exito_loguea_y_cierra_sesion(self) -> None:
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.generar_reportes") as m_gen:
            m_session.return_value = MagicMock()
            m_resumen = MagicMock()
            m_resumen.totales = 3
            m_resumen.nuevos = 1
            m_resumen.reutilizados = 2
            m_resumen.por_origen = {"gemini": 1, "plantilla": 2}
            m_resumen.por_motivo_fallback = {"cuota_diaria": 1, "forzado": 1}
            rr1 = MagicMock(); rr1.llamadas_ia = 1
            rr2 = MagicMock(); rr2.llamadas_ia = 0
            rr3 = MagicMock(); rr3.llamadas_ia = 0
            m_resumen.reportes = [rr1, rr2, rr3]
            m_gen.return_value = m_resumen

            # No debe lanzar:
            job_reportes()

        m_gen.assert_called_once_with(m_session.return_value)
        m_session.return_value.close.assert_called_once()

    def test_suma_llamadas_ia_correctamente(self) -> None:
        """El log incluye la SUMA de `llamadas_ia` de todos los reportes.
        Es el número con el que se vigila D73 desde los logs, sin consultar
        la base."""
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.generar_reportes") as m_gen, \
             patch("scheduler.jobs.logger") as m_log:
            m_session.return_value = MagicMock()
            m_resumen = MagicMock()
            m_resumen.totales = 3
            m_resumen.nuevos = 3
            m_resumen.reutilizados = 0
            m_resumen.por_origen = {"gemini": 3}
            m_resumen.por_motivo_fallback = {}
            rr1 = MagicMock(); rr1.llamadas_ia = 2
            rr2 = MagicMock(); rr2.llamadas_ia = 1
            rr3 = MagicMock(); rr3.llamadas_ia = 3
            m_resumen.reportes = [rr1, rr2, rr3]
            m_gen.return_value = m_resumen

            job_reportes()

        # logger.info(fmt, *args): args[-1] es `llamadas_totales` = 2+1+3.
        args = m_log.info.call_args[0]
        self.assertEqual(args[-1], 6)

    def test_falla_no_propaga_y_cierra_sesion(self) -> None:
        """Si `generar_reportes` lanza (por un bug inesperado, no por el
        presupuesto agotado — ese caso lo maneja la propia función y NO
        lanza), el job lo absorbe y la sesión se cierra igual."""
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.generar_reportes") as m_gen:
            m_session.return_value = MagicMock()
            m_gen.side_effect = RuntimeError("Gemini caído de forma inesperada")

            # No debe lanzar: el scheduler no debe morir por esto.
            job_reportes()

        m_session.return_value.close.assert_called_once()

    def test_presupuesto_agotado_no_es_excepcion(self) -> None:
        """Con el presupuesto diario agotado, `generar_reportes` NO lanza:
        devuelve un `ResumenGeneracion` normal con `motivo_fallback`
        `cuota_diaria` y `llamadas_ia=0`. El job no necesita manejar ese
        caso por separado: se comporta como una corrida normal."""
        with patch("scheduler.jobs.SessionLocal") as m_session, \
             patch("scheduler.jobs.generar_reportes") as m_gen:
            m_session.return_value = MagicMock()
            m_resumen = MagicMock()
            m_resumen.totales = 2
            m_resumen.nuevos = 2
            m_resumen.reutilizados = 0
            m_resumen.por_origen = {"plantilla": 2}
            m_resumen.por_motivo_fallback = {"cuota_diaria": 2}
            rr1 = MagicMock(); rr1.llamadas_ia = 0
            rr2 = MagicMock(); rr2.llamadas_ia = 0
            m_resumen.reportes = [rr1, rr2]
            m_gen.return_value = m_resumen

            # No debe lanzar:
            job_reportes()

        m_session.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()