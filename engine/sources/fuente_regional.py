"""
Contrato común de las fuentes regionales de calidad del aire (M4).

Las fuentes del proyecto son heterogéneas (OpenAQ/AQICN son APIs
oficiales; IBOCA/SIATA son servicios públicos sin clave; Corantioquia y
SIMAC a futuro tendrán otra forma). Lo que todas comparten: producen un
`ResultadoDescarga`. Ese es el contrato real, y vive en `sources/tipos.py`;
este módulo lo formaliza como `Protocol` para que las fuentes futuras
tengan una referencia y el type checker pueda verificar conformidad.

Por qué `Protocol` y no una ABC: no obliga a heredar. Las fuentes de M3
(ClienteOpenAQ, ClienteAQICN) ya cumplen el contrato sin saber que existe,
y no hay que tocarlas. Si en el futuro las fuentes regionales empiezan a
compartir lógica concreta (reintentos HTTP, etc.), ahí sí conviene una ABC.

Qué NO está en el contrato: el atributo `fuente`. Ya viaja en
`ResultadoDescarga.fuente`, que es donde lo lee `services/ingestion.py`.
Pedirlo también como atributo de clase hacía el Protocol más estricto que
el contrato real.

Cómo se usa:
    def ejecutar(cliente: FuenteRegional) -> ResultadoDescarga:
        with cliente:
            return cliente.descargar()
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from sources.tipos import ResultadoDescarga


@runtime_checkable
class FuenteRegional(Protocol):
    """Ver docstring del módulo."""

    def descargar(self) -> ResultadoDescarga:
        """Trae todas las estaciones y las traduce a `ResultadoDescarga`.

        Fallo total (red, HTTP, JSON) -> devuelve vacío con `abortada`
        seteado, sin lanzar. Fallo puntual de una estación -> se salta y
        se sigue. (Patrón de rotowire_lineups.py: un scraper no debe
        tumbar el pipeline.)
        """
        ...

    def close(self) -> None:
        """Libera recursos (conexiones HTTP, etc.). Idempotente."""
        ...