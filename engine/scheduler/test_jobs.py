"""
Tests de los jobs del scheduler (M10 Bloques 2 y 3).

Puros: mockean las funciones de servicio y la sesión de base. No arrancan
el scheduler real, no tocan red, no tocan Postgres.

Se corren con:
    cd engine
    python -m unittest scheduler.test_jobs -v
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from scheduler.jobs import (
    _ejecutar_una_fuente,
    _fuentes_ingesta,
    ejecutar_ingesta,
    job_ingesta,
    job_pronosticos,
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


if __name__ == "__main__":
    unittest.main()