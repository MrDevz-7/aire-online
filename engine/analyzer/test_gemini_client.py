"""
Tests del cliente Gemini (M6 Bloque 5 sub-pieza 2 + fixes del Bloque 6
+ deadline de M11.1).

Sin red real: `httpx.MockTransport`. Los fixtures reales se leen de
`_testdata/`.

    cd engine
    python -m unittest analyzer.test_gemini_client -v
"""
from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from typing import Any

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
            "content": {"parts": [{"text": t} for t in parts], "role": "model"},
            "finishReason": finish,
            "index": 0,
        }],
    }

def _cuerpo_error(status: str, code: int) -> dict[str, Any]:
    return {"error": {"status": status, "code": code, "message": status}}

class _Transporte:
    """MockTransport que devuelve respuestas en orden y cuenta requests.
    Falla si se le pide más de lo esperado (detecta requests inesperados)."""

    def __init__(self, respuestas: list[tuple[int, dict[str, Any]]]) -> None:
        self._respuestas = iter(respuestas)
        self.n_requests = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.n_requests += 1
        try:
            status, body = next(self._respuestas)
        except StopIteration:
            raise AssertionError(
                f"Request inesperado (#{self.n_requests})"
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
        espera_reintento_s=0.0,
        transport=httpx.MockTransport(transporte.handler),
    )

class TestSinClave(unittest.TestCase):
    def test_sin_clave_no_llama_y_devuelve_motivo(self) -> None:
        transporte = _Transporte([])
        with _cliente(transporte, api_keys=[]) as c:
            r = c.generar("sys", "user")
        self.assertFalse(r.exito)
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

    def test_un_solo_part(self) -> None:
        transporte = _Transporte([(200, _cuerpo_exito(["texto único"]))])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertEqual(r.texto, "texto único")
        self.assertTrue(r.exito)

    def test_fixture_real_estado_ciudad(self) -> None:
        fix = _fixture("gemini_exito_estado_ciudad.json")
        partes = fix["body"]["candidates"][0]["content"]["parts"]
        texto_esperado = "".join(p["text"] for p in partes)
        transporte = _Transporte([(200, fix["body"])])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.texto, texto_esperado)
        self.assertIsNone(r.motivo_fallo)
        self.assertEqual(r.llamadas_gastadas, 1)

class TestRespuestasInvalidas(unittest.TestCase):
    def test_finish_reason_truncado_devuelve_validacion_texto(self) -> None:
        transporte = _Transporte([
            (200, _cuerpo_exito(["corte"], finish="MAX_TOKENS")),
        ])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "validacion_texto")

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
    def test_503_reintento_exito_con_una_sola_key(self) -> None:
        transporte = _Transporte([
            (503, _cuerpo_error("UNAVAILABLE", 503)),
            (200, _cuerpo_exito(["ok"])),
        ])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-A")
        self.assertEqual(r.llamadas_gastadas, 2)

    def test_503_doble_cascada_al_siguiente_modelo(self) -> None:
        transporte = _Transporte([
            (503, _cuerpo_error("UNAVAILABLE", 503)),
            (503, _cuerpo_error("UNAVAILABLE", 503)),
            (200, _cuerpo_exito(["ok modelo B"])),
        ])
        with _cliente(transporte, modelos=["modelo-A", "modelo-B"]) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-B")
        self.assertEqual(r.llamadas_gastadas, 3)

    def test_429_con_1_key_no_reintenta_pasa_al_siguiente_modelo(self) -> None:
        """429 con 1 sola key: la key está agotada, no se reintenta.
        Cascada directa al siguiente modelo, que también da 429."""
        transporte = _Transporte([
            (429, _cuerpo_error("RESOURCE_EXHAUSTED", 429)),  # modelo-A
            (429, _cuerpo_error("RESOURCE_EXHAUSTED", 429)),  # modelo-B
        ])
        with _cliente(transporte, modelos=["modelo-A", "modelo-B"]) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "http_429")
        self.assertEqual(r.llamadas_gastadas, 2)
        self.assertEqual(transporte.n_requests, 2)

    def test_429_con_1_key_luego_exito_en_el_siguiente_modelo(self) -> None:
        """429 con 1 sola key: sin reintento, cascada al modelo-B, éxito."""
        transporte = _Transporte([
            (429, _cuerpo_error("RESOURCE_EXHAUSTED", 429)),  # modelo-A
            (200, _cuerpo_exito(["ok"])),                     # modelo-B
        ])
        with _cliente(transporte, modelos=["modelo-A", "modelo-B"]) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-B")
        self.assertEqual(r.llamadas_gastadas, 2)
        self.assertEqual(transporte.n_requests, 2)

