"""
Construcción de prompts para Gemini: system prompt (persona + reglas de
salida), prompt de evaluación de lead, filtro previo should_skip_lead, y
prompt de generación de email.

Todo vive en el mismo archivo porque comparten la misma "voz de marca" y
las mismas reglas de salida (idioma, tono, longitud) — tenerlos juntos
evita que se desincronicen si un día cambia el estilo de CustoFinder.
Estas funciones NO llaman a la red: son puro armado de strings, así se
pueden testear sin gastar cuota de Gemini ni necesitar conexión.
"""
from __future__ import annotations


def should_skip_lead(context: dict) -> tuple[bool, str]:
    """
    Decide si conviene NO gastar una llamada a Gemini en este negocio.
    Devuelve (skip: bool, reason: str). reason siempre tiene contenido,
    incluso cuando skip=False (para loguear el motivo de por qué sí sigue).
    """
    if context.get("has_website"):
        return True, (
            "El negocio ya tiene sitio web (has_website=True). CustoFinder "
            "hoy prospecta negocios sin web; se descarta sin gastar cuota "
            "de Gemini."
        )

    if not context.get("phone") and not context.get("address"):
        return True, (
            "Sin teléfono ni dirección registrados: no hay ningún dato de "
            "contacto para hacer seguimiento comercial, aunque el lead sea "
            "bueno en teoría."
        )

    if not context.get("name") or not context["name"].strip():
        return True, "Sin nombre utilizable (no debería llegar hasta acá si maps_discovery.py filtró bien)."

    return False, "Pasa el filtro previo; se evalúa con Gemini."


def build_system_prompt() -> str:
    """Persona + reglas de salida. Se manda como system_instruction en
    cada llamada (tanto para evaluar leads como para escribir emails)."""
    return (
        "Eres un analista comercial senior de CustoFinder, una agencia de "
        "desarrollo de software freelance en Medellín, Colombia, especializada "
        "en construir sitios web y presencia digital para negocios locales "
        "(restaurantes, peluquerías, gimnasios, clínicas, etc).\n\n"
        "Tu trabajo es evaluar negocios descubiertos como posibles leads "
        "comerciales, y cuando se te pida, redactar emails de prospección.\n\n"
        "REGLAS DE SALIDA:\n"
        "- Responde SIEMPRE en español, tono profesional pero cercano "
        "(colombiano, no español de España).\n"
        "- Cuando se te pida evaluar un lead, responde ÚNICAMENTE con un "
        "objeto JSON válido, sin texto antes ni después, sin explicaciones "
        "adicionales. No uses bloques de código markdown si no te lo piden "
        "explícitamente.\n"
        "- Nunca inventes datos del negocio que no te dieron (rating, número "
        "de empleados, años operando, etc). Basa tu análisis solo en la "
        "información provista."
    )


def build_lead_prompt(context: dict) -> str:
    """
    Arma el prompt de evaluación de un negocio concreto. `context` es el
    dict con la forma de Business: name, category, zone, address, phone,
    has_website (rating/review_count no aplican con OSM, ver nota abajo).
    """
    return (
        "Evalúa el siguiente negocio local como posible lead comercial para "
        "CustoFinder (venderle desarrollo de sitio web / presencia digital).\n\n"
        f"- Nombre: {context.get('name')}\n"
        f"- Categoría: {context.get('category')}\n"
        f"- Zona: {context.get('zone')}\n"
        f"- Dirección: {context.get('address') or 'no disponible'}\n"
        f"- Teléfono: {context.get('phone') or 'no disponible'}\n"
        f"- ¿Tiene sitio web?: {'Sí' if context.get('has_website') else 'No'}\n\n"
        "NOTA IMPORTANTE: estos datos vienen de OpenStreetMap, no de Google "
        "Places. No hay rating ni número de reseñas disponibles — NO asumas "
        "ni inventes ninguno de los dos. Además, el campo 'tiene sitio web' "
        "puede tener falsos negativos (negocios que sí tienen web pero no lo "
        "cargaron en OSM); considera esto como una señal, no una certeza "
        "absoluta, al justificar tu urgency_score.\n\n"
        "Responde con un JSON con EXACTAMENTE estas claves:\n"
        "{\n"
        '  "urgency_score": <número de 0 a 10, qué tan urgente/valioso es '
        "este lead>,\n"
        '  "recommended_service": "<string corto, el servicio concreto que '
        "le venderías (ej: \\\"sitio web con menú digital y reservas\\\")>\",\n"
        '  "sales_arguments": ["<argumento 1>", "<argumento 2>", "<argumento 3>"],\n'
        '  "reasoning": "<1-2 frases explicando el score, en español>"\n'
        "}\n"
        "sales_arguments debe tener entre 2 y 4 argumentos concretos y "
        "específicos a ESTE negocio (no genéricos)."
    )


def build_email_prompt(lead_context: dict) -> str:
    """
    Arma el prompt para redactar el email de prospección. `lead_context`
    incluye los datos del negocio MÁS el resultado ya guardado del análisis
    (urgency_score, recommended_service, sales_arguments).
    """
    arguments = lead_context.get("sales_arguments") or []
    arguments_text = "\n".join(f"- {arg}" for arg in arguments) or "(sin argumentos registrados)"

    return (
        "Redacta un email corto de prospección comercial en frío (cold "
        "email) para el siguiente negocio, de parte de CustoFinder.\n\n"
        f"- Negocio: {lead_context.get('name')}\n"
        f"- Categoría: {lead_context.get('category')}\n"
        f"- Zona: {lead_context.get('zone')}\n"
        f"- Servicio recomendado: {lead_context.get('recommended_service')}\n"
        f"- Argumentos de venta a usar:\n{arguments_text}\n\n"
        "REGLAS:\n"
        "- Máximo 150 palabras en el cuerpo.\n"
        "- Menciona el nombre del negocio de forma natural (no como plantilla "
        "genérica de mail masivo).\n"
        "- Un único llamado a la acción claro al final (ej: agendar una "
        "llamada corta de 15 minutos).\n"
        "- NO uses frases como 'Espero que este correo te encuentre bien'.\n"
        "- Firma como 'Equipo CustoFinder'.\n\n"
        "Responde en texto plano con este formato EXACTO (sin JSON, sin "
        "markdown):\n"
        "Asunto: <línea de asunto>\n\n"
        "<cuerpo del email>"
    )