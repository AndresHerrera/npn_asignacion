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
OUTPUT_SHP = "terrenos_test_estrategia2.shp"
GRID_CRS = "EPSG:3115"  # MAGNA-SIRGAS / Colombia oeste; ajustar al ámbito
N_FRANJAS_FORZ = 0  # 0 = automático a partir de densidad * √n
# >1.0: más franjas (cada una más baja) → menos mezcla N–S *dentro* de la franja
FRANJAS_SOBRE_RAIZN = 2.0
# Micro-bandas horizontales *dentro* de cada franja (ver barrido 2D abajo)
MICROBANDAS_POR_FRANJA = 4


def _ref_lonlat(geom) -> Tuple[float, float]:
    """
    Punto de referencia interior (polígonos irregulares, agujeros, L, etc.):
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
# 3. Boustrophedon: franjas N→S; dentro de cada franja no usar solo X (easting),
#    porque con predios con variación en Y el trazo pica “en diente” N–S.
#    Añadimos micro-bandas N→S y barrido E–O en cada una (2D, sin Morton global).
# ------------------------------
gdf_prj = gdf.to_crs(GRID_CRS)
xmin, ymin, xmax, ymax = gdf_prj.total_bounds
del gdf_prj

n_feat = len(gdf)
if int(N_FRANJAS_FORZ) > 0:
    n_strips = max(1, int(N_FRANJAS_FORZ))
    if n_strips == 1 and n_feat >= 2:
        print(
            "Aviso: N_FRANJAS_FORZ=1 implica un solo sentido oeste->este; "
            "no es boustrophedon completo."
        )
elif n_feat >= 2:
    n_strips = int(round(FRANJAS_SOBRE_RAIZN * math.sqrt(float(n_feat))))
    n_strips = min(n_feat, max(2, n_strips))
else:
    n_strips = 1
span_y = max(float(ymax - ymin), 1e-6)
H = span_y / float(n_strips)

ref = gpd.GeoSeries(
    [Point(lon, lat) for lon, lat in zip(gdf["lon"], gdf["lat"])],
    crs="EPSG:4326",
).to_crs(GRID_CRS)
x = ref.x.to_numpy()
y = ref.y.to_numpy()
del ref

ok = np.isfinite(x) & np.isfinite(y)
c_prj = gdf.to_crs(GRID_CRS).geometry.centroid
cxf = c_prj.x.to_numpy()
cyf = c_prj.y.to_numpy()
x = np.where(ok, x, cxf)
y = np.where(ok, y, cyf)
ok2 = np.isfinite(x) & np.isfinite(y)

ibin = np.floor((y - ymin) / H).astype(np.int64)
ibin = np.clip(ibin, 0, n_strips - 1)
rkey = (n_strips - 1) - ibin
INV = 1_000_000
rkey = np.where(ok2, rkey, INV)
b_ok = ok2
if n_feat >= 2 and b_ok.sum() >= 2 and n_strips >= 2:
    mask_f = b_ok & (rkey < INV)
    n_used = int(len(np.unique(rkey[mask_f]))) if mask_f.any() else 0
    if n_used < 2:
        med = float(np.median(y[b_ok]))
        rkey = np.where(
            b_ok,
            np.where(y >= med, 0, 1).astype(np.int64),
            rkey,
        )
        n_strips = 2
        H = span_y / 2.0
        print(
            "Aviso: predios en una sola franja; corte N/S por mediana y (2 franjas)."
        )
del c_prj

gdf = gdf.reset_index(drop=True)
n = len(gdf)
rkey = rkey[:n]
x = x[:n]
y = y[:n]
ok2 = ok2[:n]

_nb = max(1, int(MICROBANDAS_POR_FRANJA))
print(
    f"Boustrophedon: n_franjas = {n_strips}  (~{n / n_strips:.1f} predios/franja), "
    f"microbandas/franja = {_nb}, n={n}, altura_franja = {H:.1f} m en GRID_CRS)"
)

# ------------------------------
# 4–5. NEW_CODE: rkey = franjas N→S; y_tier = micro-bandas N→S *dentro*; x = E–O según
#      paridad (2*rkey*mb + y_tier) para que el barrido 2D no “suba y baje” en Y solo
#      por el orden de X (diente N–S en la polilínea).
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
if len(rkey) != n:
    raise ValueError("Inconsistencia filas / puntos de referencia.")

idx0 = np.arange(n, dtype=np.int64)
mb = _nb
# Fila 0 = más al norte (y mayor) dentro de la franja; columna: este (X)
y_tier = np.zeros(n, dtype=np.int64)
for k in range(int(n_strips)):
    m = (rkey == k) & (rkey < INV)
    if not np.any(m):
        continue
    yy = y[m]
    y_lo, y_hi = float(np.min(yy)), float(np.max(yy))
    h_t = (y_hi - y_lo) / float(mb) + 1e-6
    # tier 0 = y alto (norte) en el predio, mb-1 = sur
    y_tier[m] = np.floor((y_hi - y[m]) / h_t).astype(np.int64)
    y_tier[m] = np.clip(y_tier[m], 0, mb - 1)
# Trazo: franja, luego N→S en micro-bandas, luego E–O según boustrophedon en (franja*mb + tier)
sweep = 2 * rkey * mb + y_tier
sweep = np.where(rkey < INV, sweep, 10**12)
even_sweep = (sweep % 2) == 0
x_key = np.where((rkey >= INV) | even_sweep, x, -x)
m_ord = np.lexsort((idx0, x_key, y_tier, rkey))

gdf = gdf.iloc[m_ord].copy().reset_index(drop=True)
gdf["NEW_CODE"] = [f"{i:04d}" for i in range(START_NPN, START_NPN + n)]
gdf["F_STRP"] = rkey[m_ord]
gdf["N_FRJ"] = np.int32(n_strips)

# Secuencia de puntos **mismas** (x,y) que definen el orden (polilínea coherente con el barrido)
x_seq = x[m_ord]
y_seq = y[m_ord]
line_prj = gpd.GeoSeries(
    [Point(float(a), float(b)) for a, b in zip(x_seq, y_seq)],
    crs=GRID_CRS,
).to_crs("EPSG:4326")
line_xy = [(float(g.x), float(g.y)) for g in line_prj]

# ------------------------------
# 6. Polilínea = trazo suave O–E / E–O por franja (sin saltos Z)
# ------------------------------
out_poly = Path(OUTPUT_SHP)
out_lines = out_poly.with_name(out_poly.stem + "_newcode_path.shp")

if len(line_xy) >= 2:
    gdf_lines = gpd.GeoDataFrame(
        data={"N_PTOS": [len(line_xy)]},
        geometry=[LineString(line_xy)],
        crs="EPSG:4326",
    )
    gdf_lines.to_file(out_lines, driver="ESRI Shapefile")
    print(f"Capa de lineas (secuencia NEW_CODE, X monotono por franja): {out_lines}")
else:
    print("Aviso: no se genero la capa de lineas (faltan puntos).")

# ------------------------------
# 7. Save to new shapefile
# ------------------------------
gdf_out = gdf.drop(
    columns=["lon", "lat"],
    errors="ignore",
)
gdf_out.to_file(OUTPUT_SHP, driver="ESRI Shapefile")

print(f"Done. New shapefile saved as {OUTPUT_SHP}")
