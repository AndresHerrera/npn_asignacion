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
OUTPUT_SHP = "terrenos_test_estrategia1.shp"
# 0.0 o negativo: tamaño de celda automático (pauta según empaque del ámbito y n)
GRID_CELL_M = 0.0
GRID_CRS = "EPSG:3115"  # MAGNA-SIRGAS / Colombia oeste; cambiar según el ámbito
# Escala: ~0.3–0.7 = “varias” celdas en el lote; mayor = celdas más gruesas
AUTO_CELL_FRACTION = 0.45
# Piso/ techo (metros) del automático, para no degenerar
AUTO_CELL_MIN_M = 10.0
AUTO_CELL_MAX_M = 500.0


def _ref_lonlat(geom) -> Tuple[float, float]:
    """
    Punto de referencia interior (robusto en polígonos irregulares, agujeros, L, etc.):
    representative_point; si no aplica, centroide.
    """
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
    """Intercala 16 bits (x) e (y) en un entero: orden Z / Morton en cuadrante."""
    x = int(ix) & 0xFFFF
    y = int(iy) & 0xFFFF
    z = 0
    for b in range(16):
        z |= ((x >> b) & 1) << (2 * b)
        z |= ((y >> b) & 1) << (2 * b + 1)
    return int(z)


def _morton_keys(
    x: np.ndarray,
    y: np.ndarray,
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
) -> np.ndarray:
    w = max(float(xmax - xmin), 1e-6)
    h = max(float(ymax - ymin), 1e-6)
    nx = (np.clip((x - xmin) / w, 0.0, 1.0) * 65535.0).astype(np.int64)
    ny = (np.clip((y - ymin) / h, 0.0, 1.0) * 65535.0).astype(np.int64)
    m = np.zeros(len(x), dtype=np.int64)
    for i in range(len(x)):
        m[i] = _morton16(int(nx[i]), int(ny[i]))
    return m


# ------------------------------
# 1. Load parcel data
# ------------------------------
gdf = gpd.read_file(INPUT_SHP)
if gdf.crs is None:
    raise ValueError("Shapefile has no CRS. Please assign one.")
gdf = gdf.to_crs("EPSG:4326")  # WGS84

# ------------------------------
# 2. Punto de referencia (interior) por predio
# ------------------------------
_ref = gdf.geometry.apply(_ref_lonlat)
gdf["lon"] = _ref.apply(lambda t: t[0])
gdf["lat"] = _ref.apply(lambda t: t[1])
del _ref

# ------------------------------
# 3. Grilla: coordenadas en GRID_CRS y tamaño de celda
# ------------------------------
gdf_prj = gdf.to_crs(GRID_CRS)
xmin, ymin, xmax, ymax = gdf_prj.total_bounds
n_feat = len(gdf)
a_box = max((xmax - xmin) * (ymax - ymin), 0.0)
s = float(GRID_CELL_M) if float(GRID_CELL_M) > 0.0 else 0.0
if s <= 0.0 and n_feat > 0 and a_box > 0.0:
    s = min(
        AUTO_CELL_MAX_M,
        max(
            AUTO_CELL_MIN_M,
            math.sqrt(a_box / float(n_feat)) * AUTO_CELL_FRACTION,
        ),
    )
    print(f"GRID_CELL_M (auto) = {s:.2f} m  (caja ~{math.sqrt(a_box):.0f} m de lado, n={n_feat})")
elif s <= 0.0:
    s = max(AUTO_CELL_MIN_M, 50.0)
    print(f"GRID_CELL_M (respaldo) = {s:.2f} m")

ref = gpd.GeoSeries(
    [Point(lon, lat) for lon, lat in zip(gdf["lon"], gdf["lat"])],
    crs="EPSG:4326",
).to_crs(GRID_CRS)
x = ref.x.to_numpy()
y = ref.y.to_numpy()
del gdf_prj, ref
morton_all = _morton_keys(x, y, xmin, ymin, xmax, ymax)

dxi = (x - xmin) / s
dyi = (y - ymin) / s
ok = np.isfinite(dxi) & np.isfinite(dyi) & (s > 0.0) & np.isfinite(x) & np.isfinite(y)
gcol = np.full(len(gdf), -1, dtype=np.int64)
grow = np.full(len(gdf), -1, dtype=np.int64)
gcol[ok] = np.floor(dxi[ok]).astype(np.int64)
grow[ok] = np.floor(dyi[ok]).astype(np.int64)

# Respaldo: centroide en GRID_CRS si (lon,lat) o celda quedan inválidos
c_prj = gdf.to_crs(GRID_CRS).geometry.centroid
cxf = c_prj.x.to_numpy()
cyf = c_prj.y.to_numpy()
okf = np.isfinite(cxf) & np.isfinite(cyf) & (s > 0.0)
b_fill = (gcol < 0) | (grow < 0) | ~ok
gcol2 = gcol.copy()
grow2 = grow.copy()
if np.any(b_fill & okf):
    dxi_f = (cxf - xmin) / s
    dyi_f = (cyf - ymin) / s
    ok2 = b_fill & okf & np.isfinite(dxi_f) & np.isfinite(dyi_f)
    gcol2[ok2] = np.floor(dxi_f[ok2]).astype(np.int64)
    grow2[ok2] = np.floor(dyi_f[ok2]).astype(np.int64)
