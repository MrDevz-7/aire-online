"""
Tests del validador de salida (M6 Bloque 5, sub-pieza 3).
Puros: sin red, sin base, sin clave. Construyen la ficha y el texto a mano.
Se corren con:
    cd engine
    python -m unittest analyzer.test_validador_texto -v
"""
from __future__ import annotations
import unittest
from analyzer.validador_texto import validar
def _ficha_minima() -> dict:
    """Ficha 'estado_ciudad' plausible y chica, con los números que el
    texto de ejemplo va a mencionar."""
    return {
        "tipo": "estado_ciudad",
        "alcance": "Bogotá",
        "fecha_referencia": "2026-10-04",
        "ciudades": [{
            "nombre": "Bogotá",
            "contaminantes": [
                {"contaminante": "pm25", "unidad": "µg/m³", "valor": 18.5,
                 "categoria_aqi": "Moderada", "n_estaciones": 12},
                {"contaminante": "pm10", "unidad": "µg/m³", "valor": 42.0,
                 "categoria_aqi": "Buena", "n_estaciones": 10},
            ],
            "estaciones_activas": 12,
            "fuentes_aportantes": ["iboca", "openaq", "aqicn"],
            "dato_mas_reciente_utc": "2026-10-04T15:00:00Z",
            "dato_mas_reciente_local": "2026-10-04 10:00 -05",
        }],
        "limitaciones": [
            "Cobertura real hoy: Bogotá y Valle de Aburrá.",
            "El pronóstico es de un modelo regional en grilla (~45 km).",
        ],
        "atribuciones": ["OpenAQ (openaq.org)", "AQICN/WAQI (aqicn.org)"],
    }
_TEXTO_TIPICO = (
    "Reporte del estado del aire para Bogotá, con fecha de referencia 2026-10-04. "
    "El material particulado PM2.5 registra 18.5 µg/m³, categoría Moderada, "
    "con 12 estaciones activas. El PM10 registra 42.0 µg/m³, categoría Buena. "
    "El dato más reciente corresponde a las 15:00 UTC (10:00 hora local -05). "
    "La información fue aportada por IBOCA, OpenAQ y AQICN."
)
class TestTextoValido(unittest.TestCase):
    def test_texto_tipico_pasa(self) -> None:
        self.assertIsNone(validar(_TEXTO_TIPICO, _ficha_minima()))
    def test_nombres_de_contaminantes_no_cuentan_como_numeros(self) -> None:
        """El '2.5' de PM2.5 y el '10' de PM10 no deben exigir que la ficha
        tenga esos valores: son nombres, no datos."""
        texto = "Se midió PM2.5, PM2,5, PM25, PM 2.5, PM10 y O3."
        self.assertIsNone(validar(texto, _ficha_minima()))
    def test_redondeo_admitido_hacia_abajo(self) -> None:
        """La ficha tiene 18.5: '18' es un redondeo válido."""
        self.assertIsNone(validar("El PM2.5 fue 18.", _ficha_minima()))
    def test_redondeo_admitido_hacia_arriba(self) -> None:
        """La ficha tiene 18.5: '19' es un redondeo válido."""
        self.assertIsNone(validar("El PM2.5 fue 19.", _ficha_minima()))
    def test_coma_decimal_admitida(self) -> None:
        """'18,5' (coma decimal en español) debe coincidir con 18.5."""
        self.assertIsNone(validar("El PM2.5 fue 18,5.", _ficha_minima()))
    def test_componentes_de_fecha_no_se_exigen_uno_por_uno(self) -> None:
        """Aunque la ficha no tenga '4' suelto, la fecha de referencia sí:
        el número '4' del texto es un componente de la fecha."""
        self.assertIsNone(validar("Fecha: 4 de octubre de 2026.", _ficha_minima()))
class TestTextoInvalidoPorLargo(unittest.TestCase):
    def test_texto_vacio_falla(self) -> None:
        self.assertEqual(validar("", _ficha_minima()), "validacion_texto")
        self.assertEqual(validar("   ", _ficha_minima()), "validacion_texto")
    def test_texto_demasiado_largo_falla(self) -> None:
        # REPORTE_MAX_CARACTERES_TEXTO por defecto: 4000.
        self.assertEqual(
            validar("a" * 5000, _ficha_minima()), "validacion_texto"
        )
class TestTerminosProhibidos(unittest.TestCase):
    def test_machine_learning_falla(self) -> None:
        self.assertEqual(
            validar("El sistema usa machine learning para predecir.",
                   _ficha_minima()),
            "validacion_texto",
        )
    def test_ml_variante_en_espanol_falla(self) -> None:
        self.assertEqual(
            validar("Un modelo de aprendizaje automático.", _ficha_minima()),
            "validacion_texto",
        )
    def test_prediccion_calibrada_falla(self) -> None:
        self.assertEqual(
            validar("Una predicción calibrada con datos.", _ficha_minima()),
            "validacion_texto",
        )
    def test_garantiza_falla(self) -> None:
        self.assertEqual(
            validar("El sistema garantiza precisión.", _ficha_minima()),
            "validacion_texto",
        )
    def test_con_certeza_falla(self) -> None:
        self.assertEqual(
            validar("Se puede afirmar con certeza.", _ficha_minima()),
            "validacion_texto",
        )
    def test_case_insensitive(self) -> None:
        self.assertEqual(
            validar("Usa MACHINE LEARNING.", _ficha_minima()),
            "validacion_texto",
        )
    def test_palabra_que_contiene_pero_no_es_el_termino_no_falla(self) -> None:
        """'garantizar' no debe matchear contra 'garantiza' (word boundary)."""
        # 'garantizar' es un verbo distinto, no está en la lista.
        # Este texto también tiene que pasar los otros chequeos.
        self.assertIsNone(
            validar("El PM2.5 fue 18.5.", _ficha_minima())
        )
class TestNumerosNoRastreables(unittest.TestCase):
    def test_numero_inventado_falla(self) -> None:
        """99 no está en la ficha (ni como valor ni como redondeo)."""
        self.assertEqual(
            validar("El PM2.5 fue 99.", _ficha_minima()),
            "validacion_numeros",
        )
    def test_numero_grande_inventado_falla(self) -> None:
        self.assertEqual(
            validar("La concentración fue 1234.", _ficha_minima()),
            "validacion_numeros",
        )
    def test_numero_chico_inventado_falla(self) -> None:
        # 7 no aparece en la ficha ni como redondeo de ningún valor.
        self.assertEqual(
            validar("El PM2.5 fue 7.", _ficha_minima()),
            "validacion_numeros",
        )
    def test_mixto_un_valido_y_uno_inventado_falla(self) -> None:
        """Alcanza con UN número no rastreable para rechazar el texto."""
        self.assertEqual(
            validar("El PM2.5 fue 18.5 y el PM10 fue 99.", _ficha_minima()),
            "validacion_numeros",
        )
class TestOrdenDeChequeos(unittest.TestCase):
    """Cuando hay varias fallas, se reporta la primera del orden
    largo -> términos -> números."""
    def test_largo_gana_sobre_terminos(self) -> None:
        texto = ("machine learning " * 300)  # largo y con término prohibido
        self.assertEqual(validar(texto, _ficha_minima()), "validacion_texto")
    def test_terminos_ganan_sobre_numeros(self) -> None:
        texto = "El sistema usa machine learning para calcular 99."
        # Aunque 99 no sea rastreable, primero se detecta el término.
        self.assertEqual(validar(texto, _ficha_minima()), "validacion_texto")
if __name__ == "__main__":
    unittest.main()