"""
Estrategia 3 (híbrida): polígonos irregulares, jerarquía N→S + giro en sentido horario
a partir de la esquina noroeste, con desempates por distancia/área.
"""
import math
import os
from pathlib import Path
from typing import Tuple

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point

# ------------------------------
# CONFIGURATION
# ------------------------------
INPUT_SHP = "terrenos_test.shp"
OUTPUT_SHP = "terrenos_test_estrategia3.shp"
GRID_CRS = "EPSG:3115"
# Número aprox. de franjas horizontales (N→S) ~ densidad * √n; >=2 si n>=2
FRANJAS_SOBRE_RAIZN = 2.0
N_FRANJAS_FORZ = 0  # 0 = automático; >0 fuerza n_franjas


def _ref_lonlat(geom) -> Tuple[float, float]:
    """Punto interior: representative_point, luego centroide."""
    if geom is None or geom.is_empty:
        return (float("nan"), float("nan"))
    p = None
    try:
        p = geom.representative_point()
    except (AttributeError, TypeError, ValueError):
        pass
    if p is None or p.is_empty:
        try:
            c = geom.centroid
            p = c if c is not None and not c.is_empty else None
        except (AttributeError, TypeError, ValueError):
            p = None
    if p is None or p.is_empty:
        return (float("nan"), float("nan"))
    return (float(p.x), float(p.y))


# ------------------------------
# 1. Carga
# ------------------------------
gdf = gpd.read_file(INPUT_SHP)
if gdf.crs is None:
    raise ValueError("Shapefile has no CRS. Please assign one.")
gdf = gdf.to_crs("EPSG:4326")

# ------------------------------
# 2. Puntos (lon, lat) y geometría para área
# ------------------------------
_ref = gdf.geometry.apply(_ref_lonlat)
gdf["lon"] = _ref.apply(lambda t: t[0])
gdf["lat"] = _ref.apply(lambda t: t[1])
del _ref

gdf_p = gdf.to_crs(GRID_CRS)
n_feat = len(gdf)
xmin, ymin, xmax, ymax = gdf_p.total_bounds
g_area = gdf_p.geometry.area.to_numpy()
c_ll = gdf_p.geometry.centroid
cxg = c_ll.x.to_numpy()
cyg = c_ll.y.to_numpy()
del c_ll, gdf_p
ref = gpd.GeoSeries(
    [Point(lon, lat) for lon, lat in zip(gdf["lon"], gdf["lat"])],
    crs="EPSG:4326",
).to_crs(GRID_CRS)
x = ref.x.to_numpy()
y = ref.y.to_numpy()
ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(cxg) & np.isfinite(cyg)
x = np.where(ok, x, cxg)
y = np.where(ok, y, cyg)
ok2 = np.isfinite(x) & np.isfinite(y)
del ref

# Franjas N→S (rkey 0 = norte) + referencias para búsqueda
# ------------------------------
if int(N_FRANJAS_FORZ) > 0:
    n_strips = max(1, int(N_FRANJAS_FORZ))
elif n_feat >= 2:
    n_strips = int(round(FRANJAS_SOBRE_RAIZN * math.sqrt(float(n_feat))))
    n_strips = min(n_feat, max(2, n_strips))
else:
    n_strips = 1

span_y = max(float(ymax - ymin), 1e-6)
H = span_y / float(n_strips)
ibin = np.floor((y - ymin) / H).astype(np.int64)
ibin = np.clip(ibin, 0, n_strips - 1)
rkey = (n_strips - 1) - ibin
INV = 1_000_000
rkey = np.where(ok2, rkey, INV)
# Mediana: una sola franja
if n_feat >= 2 and ok2.sum() >= 2 and n_strips >= 2:
    msk = (rkey < INV) & ok2
    if msk.sum() and len(np.unique(rkey[msk])) < 2:
        med = float(np.median(y[msk & ok2]))
        rkey = np.where(msk, np.where(y >= med, 0, 1).astype(np.int64), rkey)
        n_strips = 2
        H = span_y / 2.0
        print("Aviso: 2 franjas por mediana y (corte N/S).")

gdf = gdf.reset_index(drop=True)
n = len(gdf)
g_area = g_area[:n]
x = x[:n]
y = y[:n]
rkey = rkey[:n]
ok2 = ok2[:n]
lat_v = gdf["lat"].to_numpy(dtype=np.float64)
lon_v = gdf["lon"].to_numpy(dtype=np.float64)
valid_ll = np.isfinite(lat_v) & np.isfinite(lon_v)