gdf["G_COL"] = gcol2
gdf["G_ROW"] = grow2
del c_prj

# ------------------------------
# 4–5. NEW_CODE: zig-zag N→S + desempate Morton (vecinos 2D en formas irregulares)
# (x, y, morton_all ya alinean con el orden de filas de gdf)
# ------------------------------
START_NPN = int(os.environ.get("NPN_START", "1"))
STOP_NPN = int(os.environ.get("NPN_STOP", "9999"))
if START_NPN < 0 or STOP_NPN > 9999 or START_NPN > STOP_NPN:
    raise ValueError("Rango NPN invalido: use start/stop entre 0000 y 9999.")
gdf = gdf.reset_index(drop=True)
n = len(gdf)
available = (STOP_NPN - START_NPN) + 1
if n > available:
    raise ValueError(
        f"El rango NPN seleccionado ({START_NPN:04d}-{STOP_NPN:04d}) no alcanza para {n} poligonos."
    )
if len(x) != n or len(morton_all) != n:
    raise ValueError("Inconsistencia filas / puntos de referencia.")

gr = gdf["G_ROW"].to_numpy()
gc = gdf["G_COL"].to_numpy()
c_ll = gdf.geometry.centroid
c_lat = c_ll.y.to_numpy()
c_lon = c_ll.x.to_numpy()
idx0 = np.arange(n, dtype=np.int64)
valid = (gr >= 0) & (gc >= 0)
INV = 1_000_000
u = np.sort(np.unique(gr[valid]))[::-1] if valid.any() else np.array([], dtype=np.int64)
row_id_to_rank = {v: k for k, v in enumerate(u)}
rkey = np.array(
    [row_id_to_rank[gr[i]] if valid[i] else INV for i in range(n)],
    dtype=np.int64,
)
if valid.any():
    max_gc = int(np.max(gc[valid]))
    min_gc = int(np.min(gc[valid]))
    mxc = max_gc - min_gc
    even = (rkey % 2) == 0
    ckey = np.where(
        valid & even,
        gc,
        np.where(valid & ~even, mxc - (gc - min_gc), 0),
    ).astype(np.int64)
else:
    ckey = np.zeros(n, dtype=np.int64)
c_lon2 = np.where(np.isfinite(c_lon), c_lon, 0.0)
even = (rkey % 2) == 0
c_lonT = np.where((rkey >= INV) | even, c_lon2, -c_lon2)
# Boustrophedon + Morton dentro de la misma (fila, col) para predios apretados/irregulares
m_ord = np.lexsort(
    (idx0, c_lat, c_lonT, morton_all.astype(np.int64), ckey, rkey)
)

gdf = gdf.iloc[m_ord].copy().reset_index(drop=True)
gdf["NEW_CODE"] = [f"{i:04d}" for i in range(START_NPN, START_NPN + n)]

# ------------------------------
# 6. Capa de lineas: secuencia NEW_CODE; puntos = mismo criterio que la grilla
# ------------------------------
out_poly = Path(OUTPUT_SHP)
out_lines = out_poly.with_name(out_poly.stem + "_newcode_path.shp")

path_df = gdf.sort_values("NEW_CODE", kind="mergesort")
path_df = path_df.loc[~path_df.geometry.is_empty]
coords = []
for _idx, row in path_df.iterrows():
    g = row.geometry
    p = g.representative_point() if g is not None and not g.is_empty else None
    if p is not None and not p.is_empty:
        x, y = float(p.x), float(p.y)
    else:
        c = g.centroid
        if c is None or c.is_empty:
            continue
        x, y = c.x, c.y
    if math.isfinite(x) and math.isfinite(y):
        coords.append((x, y))

if len(coords) >= 2:
    gdf_lines = gpd.GeoDataFrame(
        data={"N_PTOS": [len(coords)]},
        geometry=[LineString(coords)],
        crs=gdf.crs,
    )
    gdf_lines.to_file(out_lines, driver="ESRI Shapefile")
    print(f"Capa de lineas (secuencia NEW_CODE): {out_lines}")
else:
    print(
        "Aviso: se necesitan al menos 2 predios con representante/punto valido; "
        "no se genero la capa de lineas."
    )

# ------------------------------
# 7. Save to new shapefile
# ------------------------------
gdf_out = gdf.drop(
    columns=["lon", "lat"],
    errors="ignore",
)
gdf_out.to_file(OUTPUT_SHP, driver="ESRI Shapefile")

print(f"Done. New shapefile saved as {OUTPUT_SHP}")
