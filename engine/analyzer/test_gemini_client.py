"""
Tests del cliente Gemini (M6 Bloque 5, sub-pieza 2).
Todos los tests usan `httpx.MockTransport`: no tocan la red real ni
necesitan clave. Los dos fixtures reales se leen de `_testdata/`.
Se corren con:
    cd engine
    python -m unittest analyzer.test_gemini_client -v
"""
from __future__ import annotations
import json
import unittest
from pathlib import Path
from typing import Any, Callable
import httpx
from analyzer.gemini_client import (
    INSTRUCCION_SISTEMA,
    ClienteGemini,
)
_TESTDATA = Path(__file__).resolve().parent / "_testdata"
def _fixture(nombre: str) -> dict[str, Any]:
    return json.loads((_TESTDATA / nombre).read_text(encoding="utf-8"))
def _cuerpo_exito(parts: list[str], finish: str = "STOP") -> dict[str, Any]:
    return {
        "candidates": [{
            "content": {
                "parts": [{"text": t} for t in parts],
                "role": "model",
            },
            "finishReason": finish,
            "index": 0,
        }],
    }
def _cuerpo_error(status: str, code: int) -> dict[str, Any]:
    return {"error": {"status": status, "code": code, "message": status}}
class _Transporte:
    """Handler de `httpx.MockTransport` que devuelve respuestas en orden
    y cuenta cuántas veces fue llamado. Falla si se le pide más de lo que
    tiene: así un test detecta que el cliente hizo un request inesperado."""
    def __init__(self, respuestas: list[tuple[int, dict[str, Any]]]) -> None:
        self._respuestas = iter(respuestas)
        self.n_requests = 0
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.n_requests += 1
        try:
            status, body = next(self._respuestas)
        except StopIteration:
            raise AssertionError(
                f"El cliente hizo un request inesperado (#{self.n_requests})"
            )
        return httpx.Response(status_code=status, json=body)
def _cliente(
    transporte: _Transporte,
    *,
    api_keys: list[str] | None = None,
    modelos: list[str] | None = None,
    max_intentos: int | None = None,
) -> ClienteGemini:
    return ClienteGemini(
        api_keys=api_keys if api_keys is not None else ["clave-de-test"],
        modelos=modelos if modelos is not None else ["modelo-A"],
        max_intentos=max_intentos,
        espera_reintento_s=0.0,  # sin sleeps reales en tests
        transport=httpx.MockTransport(transporte.handler),
    )
class TestSinClave(unittest.TestCase):
    def test_sin_clave_no_llama_y_devuelve_motivo(self) -> None:
        transporte = _Transporte([])  # no debe consumirse
        with _cliente(transporte, api_keys=[]) as c:
            r = c.generar("sys", "user")
        self.assertFalse(r.exito)
        self.assertIsNone(r.texto)
        self.assertEqual(r.motivo_fallo, "sin_clave")
        self.assertEqual(r.llamadas_gastadas, 0)
        self.assertEqual(transporte.n_requests, 0)
class TestExito(unittest.TestCase):
    def test_concatenacion_de_parts(self) -> None:
        partes = ["El reporte dice hola, ", "el aire está limpio."]
        transporte = _Transporte([(200, _cuerpo_exito(partes))])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.texto, "El reporte dice hola, el aire está limpio.")
        self.assertEqual(r.modelo, "modelo-A")
        self.assertEqual(r.llamadas_gastadas, 1)
        self.assertIsNone(r.motivo_fallo)
        self.assertEqual(transporte.n_requests, 1)
    def test_un_solo_part(self) -> None:
        transporte = _Transporte([(200, _cuerpo_exito(["texto único"]))])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertEqual(r.texto, "texto único")
        self.assertTrue(r.exito)
    def test_fixture_real_estado_ciudad(self) -> None:
        """Usa el fixture real (dos `parts` separados por la API)."""
        fix = _fixture("gemini_exito_estado_ciudad.json")
        assert fix["status"] == 200
        partes = fix["body"]["candidates"][0]["content"]["parts"]
        texto_esperado = "".join(p["text"] for p in partes)
        transporte = _Transporte([(200, fix["body"])])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.texto, texto_esperado)
        self.assertEqual(r.motivo_fallo, None)
        self.assertEqual(r.llamadas_gastadas, 1)
class TestRespuestasInvalidas(unittest.TestCase):
    def test_finish_reason_truncado_devuelve_validacion_texto(self) -> None:
        transporte = _Transporte([
            (200, _cuerpo_exito(["corte a media pal", ], finish="MAX_TOKENS")),
        ])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "validacion_texto")
        self.assertEqual(r.llamadas_gastadas, 1)
    def test_sin_candidatos_devuelve_error_api(self) -> None:
        transporte = _Transporte([(200, {})])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "error_api")
    def test_candidato_sin_parts_devuelve_error_api(self) -> None:
        cuerpo = {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]}
        transporte = _Transporte([(200, cuerpo)])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "error_api")
