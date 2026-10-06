"""Middlewares propios del engine (M8, D79)."""
from __future__ import annotations

import hashlib
import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def _comparar_tokens(a: str, b: str) -> bool:
    """Comparación en tiempo constante.

    `hmac.compare_digest` corta antes cuando los largos difieren: eso
    filtra por timing el largo del token correcto. Se hashean AMBOS lados
    a SHA-256 (32 bytes fijos) para que la comparación final siempre sea
    entre dos buffers del mismo tamaño, independientemente del input.
    """
    ha = hashlib.sha256(a.encode("utf-8")).digest()
    hb = hashlib.sha256(b.encode("utf-8")).digest()
    return hmac.compare_digest(ha, hb)


class InternalTokenMiddleware(BaseHTTPMiddleware):
    """Exige `X-Internal-Token` en todas las rutas `/internal/*` cuando el
    token esperado NO está vacío (D79).

    Si el token está vacío, las rutas quedan abiertas: es el flujo de
    desarrollo local de D44 (llamar `/internal/*` directo al engine sin
    autenticación). En producción el engine se niega a arrancar sin token:
    ver `api.main.validar_arranque`.

    Las rutas `/api/*` de lectura no se ven afectadas (son públicas).
    """

    def __init__(self, app, *, token_esperado: str) -> None:
        super().__init__(app)
        self._token = token_esperado

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/internal/"):
            return await call_next(request)
        if not self._token:
            # Modo abierto (solo desarrollo local).
            return await call_next(request)
        recibido = request.headers.get("x-internal-token", "")
        if not recibido or not _comparar_tokens(recibido, self._token):
            return JSONResponse(
                {"detail": "Token interno inválido o ausente"},
                status_code=401,
            )
        return await call_next(request)