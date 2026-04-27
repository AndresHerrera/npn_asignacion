"""
Estrategia 4: grilla sobre el bbox, paso s = sqrt(área mín. de un polígono);
cada centroide se proyecta al centro de celda más cercano; asignación tipo 1+2+3
(boustrophedon N–S, Morton, rotación 0001 = noroeste).
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
OUTPUT_SHP = "terrenos_test_estrategia4.shp"
GRID_CRS = "EPSG:3115"
MIN_CELL_M = 1.0  # piso s (m) si el polígono mín. es casi cero
MAX_NPN = 9999


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


def _morton16(ix: int, iy: int) -> int:
    xb = int(ix) & 0xFFFF
    yb = int(iy) & 0xFFFF
    z = 0
    for b in range(16):
        z |= ((xb >> b) & 1) << (2 * b)
        z |= ((yb >> b) & 1) << (2 * b + 1)
    return int(z)


def _morton_keys(
    x: np.ndarray, y: np.ndarray, xmin: float, ymin: float, xmax: float, ymax: float
) -> np.ndarray:
    w = max(float(xmax - xmin), 1e-6)
    h = max(float(ymax - ymin), 1e-6)
    nx = (np.clip((x - xmin) / w, 0.0, 1.0) * 65535.0).astype(np.int64)
    ny = (np.clip((y - ymin) / h, 0.0, 1.0) * 65535.0).astype(np.int64)
    m = np.zeros(len(x), dtype=np.int64)
    for i in range(len(x)):
        m[i] = _morton16(int(nx[i]), int(ny[i]))
    return m


def _nearest_cell_indices(
    cx: np.ndarray,
    cy: np.ndarray,
    xmin: float,
    ymin: float,
    s: float,
    ncx: int,
    nry: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Devuelve índice de columna, de fila (Y al norte) y (x, y) del centro de celda más
    próximo a cada centroide.
    """
    s = max(float(s), 1e-6)
    n = len(cx)
    ic2 = np.zeros(n, dtype=np.int64)
    ir2 = np.zeros(n, dtype=np.int64)
    for k in range(n):
        a = (float(cx[k]) - xmin) / s
        i0 = int(math.floor(a))
        best_i, best_d = 0, float("inf")
        for i in (i0 - 1, i0, i0 + 1):
            if 0 <= i < ncx:
                xc = xmin + (i + 0.5) * s
                d = abs(float(cx[k]) - xc)
                if d < best_d:
                    best_d, best_i = d, i
        ic2[k] = best_i
    for k in range(n):
        a = (float(cy[k]) - ymin) / s
        j0 = int(math.floor(a))
        best_j, best_d = 0, float("inf")
        for j in (j0 - 1, j0, j0 + 1):
            if 0 <= j < nry:
                yc = ymin + (j + 0.5) * s
                d = abs(float(cy[k]) - yc)
                if d < best_d:
                    best_d, best_j = d, j
        ir2[k] = best_j
    x_snap = xmin + (ic2.astype(np.float64) + 0.5) * s
    y_snap = ymin + (ir2.astype(np.float64) + 0.5) * s
    return ic2, ir2, x_snap, y_snap


# ------------------------------
# 1. Carga
# ------------------------------
gdf = gpd.read_file(INPUT_SHP)
if gdf.crs is None:
    raise ValueError("Shapefile has no CRS. Please assign one.")
gdf = gdf.to_crs("EPSG:4326")

# ------------------------------
# 2. Puntos (lon,lat) y geometría
# ------------------------------
_ref = gdf.geometry.apply(_ref_lonlat)
gdf["lon"] = _ref.apply(lambda t: t[0])
gdf["lat"] = _ref.apply(lambda t: t[1])
del _ref

gdf_p = gdf.to_crs(GRID_CRS)
xmin, ymin, xmax, ymax = gdf_p.total_bounds
g_area = gdf_p.geometry.area.to_numpy()
a_min = float(np.nanmin(g_area[np.isfinite(g_area) & (g_area > 0.0)])) if np.any(
    g_area > 0.0
) else 0.0
# Lado de celda = raíz de área del polígono mín.
s = max(MIN_CELL_M, math.sqrt(a_min + 1e-6))
c_ll = gdf_p.geometry.centroid
cxg = c_ll.x.to_numpy()
cyg = c_ll.y.to_numpy()
del c_ll, gdf_p

spanx = max(xmax - xmin, 1e-6)
spany = max(ymax - ymin, 1e-6)
ncx = int(np.ceil(spanx / s))
nry = int(np.ceil(spany / s))
ncx = max(1, ncx)
nry = max(1, nry)

# Centroide a celda más cercana (centro de dicha celda)
ic, ir, x_snap, y_snap = _nearest_cell_indices(cxg, cyg, xmin, ymin, s, ncx, nry)
gdf["G_COL"] = ic
gdf["G_ROW"] = ir
gdf["S_XM"] = x_snap
gdf["S_YM"] = y_snap
gdf["G_STEP"] = float(s)
gdf["G_NCE"] = ncx
gdf["G_NFI"] = nry

