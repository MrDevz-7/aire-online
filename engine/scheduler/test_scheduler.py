"""
Tests del arranque/parada del scheduler (M10 Bloques 2–5 + M10.1 Bloques 1–2).

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
        self.assertNotIn("prueba_m10", ids)

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_job_ingesta_tiene_trigger_cron_cada_hora_al_minuto_5(self) -> None:
        sched_mod.iniciar_scheduler()
        job = sched_mod._scheduler.get_job("ingesta")
        self.assertIsNotNone(job)
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
        sched_mod.detener_scheduler()
        self.assertIsNone(sched_mod._scheduler)

    # ----- M10 Bloque 3: job de pronósticos -------------------------------

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_arranca_y_registra_job_pronosticos(self) -> None:
        sched_mod.iniciar_scheduler()
        ids = {j.id for j in sched_mod._scheduler.get_jobs()}
        self.assertIn("pronosticos", ids)
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

    # ----- M10 Bloque 4: job de auditoría ---------------------------------

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_arranca_y_registra_job_auditoria(self) -> None:
        sched_mod.iniciar_scheduler()
        ids = {j.id for j in sched_mod._scheduler.get_jobs()}
        self.assertIn("auditoria", ids)
        self.assertIn("ingesta", ids)
        self.assertIn("pronosticos", ids)

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_job_auditoria_tiene_trigger_cron_a_las_04_40(self) -> None:
        sched_mod.iniciar_scheduler()
        job = sched_mod._scheduler.get_job("auditoria")
        self.assertIsNotNone(job)
        campos = {f.name: str(f) for f in job.trigger.fields}
        self.assertEqual(campos["hour"], "4")
        self.assertEqual(campos["minute"], "40")

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_job_auditoria_tiene_misfire_grace_time_1h(self) -> None:
        sched_mod.iniciar_scheduler()
        job = sched_mod._scheduler.get_job("auditoria")
        self.assertEqual(job.misfire_grace_time, 3600)

    # ----- M10 Bloque 5: jobs de purga ------------------------------------

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_arranca_y_registra_jobs_purgas(self) -> None:
        sched_mod.iniciar_scheduler()
        ids = {j.id for j in sched_mod._scheduler.get_jobs()}
        self.assertIn("purgas", ids)
        self.assertIn("purgas_sesiones", ids)

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_jobs_purgas_tienen_trigger_cron_a_las_05_30(self) -> None:
        # M10.1: horario movido de 05:10 a 05:30 para dejar lugar a reportes.
        sched_mod.iniciar_scheduler()
        for job_id in ("purgas", "purgas_sesiones"):
            job = sched_mod._scheduler.get_job(job_id)
            self.assertIsNotNone(job, f"job {job_id} no encontrado")
            campos = {f.name: str(f) for f in job.trigger.fields}
            self.assertEqual(campos["hour"], "5", f"{job_id}: hour")
            self.assertEqual(campos["minute"], "30", f"{job_id}: minute")

    # ----- M10.1 Bloque 1: job de reconciliación --------------------------

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_arranca_y_registra_job_reconciliacion(self) -> None:
        sched_mod.iniciar_scheduler()
        ids = {j.id for j in sched_mod._scheduler.get_jobs()}
        self.assertIn("reconciliacion", ids)

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_job_reconciliacion_tiene_trigger_cron_a_las_03_40(self) -> None:
        sched_mod.iniciar_scheduler()
        job = sched_mod._scheduler.get_job("reconciliacion")
        self.assertIsNotNone(job)
        campos = {f.name: str(f) for f in job.trigger.fields}
        self.assertEqual(campos["hour"], "3")
        self.assertEqual(campos["minute"], "40")

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_job_reconciliacion_tiene_misfire_grace_time_1h(self) -> None:
        sched_mod.iniciar_scheduler()
        job = sched_mod._scheduler.get_job("reconciliacion")
        self.assertEqual(job.misfire_grace_time, 3600)

    # ----- M10.1 Bloque 2: job de reportes --------------------------------

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_arranca_y_registra_job_reportes(self) -> None:
        sched_mod.iniciar_scheduler()
        ids = {j.id for j in sched_mod._scheduler.get_jobs()}
        self.assertIn("reportes", ids)

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_job_reportes_tiene_trigger_cron_a_las_05_00(self) -> None:
        sched_mod.iniciar_scheduler()
        job = sched_mod._scheduler.get_job("reportes")
        self.assertIsNotNone(job)
        campos = {f.name: str(f) for f in job.trigger.fields}
        self.assertEqual(campos["hour"], "5")
        self.assertEqual(campos["minute"], "0")

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_job_reportes_tiene_misfire_grace_time_1h(self) -> None:
        sched_mod.iniciar_scheduler()
        job = sched_mod._scheduler.get_job("reportes")
        self.assertEqual(job.misfire_grace_time, 3600)

    # ----- Conteo global --------------------------------------------------

    @patch.object(settings, "SCHEDULER_ENABLED", True)
    def test_scheduler_registra_exactamente_7_jobs(self) -> None:
        # Red de seguridad: si alguien agrega un job sin querer, el test
        # lo detecta. Total tras M10.1 Bloque 2: 7 jobs (reconciliacion,
        # ingesta, pronosticos, auditoria, reportes, purgas,
        # purgas_sesiones).
        sched_mod.iniciar_scheduler()
        self.assertEqual(len(sched_mod._scheduler.get_jobs()), 7)


if __name__ == "__main__":
    unittest.main()