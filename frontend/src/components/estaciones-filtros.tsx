// frontend/src/components/estaciones-filtros.tsx
//
// Barra de filtros del listado de estaciones. Tres filtros:
//   - fuente: select poblado con las fuentes presentes en la lista.
//   - ciudad: select poblado con las ciudades presentes en la lista.
//   - activa: todas / solo activas / solo inactivas.
//
// Los selects se pueblan a partir de la lista SIN filtrar (así las opciones
// no desaparecen cuando se filtra por otra cosa). Recibe `opcionesFuentes` y
// `opcionesCiudades` como props desde la página.

"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";

export type FiltroActiva = "todas" | "activas" | "inactivas";

export interface FiltrosEstaciones {
  fuente: string;
  ciudad: string;
  activa: FiltroActiva;
}

interface Props {
  filtros: FiltrosEstaciones;
  onChange: (filtros: FiltrosEstaciones) => void;
  opcionesFuentes: string[];
  opcionesCiudades: string[];
}

export function EstacionesFiltros({
  filtros,
  onChange,
  opcionesFuentes,
  opcionesCiudades,
}: Props) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div className="space-y-1.5">
        <Label htmlFor="filtro-fuente" className="text-xs">
          Fuente
        </Label>
        <Select
          value={filtros.fuente}
          onValueChange={(v) =>
            onChange({ ...filtros, fuente: v ?? "todas" })
          }
        >
          <SelectTrigger id="filtro-fuente">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todas">Todas</SelectItem>
            {opcionesFuentes.map((f) => (
              <SelectItem key={f} value={f}>
                {f}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="filtro-ciudad" className="text-xs">
          Ciudad
        </Label>
        <Select
          value={filtros.ciudad}
          onValueChange={(v) =>
            onChange({ ...filtros, ciudad: v ?? "todas" })
          }
        >
          <SelectTrigger id="filtro-ciudad">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todas">Todas</SelectItem>
            {opcionesCiudades.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="filtro-activa" className="text-xs">
          Estado
        </Label>
        <Select
          value={filtros.activa}
          onValueChange={(v) =>
            onChange({ ...filtros, activa: (v ?? "todas") as FiltroActiva })
          }
        >
          <SelectTrigger id="filtro-activa">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todas">Todas</SelectItem>
            <SelectItem value="activas">Solo activas</SelectItem>
            <SelectItem value="inactivas">Solo inactivas</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}