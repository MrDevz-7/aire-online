// frontend/src/lib/motivo-fallback.ts
//
// Traduce el `motivo_fallback` que persiste el backend (enum D70) a texto
// humano para mostrar en la card del reporte. Ninguno de estos motivos es
// un error de la app: son la explicación de por qué se usó la plantilla
// determinística en lugar de Gemini.
//
// El tono es informativo, no alarmante. "Cuota diaria agotada" es una
// situación esperada del proyecto (D73), no un fallo.

import type { MotivoFallback } from "@/types/api";

export interface MotivoInfo {
  titulo: string;
  descripcion: string;
  /** true = es un motivo "esperado/normal" del sistema, sin alerta visual. */
  esperado: boolean;
}

const MOTIVOS: Record<MotivoFallback, MotivoInfo> = {
  sin_clave: {
    titulo: "Sin clave de Gemini configurada",
    descripcion:
      "El proyecto está corriendo sin API key de Gemini, así que el texto fue redactado con la plantilla determinística. Es un modo de operación válido: la plantilla dice exactamente lo mismo que la ficha, sin agregar ni omitir datos.",
    esperado: true,
  },
  cuota_diaria: {
    titulo: "Cuota diaria de Gemini agotada",
    descripcion:
      "El proyecto llegó al tope diario de solicitudes a Gemini (D73). El reporte se generó con la plantilla determinística. Mañana vuelve a estar disponible.",
    esperado: true,
  },
  http_429: {
    titulo: "Gemini devolvió límite de tasa",
    descripcion:
      "Gemini respondió 429 (demasiadas solicitudes). El proyecto agotó los reintentos y cayó a la plantilla determinística.",
    esperado: true,
  },
  timeout: {
    titulo: "Gemini no respondió a tiempo",
    descripcion:
      "La solicitud a Gemini superó el tiempo máximo de espera. El proyecto cayó a la plantilla determinística.",
    esperado: true,
  },
  error_api: {
    titulo: "Gemini devolvió un error",
    descripcion:
      "La API de Gemini respondió con un error no recuperable. El proyecto cayó a la plantilla determinística.",
    esperado: true,
  },
  validacion_numeros: {
    titulo: "Texto descartado: mencionaba números fuera de la ficha",
    descripcion:
      "El texto que redactó Gemini contenía al menos un número que no estaba en los datos de entrada. Como el proyecto garantiza que nunca se inventan cifras (D70), ese texto se descartó y se usó la plantilla determinística.",
    esperado: false,
  },
  validacion_texto: {
    titulo: "Texto descartado: no pasó la validación",
    descripcion:
      "El texto que redactó Gemini contenía términos prohibidos (por ejemplo, prometer certeza o describir el sistema como machine learning), o superó el largo máximo. Se descartó y se usó la plantilla determinística.",
    esperado: false,
  },
  forzado: {
    titulo: "Generación con plantilla forzada",
    descripcion:
      "Este reporte se generó explícitamente con la plantilla determinística, sin llamar a Gemini. Es la vía manual que usa el panel de admin para verificar el flujo sin gastar cuota.",
    esperado: true,
  },
};

export function infoMotivoFallback(m: MotivoFallback | null): MotivoInfo | null {
  if (!m) return null;
  return MOTIVOS[m] ?? null;
}