class Test503ReintentoYCascada(unittest.TestCase):
    def test_503_reintento_exito(self) -> None:
        """El 503 recurrente que se observó con la clave real: primer
        intento 503, reintento al mismo modelo devuelve 200."""
        transporte = _Transporte([
            (503, _cuerpo_error("UNAVAILABLE", 503)),
            (200, _cuerpo_exito(["ok"])),
        ])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-A")
        self.assertEqual(r.llamadas_gastadas, 2)
        self.assertEqual(transporte.n_requests, 2)
    def test_503_doble_cascada_al_siguiente_modelo(self) -> None:
        """Dos 503 al primer modelo (intento + reintento), después cascada
        al siguiente, que responde 200."""
        transporte = _Transporte([
            (503, _cuerpo_error("UNAVAILABLE", 503)),
            (503, _cuerpo_error("UNAVAILABLE", 503)),
            (200, _cuerpo_exito(["ok desde el modelo B"])),
        ])
        with _cliente(transporte, modelos=["modelo-A", "modelo-B"]) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-B")
        self.assertEqual(r.llamadas_gastadas, 3)
        self.assertEqual(transporte.n_requests, 3)
    def test_resource_exhausted_sin_reintento_cascada_al_siguiente(self) -> None:
        """RESOURCE_EXHAUSTED no reintenta el mismo modelo: pasa al
        siguiente. Si ese también da 429, el resultado es http_429."""
        transporte = _Transporte([
            (429, _cuerpo_error("RESOURCE_EXHAUSTED", 429)),
            (429, _cuerpo_error("RESOURCE_EXHAUSTED", 429)),
        ])
        with _cliente(transporte, modelos=["modelo-A", "modelo-B"]) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "http_429")
        self.assertEqual(r.llamadas_gastadas, 2)
        self.assertEqual(transporte.n_requests, 2)
    def test_resource_exhausted_luego_exito_en_el_siguiente(self) -> None:
        transporte = _Transporte([
            (429, _cuerpo_error("RESOURCE_EXHAUSTED", 429)),
            (200, _cuerpo_exito(["ok"])),
        ])
        with _cliente(transporte, modelos=["modelo-A", "modelo-B"]) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-B")
        self.assertEqual(r.llamadas_gastadas, 2)
class TestNoRecuperable(unittest.TestCase):
    def test_unauthenticated_corta_sin_reintento_ni_cascada(self) -> None:
        """Fixture real de error de auth (401 UNAUTHENTICATED). Debe
        cortar la cascada inmediatamente: con dos modelos configurados,
        hace UN solo request y devuelve error_api."""
        fix = _fixture("gemini_error_auth.json")
        transporte = _Transporte([(fix["status"], fix["body"])])
        with _cliente(transporte, modelos=["modelo-A", "modelo-B"]) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "error_api")
        self.assertEqual(r.llamadas_gastadas, 1)
        self.assertEqual(transporte.n_requests, 1)
        self.assertEqual(r.modelo, "modelo-A")
class TestTimeout(unittest.TestCase):
    def test_timeout_reintenta_y_luego_falla_con_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("test timeout", request=request)
        with ClienteGemini(
            api_keys=["k"], modelos=["modelo-A"],
            espera_reintento_s=0.0,
            transport=httpx.MockTransport(handler),
        ) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "timeout")
        # 2 intentos al único modelo (intento + reintento); al agotarse
        # los modelos, devuelve timeout.
        self.assertEqual(r.llamadas_gastadas, 2)
class TestTopeDeIntentos(unittest.TestCase):
    def test_tope_por_reporte_corta_antes_de_agotar_modelos(self) -> None:
        """max_intentos=2: primer modelo con 503 en intento y reintento,
        tope alcanzado -> no se llega a probar el segundo modelo."""
        transporte = _Transporte([
            (503, _cuerpo_error("UNAVAILABLE", 503)),
            (503, _cuerpo_error("UNAVAILABLE", 503)),
            # No debería consumirse el 3ro:
            (200, _cuerpo_exito(["no debería llegar"])),
        ])
        with _cliente(
            transporte, modelos=["modelo-A", "modelo-B"], max_intentos=2,
        ) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "error_api")
        self.assertEqual(r.llamadas_gastadas, 2)
        self.assertEqual(transporte.n_requests, 2)
class TestCascadaPorNotFound(unittest.TestCase):
    def test_not_found_pasa_al_siguiente_modelo(self) -> None:
        """Si el modelo principal no está disponible para la clave
        (NOT_FOUND), la cascada salta al siguiente sin reintentar."""
        transporte = _Transporte([
            (404, _cuerpo_error("NOT_FOUND", 404)),
            (200, _cuerpo_exito(["ok"])),
        ])
        with _cliente(transporte, modelos=["modelo-A", "modelo-B"]) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-B")
        self.assertEqual(r.llamadas_gastadas, 2)
        self.assertEqual(transporte.n_requests, 2)
if __name__ == "__main__":
    unittest.main()