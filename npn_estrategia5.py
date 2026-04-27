"""
Estrategia 5 — Lawnmower (cortacésped / boustrophedon puro en sentido de bandas
horizontales N→S, alternando oeste–este y este–oeste). Pensado para disposición
**irregular** y áreas dispares: el paso y las bandas se derivan de estadísticos
del conjunto, no solo del polígono mínimo (a menudo poco adecuado a la mancha real).
No se usa curva de Morton (Z) en el orden, para no mezclar con otro recorrido.
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
OUTPUT_SHP = "terrenos_test_estrategia5.shp"
GRID_CRS = "EPSG:3115"
MIN_CELL_M = 5.0
MAX_NPN = 9999
# Cómo fijar el paso s (m) y las bandas N–S. "adaptive" = combina caja y lotes
CELL_MODE = "adaptive"  # "adaptive" | "median_lot" | "sqrt_bbox"
ADAPT_PCT = 0.4  # con adaptive: s ≈ sqrt(bbox_m2 / n) * factor


def _ref_lonlat(geom) -> Tuple[float, float]:
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

_ref = gdf.geometry.apply(_ref_lonlat)
gdf["lon"] = _ref.apply(lambda t: t[0])
gdf["lat"] = _ref.apply(lambda t: t[1])
del _ref

gdf_p = gdf.to_crs(GRID_CRS)
n_feat = len(gdf)
xmin, ymin, xmax, ymax = gdf_p.total_bounds
g_area = gdf_p.geometry.area.to_numpy()
c_ll = gdf_p.geometry.centroid
x = c_ll.x.to_numpy()
y = c_ll.y.to_numpy()
a_pos = g_area[(g_area > 0.0) & np.isfinite(g_area)]
# Paso característico: para parches *no* alineados a un rectángulo regular,
# la mediana de sqrt(área) refleja un “lote típico”; evita celdas ridículas del solo-mín
med_sqrt = float(np.median(np.sqrt(a_pos))) if a_pos.size else 0.0
min_sqrt = float(np.sqrt(np.min(a_pos) + 1e-6)) if a_pos.size else MIN_CELL_M
a_box = max((xmax - xmin) * (ymax - ymin), 0.0)
s_bbox = math.sqrt(a_box / max(n_feat, 1)) * ADAPT_PCT

if CELL_MODE == "median_lot":
    s = max(MIN_CELL_M, med_sqrt) if med_sqrt > 0 else max(MIN_CELL_M, s_bbox)
elif CELL_MODE == "sqrt_bbox":
    s = max(MIN_CELL_M, s_bbox) if a_box > 0 else MIN_CELL_M
else:  # adaptive: entre mediana, bbox/n y piso; no ligue solo al mínimo
    cands = [c for c in (med_sqrt, s_bbox, min_sqrt) if c > 0.0 and np.isfinite(c)]
    s = max(MIN_CELL_M, min(cands) if cands else MIN_CELL_M)
    s = min(s, max(med_sqrt, s_bbox) * 1.5) if cands else s  # cap razonable
    s = max(MIN_CELL_M, s)

spanx = max(xmax - xmin, 1e-6)
spany = max(ymax - ymin, 1e-6)
# Franjas N–S (cada “pasada” del lawnmower en y)
H = s  # un paso = altura de banda
n_b = max(1, int(math.ceil(spany / H)))
# Índice de fila: 0 cerca de ymin, n_b-1 cerca de ymax; noroeste lógica = y alto, x bajo
ir = np.floor((y - ymin) / H).astype(np.int64)
ir = np.clip(ir, 0, n_b - 1)
# rkey 0 = banda más al norte, …, N–S
rkey = (n_b - 1) - ir
ok2 = np.isfinite(x) & np.isfinite(y)
INV = 1_000_000
rkey = np.where(ok2, rkey, INV)
# Corte mediana si una sola banda útil
if n_feat >= 2 and ok2.sum() >= 2 and n_b >= 2:
    msk = (rkey < INV) & ok2
    if msk.sum() and len(np.unique(rkey[msk])) < 2:
        med = float(np.median(y[msk & ok2]))
        rkey = np.where(
            msk, np.where(y >= med, 0, 1).astype(np.int64), rkey
        )
        n_b = 2
        H = spany / 2.0
        ir = np.floor((y - ymin) / H).astype(np.int64)
        ir = np.clip(ir, 0, 1)
        rkey = (1 - ir).astype(np.int64)
        rkey = np.where(ok2, rkey, INV)

# Columna entera (solo descriptivo / export)
ic = np.floor((x - xmin) / s).astype(np.int64)
ic = np.clip(ic, 0, max(0, int(np.ceil(spanx / s)) - 1))
del c_ll, gdf_p

gdf = gdf.reset_index(drop=True)
g_area = g_area[: len(gdf)]
x = x[: len(gdf)]
y = y[: len(gdf)]
rkey = rkey[: len(gdf)]
ir = ir[: len(gdf)]
ic = ic[: len(gdf)]
ok2 = ok2[: len(gdf)]
n = len(gdf)
START_NPN = int(os.environ.get("NPN_START", "1"))
STOP_NPN = int(os.environ.get("NPN_STOP", "9999"))
if START_NPN < 0 or STOP_NPN > 9999 or START_NPN > STOP_NPN:
    raise ValueError("Rango NPN invalido: use start/stop entre 0000 y 9999.")
available = (STOP_NPN - START_NPN) + 1
if n > min(MAX_NPN, available):
    raise ValueError(
        f"El rango NPN seleccionado ({START_NPN:04d}-{STOP_NPN:04d}) no alcanza para {n} poligonos."
    )

# ------------------------------
# 2. Lawnmower: boustrophedon = (fila n→S) + (E–O u O–E según fila)
#    Sin Morton: solo (rkey, ckey, desempate área, lon)
# ------------------------------
idx0 = np.arange(n, dtype=np.int64)
valid = (rkey < INV) & ok2
# rkey menor = banda más al norte; orden ascendente => primero al norte, luego al sur
u = (
    np.sort(np.unique(rkey[valid]))
    if valid.any()
    else np.array([], dtype=np.int64)
)
row_id_to_rank = {v: k for k, v in enumerate(u)}
rkey2 = np.array(
    [row_id_to_rank[rkey[i]] if valid[i] else INV for i in range(n)], dtype=np.int64
)
if valid.any():
    max_gc = int(np.max(ic[valid]))
    min_gc = int(np.min(ic[valid]))
    mxc = max(0, max_gc - min_gc)
    even = (rkey2 % 2) == 0
    ckey = np.where(
        valid & even,
        ic,
        np.where(valid & ~even, mxc - (ic - min_gc) if mxc else ic, 0),
    ).astype(np.int64)
else:
    ckey = np.zeros(n, dtype=np.int64)
c_lat = gdf.geometry.centroid.y.to_numpy()
c_lon = gdf.geometry.centroid.x.to_numpy()
c_lon2 = np.where(np.isfinite(c_lon), c_lon, 0.0)
even = (rkey2 % 2) == 0
c_lonT = np.where((rkey2 >= INV) | even, c_lon2, -c_lon2)
tarea = -np.log1p(np.maximum(g_area, 0.0))
# Eje principal lawnmover: (rkey2, ckey) — índice estable final
m_base = np.lexsort(
    (idx0, c_lat, c_lonT, tarea, ckey, rkey2)
)

# Inicio 0001 = esquina noroeste (max lat, min lon) sobre (lon,lat) de referencia
lat_v = gdf["lat"].to_numpy(dtype=np.float64)
lon_v = gdf["lon"].to_numpy(dtype=np.float64)
vl = np.isfinite(lat_v) & np.isfinite(lon_v)
c_lx = np.where(vl, lat_v, -np.inf)
c_ly = np.where(vl, lon_v, np.inf)
i_nw = int(np.lexsort((idx0, c_ly, -c_lx))[0])
pos = int(np.argwhere(m_base == i_nw).ravel()[0])
m_fin = np.concatenate((m_base[pos:], m_base[:pos]))

gdf = gdf.iloc[m_fin].copy().reset_index(drop=True)
gdf["NEW_CODE"] = [f"{i:04d}" for i in range(START_NPN, START_NPN + n)]
gdf["G_COL"] = ic[m_fin]
gdf["G_ROW"] = ir[m_fin]
gdf["L_S_M"] = float(s)
gdf["L_BND"] = int(n_b)
gdf["E5_MD"] = str(CELL_MODE)
gdf["E5_TIP"] = "lawnmower_boust"
print(
    f"Estrategia5 (Lawnmower): s~{s:.1f} m, bandas_N={n_b}, modo={CELL_MODE}, "
    f"med_sqrt={med_sqrt:.1f} m, 0001=noroeste (i={i_nw}, rot={pos})"
)

# Polilínea: centroides en m (misma métrica que el lawnmover), luego 4326
_gm = gdf.to_crs(GRID_CRS)
xm = _gm.geometry.centroid.x.to_numpy()
ym = _gm.geometry.centroid.y.to_numpy()
del _gm
line_p = gpd.GeoSeries(
    [Point(float(a), float(b)) for a, b in zip(xm, ym)],
    crs=GRID_CRS,
).to_crs("EPSG:4326")
line_xy = [(float(g.x), float(g.y)) for g in line_p]

out_poly = Path(OUTPUT_SHP)
out_lines = out_poly.with_name(out_poly.stem + "_newcode_path.shp")
if len(line_xy) >= 2:
    gpd.GeoDataFrame(
        data={"N_PTOS": [len(line_xy)]},
        geometry=[LineString(line_xy)],
        crs="EPSG:4326",
    ).to_file(out_lines, driver="ESRI Shapefile")
    print(f"Polilinea (centroides, patrón lawnmower): {out_lines}")

gdf.drop(columns=["lon", "lat"], errors="ignore").to_file(OUTPUT_SHP, driver="ESRI Shapefile")
print(f"Listo: {OUTPUT_SHP}")
