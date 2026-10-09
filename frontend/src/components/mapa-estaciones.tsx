// frontend/src/components/mapa-estaciones.tsx
//
// Mapa Leaflet + OpenStreetMap. Se carga SIEMPRE con `next/dynamic` y
// `{ ssr: false }` desde la página que lo use (D94): Leaflet toca `window`
// al importarse, y en el servidor `window` no existe.
//
// Los marcadores son `CircleMarker` (SVG inline), no el marker PNG
// tradicional: los PNG de Leaflet tienen rutas que el bundler reescribe y
// quedan rotas. CircleMarker no tiene ese problema, y permite colorear por
// estado (activa/inactiva).
//
// Atribución de OSM obligatoria: la exige su política de uso, y va visible
// en el control de atribución del mapa.

"use client";

import { useEffect } from "react";
import {
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import type { EstacionItem } from "@/types/api";

interface MapaEstacionesProps {
  estaciones: EstacionItem[];
  seleccionadaId: number | null;
  onSeleccionar: (id: number) => void;
}

/** Ajusta el zoom del mapa para encuadrar TODAS las estaciones visibles
 *  cada vez que la lista filtrada cambia. Sin esto, el mapa se queda en
 *  la vista inicial aunque el filtro devuelva solo 3 estaciones. */
function AjustarVista({ estaciones }: { estaciones: EstacionItem[] }) {
  const map = useMap();
  useEffect(() => {
    if (estaciones.length === 0) return;
    if (estaciones.length === 1) {
      map.setView([estaciones[0].latitud, estaciones[0].longitud], 13);
      return;
    }
    const bounds = estaciones.map(
      (e) => [e.latitud, e.longitud] as [number, number],
    );
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
  }, [estaciones, map]);
  return null;
}

export default function MapaEstaciones({
  estaciones,
  seleccionadaId,
  onSeleccionar,
}: MapaEstacionesProps) {
  return (
    <MapContainer
      // Centro y zoom iniciales: Colombia entera. AjustarVista lo corrige
      // apenas lleguen las estaciones.
      center={[4.65, -74.09]}
      zoom={6}
      scrollWheelZoom
      style={{ height: "100%", width: "100%" }}
    >
      <TileLayer
        // Atribución obligatoria de OSM (ver §3 del prompt M11).
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <AjustarVista estaciones={estaciones} />
      {estaciones.map((e) => {
        const seleccionada = seleccionadaId === e.id;
        return (
          <CircleMarker
            key={e.id}
            center={[e.latitud, e.longitud]}
            radius={seleccionada ? 10 : 6}
            pathOptions={{
              // Azul para activas, gris para inactivas. No inventamos
              // colores por AQI acá: el listado no trae lecturas.
              color: e.activa ? "#0369a1" : "#71717a",
              fillColor: e.activa ? "#0ea5e9" : "#a1a1aa",
              fillOpacity: 0.75,
              weight: seleccionada ? 3 : 2,
            }}
            eventHandlers={{
              click: () => onSeleccionar(e.id),
            }}
          >
            <Popup>
              <div style={{ fontSize: 12, lineHeight: 1.5 }}>
                <div style={{ fontWeight: 600 }}>{e.nombre}</div>
                {e.ciudad && (
                  <div style={{ color: "#71717a" }}>{e.ciudad}</div>
                )}
                <div style={{ color: "#71717a" }}>Fuente: {e.fuente}</div>
                {!e.activa && (
                  <div style={{ color: "#b45309" }}>
                    Sin actividad reciente
                  </div>
                )}
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}