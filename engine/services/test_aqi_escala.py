"""
Tests de services/aqi_escala.py (M6): categoria_aqi y smoke de convertir_a_aqi.

    cd engine
    python -m unittest services.test_aqi_escala -v

Funciones puras, sin red ni base.
"""
from __future__ import annotations

import unittest

from services.aqi_escala import categoria_aqi, convertir_a_aqi


class TestCategoriaAqi(unittest.TestCase):
    def test_buena_en_el_piso(self) -> None:
        self.assertEqual(categoria_aqi(0), "Buena")

    def test_buena_en_el_techo(self) -> None:
        self.assertEqual(categoria_aqi(50), "Buena")

    def test_moderada_en_el_piso(self) -> None:
        self.assertEqual(categoria_aqi(51), "Moderada")

    def test_moderada_en_el_techo(self) -> None:
        self.assertEqual(categoria_aqi(100), "Moderada")

    def test_limitrofes(self) -> None:
        self.assertEqual(categoria_aqi(150), "Dañina para grupos sensibles")
        self.assertEqual(categoria_aqi(151), "Dañina")
        self.assertEqual(categoria_aqi(200), "Dañina")
        self.assertEqual(categoria_aqi(201), "Muy dañina")
        self.assertEqual(categoria_aqi(300), "Muy dañina")
        self.assertEqual(categoria_aqi(301), "Peligrosa")

    def test_peligrosa_en_el_techo(self) -> None:
        self.assertEqual(categoria_aqi(500), "Peligrosa")

    def test_fuera_de_rango_devuelve_none(self) -> None:
        self.assertIsNone(categoria_aqi(-0.1))
        self.assertIsNone(categoria_aqi(-100))
        self.assertIsNone(categoria_aqi(500.1))
        self.assertIsNone(categoria_aqi(9999))

    def test_valores_intermedios_conocidos(self) -> None:
        self.assertEqual(categoria_aqi(25), "Buena")
        self.assertEqual(categoria_aqi(75), "Moderada")
        self.assertEqual(categoria_aqi(125), "Dañina para grupos sensibles")
        self.assertEqual(categoria_aqi(175), "Dañina")
        self.assertEqual(categoria_aqi(250), "Muy dañina")
        self.assertEqual(categoria_aqi(400), "Peligrosa")


class TestConvertirAaAqiSmoke(unittest.TestCase):
    """Smoke mínimo: confirma que agregar categoria_aqi no rompió nada."""

    def test_pm25_en_breakpoint_conocido(self) -> None:
        resultado = convertir_a_aqi("pm25", 35.4, "µg/m³")
        self.assertIsNotNone(resultado)
        self.assertAlmostEqual(resultado, 100.0, places=4)

    def test_pm25_en_el_piso(self) -> None:
        resultado = convertir_a_aqi("pm25", 0.0, "µg/m³")
        self.assertIsNotNone(resultado)
        self.assertAlmostEqual(resultado, 0.0, places=4)

    def test_negativo_devuelve_none(self) -> None:
        self.assertIsNone(convertir_a_aqi("pm25", -1.0, "µg/m³"))

    def test_unidad_no_reconocida_devuelve_none(self) -> None:
        self.assertIsNone(convertir_a_aqi("pm25", 35.4, "furlongs"))

    def test_pm1_no_es_convertible(self) -> None:
        self.assertIsNone(convertir_a_aqi("pm1", 10.0, "µg/m³"))

    def test_aqi_como_contaminante_no_es_convertible(self) -> None:
        self.assertIsNone(convertir_a_aqi("aqi", 50.0, "AQI"))


if __name__ == "__main__":
    unittest.main()