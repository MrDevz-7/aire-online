"""
Tests de los endpoints de reportes (M6 Bloque 6).
Usan `TestClient` de FastAPI contra la app real, con la base local. Para
no tocar filas reales, todo `alcance` de prueba lleva el prefijo
`TEST_M6_API_` y el setUp/tearDown lo borra.
Para no llamar a Gemini en los tests, el POST siempre va con
`forzar_plantilla=true`. Además el `alcance` de prueba no matchea ninguna
ciudad real, así que la ficha sale vacía y la plantilla devuelve el aviso
"no hay datos" — verificado en `test_post_forzar_plantilla_*`.
M8 (D79) agregó el `InternalTokenMiddleware`: si `INTERNAL_API_TOKEN`
está configurado en el `.env`, las rutas `/internal/*` exigen la
cabecera `X-Internal-Token`. Este archivo la manda en todos los POST
que van a `/internal/*`; los GET a `/api/*` no la necesitan.
Se corren con:
    cd engine
    python -m unittest api.test_main -v
"""
from __future__ import annotations
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from api.main import app
from database.config import settings
from database.models import Reporte
from database.session import SessionLocal
PREFIJO_ALCANCE = "TEST_M6_API_"
def _limpiar(db) -> None:
    db.execute(delete(Reporte).where(Reporte.alcance.like(f"{PREFIJO_ALCANCE}%")))
    db.commit()
class TestReportesEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.db = SessionLocal()
        _limpiar(self.db)
        # M8 (D79): el middleware exige X-Internal-Token si está
        # configurado. Si está vacío (dev local sin token), el
        # middleware deja pasar; igual mandamos la cabecera con el valor
        # que tenga, para no duplicar lógica entre los dos casos.
        self.headers_internal = {"X-Internal-Token": settings.INTERNAL_API_TOKEN}
    def tearDown(self) -> None:
        _limpiar(self.db)
        self.db.close()
    def _alcance(self, sufijo: str = "1") -> str:
        return f"{PREFIJO_ALCANCE}{sufijo}"
    def _generar_plantilla(self, tipo: str, alcance: str):
        return self.client.post(
            "/internal/reportes/generar",
            params={
                "tipo": tipo,
                "alcance": alcance,
                "forzar_plantilla": "true",
            },
            headers=self.headers_internal,
        )
    # ------------------------------------------------------------------
    # POST /internal/reportes/generar
    # ------------------------------------------------------------------
    def test_post_forzar_plantilla_persiste_con_llamadas_cero(self) -> None:
        r = self._generar_plantilla("estado_ciudad", self._alcance("a"))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["totales"], 1)
        self.assertEqual(body["nuevos"], 1)
        self.assertEqual(body["reutilizados"], 0)
        self.assertEqual(body["por_origen"], {"plantilla": 1})
        self.assertEqual(body["por_motivo_fallback"], {"forzado": 1})
        detalle = body["reportes"][0]
        self.assertEqual(detalle["tipo"], "estado_ciudad")
        self.assertEqual(detalle["alcance"], self._alcance("a"))
        self.assertEqual(detalle["origen_texto"], "plantilla")
        self.assertEqual(detalle["motivo_fallback"], "forzado")
        self.assertEqual(detalle["llamadas_ia"], 0)
        self.assertTrue(detalle["nuevo"])
    def test_post_segunda_llamada_marca_reutilizado(self) -> None:
        r1 = self._generar_plantilla("estado_ciudad", self._alcance("b"))
        r2 = self._generar_plantilla("estado_ciudad", self._alcance("b"))
        self.assertEqual(r1.json()["nuevos"], 1)
        self.assertEqual(r2.json()["nuevos"], 0)
        self.assertEqual(r2.json()["reutilizados"], 1)
    def test_post_tipo_invalido_devuelve_400(self) -> None:
        r = self.client.post(
            "/internal/reportes/generar",
            params={"tipo": "no_existe", "alcance": self._alcance("c")},
            headers=self.headers_internal,
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("no_existe", r.json()["detail"])
    # ------------------------------------------------------------------
    # GET /api/reportes/{tipo}
    # ------------------------------------------------------------------
    def test_get_404_si_no_hay(self) -> None:
        r = self.client.get(
            "/api/reportes/estado_ciudad",
            params={"alcance": self._alcance("no_existe")},
        )
        self.assertEqual(r.status_code, 404)
        self.assertIn("No hay reportes", r.json()["detail"])
    def test_get_devuelve_ultimo_report_persistido(self) -> None:
        # Sembramos un reporte con forzar_plantilla (no llama a Gemini).
        self._generar_plantilla("estado_ciudad", self._alcance("d"))
        r = self.client.get(
            "/api/reportes/estado_ciudad",
            params={"alcance": self._alcance("d")},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["tipo"], "estado_ciudad")
        self.assertEqual(body["alcance"], self._alcance("d"))
        self.assertEqual(body["origen_texto"], "plantilla")
        self.assertEqual(body["motivo_fallback"], "forzado")
        self.assertEqual(body["llamadas_ia"], 0)
        self.assertIsNone(body["modelo"])
        # La ficha va completa y el texto no está vacío.
        self.assertIn("datos_entrada", body)
        self.assertIn("fecha_referencia", body["datos_entrada"])
        self.assertTrue(body["texto"].strip())
if __name__ == "__main__":
    unittest.main()