class TestNoRecuperable(unittest.TestCase):
    def test_unauthenticated_con_una_sola_key_corta(self) -> None:
        """1 key + 401: se prueba 2 veces (reintento). Ambos fallan."""
        fix = _fixture("gemini_error_auth.json")
        transporte = _Transporte([
            (fix["status"], fix["body"]),
            (fix["status"], fix["body"]),
        ])
        with _cliente(transporte, modelos=["modelo-A"]) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "error_api")
        self.assertEqual(r.llamadas_gastadas, 2)

class TestTimeout(unittest.TestCase):
    def test_timeout_reintenta_y_luego_falla_con_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("test timeout", request=request)
        with ClienteGemini(
            api_keys=["k"], modelos=["modelo-A"], espera_reintento_s=0.0,
            transport=httpx.MockTransport(handler),
        ) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "timeout")
        self.assertEqual(r.llamadas_gastadas, 2)

class TestTopeDeIntentos(unittest.TestCase):
    def test_tope_por_reporte_corta_antes_de_agotar_modelos(self) -> None:
        transporte = _Transporte([
            (503, _cuerpo_error("UNAVAILABLE", 503)),
            (503, _cuerpo_error("UNAVAILABLE", 503)),
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
        transporte = _Transporte([
            (404, _cuerpo_error("NOT_FOUND", 404)),
            (200, _cuerpo_exito(["ok"])),
        ])
        with _cliente(transporte, modelos=["modelo-A", "modelo-B"]) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-B")
        self.assertEqual(r.llamadas_gastadas, 2)

class TestRotacionDeKeys(unittest.TestCase):
    def test_429_rota_a_la_siguiente_key(self) -> None:
        transporte = _Transporte([
            (429, _cuerpo_error("RESOURCE_EXHAUSTED", 429)),
            (200, _cuerpo_exito(["ok con la segunda key"])),
        ])
        with _cliente(
            transporte,
            api_keys=["key-agotada", "key-fresca"],
            modelos=["modelo-A"],
        ) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-A")
        self.assertEqual(r.llamadas_gastadas, 2)

    def test_unauthenticated_rota_a_la_siguiente_key(self) -> None:
        transporte = _Transporte([
            (401, _cuerpo_error("UNAUTHENTICATED", 401)),
            (200, _cuerpo_exito(["ok con la segunda key"])),
        ])
        with _cliente(
            transporte,
            api_keys=["key-mala", "key-buena"],
            modelos=["modelo-A"],
        ) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-A")
        self.assertEqual(r.llamadas_gastadas, 2)

    def test_503_rota_a_la_siguiente_key(self) -> None:
        transporte = _Transporte([
            (503, _cuerpo_error("UNAVAILABLE", 503)),
            (200, _cuerpo_exito(["ok con la segunda key"])),
        ])
        with _cliente(
            transporte,
            api_keys=["key-1", "key-2"],
            modelos=["modelo-A"],
        ) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-A")
        self.assertEqual(r.llamadas_gastadas, 2)

    def test_503_en_todas_las_keys_pasa_al_siguiente_modelo(self) -> None:
        transporte = _Transporte([
            (503, _cuerpo_error("UNAVAILABLE", 503)),  # key-1, modelo-A
            (503, _cuerpo_error("UNAVAILABLE", 503)),  # key-2, modelo-A
            (200, _cuerpo_exito(["ok con modelo-B"])),
        ])
        with _cliente(
            transporte,
            api_keys=["key-1", "key-2"],
            modelos=["modelo-A", "modelo-B"],
        ) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.modelo, "modelo-B")
        self.assertEqual(r.llamadas_gastadas, 3)

# ---------------------------------------------------------------------------
# M11.1 (D98): presupuesto de tiempo con deadline
# ---------------------------------------------------------------------------

class TestDeadline(unittest.TestCase):
    """El `deadline` corta la cascada sin tocar la red. Un deadline vencido
    equivale a "no hay más tiempo para este reporte": se devuelve
    `motivo_fallo='timeout'` con `llamadas_gastadas=0` y el transporte
    nunca recibe una request."""

    def test_deadline_vencido_no_intenta_ningun_llamado(self) -> None:
        """Deadline en el pasado: la cascada corta ANTES del primer intento.
        El MockTransport explota si algo intenta salir a la red: es la
        prueba de que el corte es real, no aspiracional."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError(
                "el deadline vencido no debería dejar llegar ninguna request a Gemini"
            )
        cliente = ClienteGemini(
            api_keys=["k"],
            modelos=["modelo-A"],
            espera_reintento_s=0.0,
            transport=httpx.MockTransport(handler),
        )
        deadline_pasado = time.monotonic() - 1.0
        with cliente as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}", deadline=deadline_pasado)
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "timeout")
        self.assertEqual(r.llamadas_gastadas, 0)

    def test_deadline_lejano_no_afecta_el_comportamiento(self) -> None:
        """Deadline en el futuro: misma cascada de siempre (sin regresión)."""
        transporte = _Transporte([(200, _cuerpo_exito(["ok"]))])
        deadline_futuro = time.monotonic() + 3600.0
        with _cliente(transporte) as c:
            r = c.generar(
                INSTRUCCION_SISTEMA, "{}", deadline=deadline_futuro,
            )
        self.assertTrue(r.exito)
        self.assertEqual(r.texto, "ok")
        self.assertEqual(r.llamadas_gastadas, 1)
        self.assertIsNone(r.motivo_fallo)

    def test_sin_deadline_el_comportamiento_es_el_previo(self) -> None:
        """`deadline=None` (default): compatibilidad total con el código
        que ya llamaba a `generar` sin pasar deadline."""
        transporte = _Transporte([(200, _cuerpo_exito(["ok"]))])
        with _cliente(transporte) as c:
            r = c.generar(INSTRUCCION_SISTEMA, "{}")
        self.assertTrue(r.exito)
        self.assertEqual(r.texto, "ok")
        self.assertEqual(r.llamadas_gastadas, 1)

    def test_deadline_prevalece_sobre_el_motivo_del_ultimo_fallo(self) -> None:
        """Cuando el deadline vence después de un fallo interno, el motivo
        que se reporta es 'timeout' (describe lo que REALMENTE pasó: nos
        quedamos sin tiempo), no el motivo del fallo previo (por ejemplo
        'error_api' de un 503)."""
        transporte = _Transporte([
            (503, _cuerpo_error("UNAVAILABLE", 503)),
        ])
        # deadline en el pasado desde el arranque: el primer chequeo del
        # while lo ve vencido y corta antes de cualquier request.
        with _cliente(transporte) as c:
            r = c.generar(
                INSTRUCCION_SISTEMA, "{}",
                deadline=time.monotonic() - 1.0,
            )
        self.assertFalse(r.exito)
        self.assertEqual(r.motivo_fallo, "timeout")
        # El transporte no recibió ninguna request: el corte fue real.
        self.assertEqual(transporte.n_requests, 0)

if __name__ == "__main__":
    unittest.main()