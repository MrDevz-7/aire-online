// frontend/src/app/admin/page.tsx
//
// Panel de administración. Botones que disparan las acciones del
// scheduler (ingesta ×4, reconciliación, captura de pronósticos,
// auditoría, reportes ×2) + log de resultados de la sesión.
//
// Reglas clave:
//   - Reconciliación es UNA acción que internamente llama a dos endpoints
//     en orden: emparejar y después comparar. Si emparejar falla, NO se
//     dispara comparar (mismo criterio que job_reconciliacion del engine).
//   - Reportes tiene DOS acciones: con Gemini (completo, puede tardar) y
//     con plantilla (instantáneo, siempre funciona). La segunda usa
//     `forzar_plantilla=true`.
//   - Serialización: solo una acción en vuelo a la vez. Previene dobles
//     clicks y respeta el rate limit admin (10/min, D82).
//   - El log NO persiste en el servidor ni en localStorage: es de sesión.

"use client";

import { useCallback, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { ProtectedRoute } from "@/components/protected-route";
import { AccionesGrid } from "@/components/admin/acciones-grid";
import { ActionLog } from "@/components/admin/action-log";
import type { EntradaLog } from "@/components/admin/resultado-card";
import {
  adminAuditRun,
  adminIngest,
  adminPronosticosCapturar,
  adminReconciliacionComparar,
  adminReconciliacionEmparejar,
  adminReportesGenerar,
  mensajeDeError,
  type IngestFuente,
} from "@/lib/api";

/**
 * Dispara la acción según su id y devuelve el resultado. Es una función
 * pura (sin estado): el panel la llama y maneja el log y el estado de
 * "en vuelo".
 *
 * Reconciliación: hace DOS llamadas encadenadas. Si la primera falla,
 * lanza antes de disparar la segunda. El resultado devuelto agrupa ambos
 * resúmenes para que el renderer los muestre en orden.
 */
async function ejecutarAccion(id: string): Promise<unknown> {
  if (id.startsWith("ingest-")) {
    const fuente = id.replace("ingest-", "") as IngestFuente;
    return adminIngest(fuente);
  }
  if (id === "reconciliacion") {
    const emparejar = await adminReconciliacionEmparejar();
    const comparar = await adminReconciliacionComparar();
    return { emparejar, comparar };
  }
  if (id === "pronosticos-capturar") {
    return adminPronosticosCapturar();
  }
  if (id === "audit-run") {
    return adminAuditRun();
  }
  if (id === "reportes-generar") {
    return adminReportesGenerar();
  }
  if (id === "reportes-generar-plantilla") {
    return adminReportesGenerar({ forzar_plantilla: true });
  }
  throw new Error(`Acción desconocida: ${id}`);
}

function AdminPanel() {
  const [enVuelo, setEnVuelo] = useState<string | null>(null);
  const [log, setLog] = useState<EntradaLog[]>([]);

  const disparar = useCallback(async (accionId: string) => {
    // El botón ya está deshabilitado mientras `enVuelo !== null`, pero por
    // las dudas: si por alguna razón llega una segunda llamada, se ignora.
    if (enVuelo !== null) return;

    setEnVuelo(accionId);
    const inicio = new Date();
    try {
      const data = await ejecutarAccion(accionId);
      const duracionMs = Date.now() - inicio.getTime();
      setLog((prev) => [
        { accionId, inicio, duracionMs, ok: true, data },
        ...prev,
      ]);
    } catch (err) {
      const duracionMs = Date.now() - inicio.getTime();
      setLog((prev) => [
        {
          accionId,
          inicio,
          duracionMs,
          ok: false,
          error: new Error(mensajeDeError(err)),
        },
        ...prev,
      ]);
    } finally {
      setEnVuelo(null);
    }
  }, [enVuelo]);

  const limpiarLog = useCallback(() => setLog([]), []);

  return (
    <main className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sky-700 dark:text-sky-400">
          <SlidersHorizontal className="size-5" />
          <span className="text-xs font-medium uppercase tracking-wider">
            Administración
          </span>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Panel de control
        </h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Las mismas acciones que el scheduler corre cada madrugada,
          disparadas a mano para hacer demos en vivo. Solo se puede
          ejecutar una acción a la vez.
        </p>
      </div>

      <AccionesGrid enVuelo={enVuelo} onDisparar={disparar} />

      <ActionLog entradas={log} onLimpiar={limpiarLog} />
    </main>
  );
}

export default function AdminPage() {
  return (
    <ProtectedRoute>
      <AdminPanel />
    </ProtectedRoute>
  );
}