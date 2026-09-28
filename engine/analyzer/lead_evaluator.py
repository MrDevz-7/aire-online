"""
Parseo y validación de la respuesta de Gemini para la evaluación de un
lead. Gemini normalmente respeta "responde solo JSON", pero en la
práctica a veces lo envuelve en bloques markdown (```json ... ```) o
agrega una frase antes/después. Este módulo es tolerante a eso.
"""
from __future__ import annotations

import json
import re

# Rango de longitud razonable para cada argumento de venta: ni vacío ni
# un párrafo entero (si Gemini se desvía mucho, mejor truncar que fallar).
MAX_SALES_ARGUMENTS = 5
MAX_ARGUMENT_LENGTH = 300
MAX_SERVICE_LENGTH = 255


class GeminiResponseParseError(ValueError):
    """La respuesta de Gemini no se pudo parsear o no cumple el esquema
    esperado. Hereda de ValueError para que el endpoint la capture junto
    con otros errores de validación."""


def _extract_json_block(raw_text: str) -> str:
    """Extrae el primer bloque {...} del texto, sin importar si viene
    envuelto en markdown (```json ... ```) o con texto alrededor."""
    # Caso 1: viene en un bloque de código markdown.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if fenced:
        return fenced.group(1)

    # Caso 2: no hay fences, pero hay un objeto JSON en algún lado del texto.
    # Tomamos desde la primera "{" hasta la última "}" del string completo.
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw_text[start : end + 1]

    raise GeminiResponseParseError(
        f"No se encontró ningún bloque JSON en la respuesta de Gemini: {raw_text[:300]!r}"
    )


def parse_gemini_response(raw_text: str) -> dict:
    """
    Parsea y valida el JSON de evaluación de lead. Devuelve un dict con
    claves: urgency_score (float, 0-10), recommended_service (str),
    sales_arguments (list[str]).

    Levanta GeminiResponseParseError si el JSON es inválido o si algún
    campo está fuera de rango / con el tipo incorrecto.
    """
    json_block = _extract_json_block(raw_text)

    try:
        data = json.loads(json_block)
    except json.JSONDecodeError as exc:
        raise GeminiResponseParseError(
            f"JSON inválido en la respuesta de Gemini: {exc}. Texto: {json_block[:300]!r}"
        ) from exc

    if not isinstance(data, dict):
        raise GeminiResponseParseError(f"Se esperaba un objeto JSON, se recibió: {type(data)}")

    # --- urgency_score ---
    score = data.get("urgency_score")
    if not isinstance(score, (int, float)):
        raise GeminiResponseParseError(f"urgency_score inválido o ausente: {score!r}")
    score = float(score)
    if not (0 <= score <= 10):
        raise GeminiResponseParseError(f"urgency_score fuera de rango [0,10]: {score}")

    # --- recommended_service ---
    service = data.get("recommended_service")
    if not isinstance(service, str) or not service.strip():
        raise GeminiResponseParseError(f"recommended_service inválido o vacío: {service!r}")
    service = service.strip()[:MAX_SERVICE_LENGTH]

    # --- sales_arguments ---
    arguments = data.get("sales_arguments")
    if not isinstance(arguments, list) or not arguments:
        raise GeminiResponseParseError(f"sales_arguments inválido o vacío: {arguments!r}")

    clean_arguments = []
    for arg in arguments[:MAX_SALES_ARGUMENTS]:
        if isinstance(arg, str) and arg.strip():
            clean_arguments.append(arg.strip()[:MAX_ARGUMENT_LENGTH])

    if not clean_arguments:
        raise GeminiResponseParseError("sales_arguments no tenía ningún string válido dentro de la lista.")

    return {
        "urgency_score": score,
        "recommended_service": service,
        "sales_arguments": clean_arguments,
    }