"""
Validador de la salida narrativa del LLM (M6, D70).
Antes de aceptar un texto redactado por Gemini, se verifica con código
normal que no invente nada. Tres chequeos, en este orden (del más barato
al más caro):

  1. Largo máximo (`REPORTE_MAX_CARACTERES_TEXTO`). Si se pasa, se rechaza.
  2. Términos prohibidos (afirmar machine learning, garantías o certezas).
  3. Números rastreables: cada número del texto debe poder encontrarse en
     la ficha, admitiendo redondeo y coma/punto como separador decimal.

Devuelve `None` si el texto pasa, o uno de los valores del CHECK de
`reportes.motivo_fallback`:
  - "validacion_texto": vacío, muy largo, o con término prohibido.
  - "validacion_numeros": algún número no rastreable a la ficha.

Sobre la extracción de números: los nombres de contaminantes ("PM2.5",
"PM10", "O3", "NO2", "SO2", "CO", "AQI") se enmascaran ANTES de buscar
dígitos, porque contienen cifras que no son datos. Sin eso, un texto
correcto que mencione "PM2.5" se rechazaría por un falso positivo.
"""
from __future__ import annotations
import math
import re
from typing import Any
from database.config import settings
# Nombres de contaminantes que hay que enmascarar antes de extraer números.
# Incluye variantes con punto y coma ("PM2.5" / "PM2,5"), sin separador
# ("PM25") y con espacio ("PM 2.5").
_CONTAMINANTES_RE = re.compile(
    r"\b(?:pm\s*2[.,]?5|pm\s*25|pm\s*10|pm\s*1|o3|no2|so2|co|aqi)\b",
    re.IGNORECASE,
)
# Números del texto: signo opcional (-), dígitos, decimal opcional con
# . o , . El lookbehind `(?<![\d.])` evita capturar el guión de un rango
# ("3-5 días") como signo negativo del segundo número.
_NUMERO_RE = re.compile(r"(?<![\d.])-?\d+(?:[.,]\d+)?")
# Términos prohibidos (case-insensitive). Cubre dos familias: afirmar
# machine learning o IA como motor del sistema, y prometer garantías o
# certezas que el proyecto no puede sostener (D2, D33, D70).
_TERMINOS_PROHIBIDOS: tuple[str, ...] = (
    # Machine learning / IA
    "machine learning",
    "aprendizaje automático",
    "aprendizaje automatico",
    "aprendizaje de máquina",
    "aprendizaje de maquina",
    "aprendizaje profundo",
    "deep learning",
    "red neuronal",
    "redes neuronales",
    "predicción calibrada",
    "prediccion calibrada",
    "predicciones calibradas",
    "modelo entrenado",
    "inteligencia artificial",
    # Garantías y certezas
    "garantiza",
    "garantizado",
    "garantizada",
    "garantizamos",
    "con certeza",
    "con total certeza",
    "con absoluta certeza",
    "certeza absoluta",
    "sin duda",
    "sin lugar a dudas",
    "asegura que",
    "aseguramos",
    "infalible",
)
_TERMINOS_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _TERMINOS_PROHIBIDOS) + r")\b",
    re.IGNORECASE,
)
# Tolerancia de comparación de números: media milésima. Captura redondeos
# a 3 decimales sin aceptar diferencias reales (por ejemplo 18.5 vs 18.6).
_TOLERANCIA = 0.0005
def validar(texto: str, ficha: dict[str, Any]) -> str | None:
    """Devuelve None si el texto pasa los tres chequeos, o el motivo de
    falla (un valor del CHECK de reportes.motivo_fallback)."""
    if not texto or not texto.strip():
        return "validacion_texto"
    if len(texto) > settings.REPORTE_MAX_CARACTERES_TEXTO:
        return "validacion_texto"
    if _TERMINOS_RE.search(texto):
        return "validacion_texto"
    if not _numeros_son_rastreables(texto, ficha):
        return "validacion_numeros"
    return None
def _normalizar_numero(token: str) -> float | None:
    """'18,5' o '18.5' -> 18.5. None si no se puede parsear."""
    try:
        return float(token.replace(",", "."))
    except ValueError:
        return None
def _valores_de_la_ficha(ficha: Any) -> set[float]:
    """Recorre la ficha (dict/list/str/num) y devuelve todos los números
    que aparecen en ella, incluyendo los embebidos en strings (por
    ejemplo dentro de 'fecha_referencia': '2026-10-04' -> {2026, 10, 4})."""
    salida: set[float] = set()
    _acumular(ficha, salida)
    return salida
def _acumular(obj: Any, salida: set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        salida.add(float(obj))
    elif isinstance(obj, str):
        for token in _NUMERO_RE.findall(obj):
            n = _normalizar_numero(token)
            if n is not None:
                salida.add(n)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _acumular(k, salida)
            _acumular(v, salida)
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            _acumular(x, salida)
def _permitidos_con_redondeos(valores: set[float]) -> set[float]:
    """Amplía el conjunto con redondeos hacia arriba, hacia abajo y
    bancario a 0, 1, 2 y 3 decimales. Un texto que redondea un valor de
    la ficha (18.5 -> 18 o 19) sigue siendo correcto."""
    salida: set[float] = set()
    for v in valores:
        salida.add(v)
        for d in (0, 1, 2, 3):
            factor = 10 ** d
            salida.add(round(v, d))
            salida.add(math.floor(v * factor) / factor)
            salida.add(math.ceil(v * factor) / factor)
    return salida
def _numeros_del_texto(texto: str) -> list[float]:
    """Números del texto, tras enmascarar los nombres de contaminantes."""
    limpio = _CONTAMINANTES_RE.sub("X", texto)
    resultado: list[float] = []
    for token in _NUMERO_RE.findall(limpio):
        n = _normalizar_numero(token)
        if n is not None:
            resultado.append(n)
    return resultado
def _es_rastreable(n: float, permitidos: set[float]) -> bool:
    for candidato in permitidos:
        if math.isclose(n, candidato, abs_tol=_TOLERANCIA):
            return True
    return False
def _numeros_son_rastreables(texto: str, ficha: dict[str, Any]) -> bool:
    permitidos = _permitidos_con_redondeos(_valores_de_la_ficha(ficha))
    for n in _numeros_del_texto(texto):
        if not _es_rastreable(n, permitidos):
            return False
    return True