# Esquina noroeste: máx. lat, mín. lon (1º predio 0001 si cuadra con el giro; rotamos luego)
c_lat2 = np.where(valid_ll, lat_v, -np.inf)
c_lon2 = np.where(valid_ll, lon_v, np.inf)
idx0 = np.arange(n, dtype=np.int64)
nw_order = np.lexsort((idx0, c_lon2, -c_lat2))
i_nw = int(nw_order[0])

# Centro de búsqueda: media básica; opcional: ponderar por área
cx0 = float(np.nanmean(x[ok2])) if np.any(ok2) else 0.0
cy0 = float(np.nanmean(y[ok2])) if np.any(ok2) else 0.0
area_w = np.where(np.isfinite(g_area) & (g_area > 0.0), g_area, 0.0)
wtot = area_w.sum()
if wtot > 0.0:
    cx0 = float(np.nansum(x * area_w) / wtot)
    cy0 = float(np.nansum(y * area_w) / wtot)

dx = x - cx0
dy = y - cy0
# Grados 0..360, sentido **horario** desde el **norte** (E=90, S=180, W=270)
ang_cw = (90.0 - np.degrees(np.arctan2(dy, dx))) % 360.0
a0 = float(ang_cw[i_nw])
rel = (ang_cw - a0) % 360.0
dist2 = np.where(ok2, dx * dx + dy * dy, 0.0)
# Tamaño: lote chico = mayor índice de orden (última capa) para no dominar; log suaviza
tarea = -np.log1p(np.maximum(g_area, 0.0))

# ------------------------------
# 4. Orden híbrido: (1) rkey N→S, (2) giro orario (rel), (3) dist., (4) área, (5) índice
#    Luego **rotar** para que 0001 = predio en esquina noroeste
# ------------------------------
START_NPN = int(os.environ.get("NPN_START", "1"))
STOP_NPN = int(os.environ.get("NPN_STOP", "9999"))
if START_NPN < 0 or STOP_NPN > 9999 or START_NPN > STOP_NPN:
    raise ValueError("Rango NPN invalido: use start/stop entre 0000 y 9999.")
available = (STOP_NPN - START_NPN) + 1
if n > available:
    raise ValueError(
        f"El rango NPN seleccionado ({START_NPN:04d}-{STOP_NPN:04d}) no alcanza para {n} poligonos."
    )

m_base = np.lexsort(
    (idx0, tarea, dist2, rel, rkey),
)
# Rotación circular: el primer código es i_nw (noroeste lexicográfico)
pos = int(np.argwhere(m_base == i_nw).ravel()[0])
m_fin = np.concatenate((m_base[pos:], m_base[:pos]))

gdf = gdf.iloc[m_fin].copy().reset_index(drop=True)
gdf["NEW_CODE"] = [f"{i:04d}" for i in range(START_NPN, START_NPN + n)]
gdf["F_STRP"] = rkey[m_fin]
gdf["N_FRJ"] = np.int32(n_strips)
gdf["ESTR3"] = "N-S_CW_area"

# Polilínea: mismas (x,y) de orden, reproyectar a 4326
x_seq = x[m_fin]
y_seq = y[m_fin]
line_prj = gpd.GeoSeries(
    [Point(float(a), float(b)) for a, b in zip(x_seq, y_seq)],
    crs=GRID_CRS,
).to_crs("EPSG:4326")
line_xy = [(float(g.x), float(g.y)) for g in line_prj]

out_poly = Path(OUTPUT_SHP)
out_lines = out_poly.with_name(out_poly.stem + "_newcode_path.shp")
if len(line_xy) >= 2:
    gpd.GeoDataFrame(
        data={"N_PTOS": [len(line_xy)]},
        geometry=[LineString(line_xy)],
        crs="EPSG:4326",
    ).to_file(out_lines, driver="ESRI Shapefile")
    print(f"Polilínea: {out_lines}")
else:
    print("Aviso: no se generó polilínea (pocos puntos).")

gdf.drop(columns=["lon", "lat"], errors="ignore").to_file(OUTPUT_SHP, driver="ESRI Shapefile")
print(
    f"Estrategia3: noroeste=0001 (i={i_nw}, rotación {pos}), "
    f"centro=({cx0:.0f},{cy0:.0f}) m, n_franjas={n_strips}. Guardado: {OUTPUT_SHP}"
)
