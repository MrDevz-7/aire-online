"""
Tests del arranque/parada del scheduler (M10 Bloques 2 y 3).

Verifican la guarda `SCHEDULER_ENABLED` y el registro de los jobs.
No tocan red ni base.

Se corren con:
    cd engine
    python -m unittest scheduler.test_scheduler -v
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from database.config import settings
from scheduler import scheduler as sched_mod


class TestSchedulerDeshabilitado(unittest.TestCase):
    def setUp(self) -> None:
        # Estado limpio: cualquier test previo que haya arrancado el
        # scheduler no debe contaminar este.
        sched_mod._scheduler = None

    def tearDown(self) -> None:
        sched_mod._scheduler = None

    @patch.object(settings, "SCHEDULER_ENABLED", False)
    def test_iniciar_no_arranca_y_no_registra_jobs(self) -> None:
        sched_mod.iniciar_scheduler()
        self.assertIsNone(sched_mod._scheduler)

    @patch.object(settings, "SCHEDULER_ENABLED", False)
    def test_iniciar_es_idempotente(self) -> None:
        sched_mod.iniciar_scheduler()
        sched_mod.iniciar_scheduler()
        self.assertIsNone(sched_mod._scheduler)


class TestSchedulerHabilitado(unittest.TestCase):
    def setUp(self) -> None:
        sched_mod._scheduler = None

    def tearDown(self) -> None:
        sched_mod.detener_scheduler()

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_arranca_y_registra_job_ingesta(self) -> None:
        sched_mod.iniciar_scheduler()
        self.assertIsNotNone(sched_mod._scheduler)
        self.assertTrue(sched_mod._scheduler.running)
        ids = {j.id for j in sched_mod._scheduler.get_jobs()}
        self.assertIn("ingesta", ids)
        # El job de prueba del Bloque 1 ya no existe.
        self.assertNotIn("prueba_m10", ids)

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_job_ingesta_tiene_trigger_cron_cada_hora_al_minuto_5(self) -> None:
        sched_mod.iniciar_scheduler()
        job = sched_mod._scheduler.get_job("ingesta")
        self.assertIsNotNone(job)
        # El trigger es un CronTrigger con minute=5 y hour=*.
        # Los campos del trigger de APScheduler exponen `.fields` con
        # las expresiones originales.
        campos = {f.name: str(f) for f in job.trigger.fields}
        self.assertEqual(campos["hour"], "*")
        self.assertEqual(campos["minute"], "5")

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_job_ingesta_tiene_max_instances_1(self) -> None:
        sched_mod.iniciar_scheduler()
        job = sched_mod._scheduler.get_job("ingesta")
        self.assertEqual(job.max_instances, 1)

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_arrancar_dos_veces_no_duplica_el_job(self) -> None:
        sched_mod.iniciar_scheduler()
        sched_mod.iniciar_scheduler()
        ids = [j.id for j in sched_mod._scheduler.get_jobs()]
        self.assertEqual(ids.count("ingesta"), 1)

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_detener_apaga_el_scheduler(self) -> None:
        sched_mod.iniciar_scheduler()
        sched_mod.detener_scheduler()
        self.assertIsNone(sched_mod._scheduler)

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_detener_sin_arrancar_no_falla(self) -> None:
        # Idempotente: no debe lanzar.
        sched_mod.detener_scheduler()
        self.assertIsNone(sched_mod._scheduler)

    # ----- Bloque 3: job de pronósticos -----------------------------------

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_arranca_y_registra_job_pronosticos(self) -> None:
        sched_mod.iniciar_scheduler()
        ids = {j.id for j in sched_mod._scheduler.get_jobs()}
        self.assertIn("pronosticos", ids)
        # El job del Bloque 2 sigue registrado también:
        self.assertIn("ingesta", ids)

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_job_pronosticos_tiene_trigger_cron_a_las_04_10(self) -> None:
        sched_mod.iniciar_scheduler()
        job = sched_mod._scheduler.get_job("pronosticos")
        self.assertIsNotNone(job)
        campos = {f.name: str(f) for f in job.trigger.fields}
        self.assertEqual(campos["hour"], "4")
        self.assertEqual(campos["minute"], "10")

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_job_pronosticos_tiene_misfire_grace_time_1h(self) -> None:
        sched_mod.iniciar_scheduler()
        job = sched_mod._scheduler.get_job("pronosticos")
        self.assertEqual(job.misfire_grace_time, 3600)

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_scheduler_registra_exactamente_2_jobs(self) -> None:
        # Red de seguridad: si alguien agrega un job sin querer en este
        # bloque, el test lo detecta. Los bloques 4 y 5 van a subir este
        # número (auditoría → 3, purgas → 4 o 5).
        sched_mod.iniciar_scheduler()
        self.assertEqual(len(sched_mod._scheduler.get_jobs()), 2)


if __name__ == "__main__":
    unittest.main()