# Morton sobre posición **en snapeada** (como 1) en bbox
morton = _morton_keys(x_snap, y_snap, xmin, ymin, xmax, ymax)

# ------------------------------
# 3. Boustrophedon (como 1) sobre filas reales; fila TM mayor y = más al norte
# ------------------------------
gdf = gdf.reset_index(drop=True)
n = len(gdf)
ic = gdf["G_COL"].to_numpy()
ir = gdf["G_ROW"].to_numpy()
x_sn = gdf["S_XM"].to_numpy()
y_sn = gdf["S_YM"].to_numpy()
morton = morton[:n]
START_NPN = int(os.environ.get("NPN_START", "1"))
STOP_NPN = int(os.environ.get("NPN_STOP", "9999"))
if START_NPN < 0 or STOP_NPN > 9999 or START_NPN > STOP_NPN:
    raise ValueError("Rango NPN invalido: use start/stop entre 0000 y 9999.")
available = (STOP_NPN - START_NPN) + 1
if n > min(MAX_NPN, available):
    raise ValueError(
        f"El rango NPN seleccionado ({START_NPN:04d}-{STOP_NPN:04d}) no alcanza para {n} poligonos."
    )

idx0 = np.arange(n, dtype=np.int64)
valid = (ic >= 0) & (ir >= 0)
INV = 1_000_000
u = np.sort(np.unique(ir[valid]))[::-1] if valid.any() else np.array([], dtype=np.int64)
row_rank = {v: k for k, v in enumerate(u)}
rkey = np.array(
    [row_rank[ir[i]] if valid[i] else INV for i in range(n)], dtype=np.int64
)
if valid.any():
    max_gc = int(np.max(ic[valid]))
    min_gc = int(np.min(ic[valid]))
    mxc = max_gc - min_gc
    even = (rkey % 2) == 0
    ckey = np.where(
        valid & even,
        ic,
        np.where(valid & ~even, mxc - (ic - min_gc), 0),
    ).astype(np.int64)
else:
    ckey = np.zeros(n, dtype=np.int64)
c_ll2 = gdf.geometry.centroid
c_lat = c_ll2.y.to_numpy()
c_lon = c_ll2.x.to_numpy()
c_lon2 = np.where(np.isfinite(c_lon), c_lon, 0.0)
even = (rkey % 2) == 0
c_lonT = np.where((rkey >= INV) | even, c_lon2, -c_lon2)

# Orden 1: boustrophedon + Morton (celda) + lat/lon; luego 3: rotar inicio a noroeste
m_base = np.lexsort(
    (idx0, c_lat, c_lonT, morton.astype(np.int64), ckey, rkey)
)
# Noroeste lex (lat, lon) sobre (lon,lat) de referencia
lat_v = gdf["lat"].to_numpy(dtype=np.float64)
lon_v = gdf["lon"].to_numpy(dtype=np.float64)
vl = np.isfinite(lat_v) & np.isfinite(lon_v)
c_lat2 = np.where(vl, lat_v, -np.inf)
c_lon2 = np.where(vl, lon_v, np.inf)
i_nw = int(np.lexsort((idx0, c_lon2, -c_lat2))[0])  # primero = noroeste
pos = int(np.argwhere(m_base == i_nw).ravel()[0])
m_fin = np.concatenate((m_base[pos:], m_base[:pos]))

gdf = gdf.iloc[m_fin].copy().reset_index(drop=True)
gdf["NEW_CODE"] = [f"{i:04d}" for i in range(START_NPN, START_NPN + n)]
gdf["E4_TIP"] = "grid_minA_boust_CW"
print(
    f"Estrategia4: s={s:.2f} m (sqrt de area min.={a_min:.1f} m2), celdas {ncx} x {nry}, "
    f"0001= noroeste (fila {i_nw}, rot {pos})"
)

# Polilínea: puntos en orden (usar snapeos en m)
x_m = gdf["S_XM"].to_numpy()
y_m = gdf["S_YM"].to_numpy()
line_m = gpd.GeoSeries(
    [Point(float(a), float(b)) for a, b in zip(x_m, y_m)],
    crs=GRID_CRS,
).to_crs("EPSG:4326")
line_xy = [(float(g.x), float(g.y)) for g in line_m]

out_poly = Path(OUTPUT_SHP)
out_lines = out_poly.with_name(out_poly.stem + "_newcode_path.shp")
if len(line_xy) >= 2:
    gpd.GeoDataFrame(
        data={"N_PTOS": [len(line_xy)]},
        geometry=[LineString(line_xy)],
        crs="EPSG:4326",
    ).to_file(out_lines, driver="ESRI Shapefile")
    print(f"Polilinea (puntos celdas snapeados): {out_lines}")

gdf.drop(columns=["lon", "lat"], errors="ignore").to_file(OUTPUT_SHP, driver="ESRI Shapefile")
print(f"Listo: {OUTPUT_SHP}")
