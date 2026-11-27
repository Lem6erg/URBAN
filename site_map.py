"""Зйомка DXF/DWG → місце на Google Maps (ТЗ Markdown/urban_site_map_spec.md). Без tkinter і без мережі:
модуль лише обчислює координати й посилання; браузер відкриває GUI за кнопкою.

Використання: python site_map.py "зйомка.dxf|dwg" ["система"]
Створено 27.11.2026 (CLAUDE)."""
import os, sys, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crs

UNITS = (1.0, 0.001)  # метри; мм (експорт Archicad без масштабу)

# СК-63, зони X (захід України) — ЛИШЕ для мітки на карті, наближено. Параметри відкриті: EPSG:7825–7827
# (ТМ, Красовський, φ0 = 0°05′), перехід Пулково-42 → WGS-84 — TOWGS84 з EPSG (точність кілька метрів).
# До crs_keys.json не додаються: точний перерахунок СК-63 — лише за офіційним ключем.
SK63 = {'СК-63, зона X%d (наближено)' % z: dict(ellipsoid='krassowsky', lon0=lon0, lat0=1 / 12.0, k0=1, fe=fe, fn=0,
                                               west=w, east=e)
        for z, lon0, fe, w, e in ((1, 23.5, 1300000, 22.0, 25.0), (2, 26.5, 2300000, 25.0, 28.0), (3, 29.5, 3300000, 28.0, 31.0))}
TOWGS84 = dict(dx=23.57, dy=-140.95, dz=-79.8, rx=0.0, ry=-0.35, rz=-0.79, ds=-0.22, convention='position')


def sk63_geo(E, N, p):
    """СК-63 (плоскі) → WGS-84 широта, довгота (наближено)."""
    lat, lon = crs.tm_inverse(E, N, p)
    X, Y, Z = crs._geo2xyz(lat, lon, 0.0, 'krassowsky')
    X, Y, Z = crs._helmert(X, Y, Z, TOWGS84)
    lat, lon, _ = crs._xyz2geo(X, Y, Z, 'wgs84')
    return lat, lon


def sk63_guess(E, N):
    for n, p in SK63.items():
        if not (p['fe'] - 5e5 < E < p['fe'] + 5e5): continue
        try: lat, lon = sk63_geo(E, N, p)
        except (ValueError, OverflowError, ZeroDivisionError): continue
        if crs.UA[0] <= lat <= crs.UA[1] and p['west'] - 0.3 <= lon <= p['east'] + 0.3: return n, lat, lon
    return None


def dxf_points(path):
    """Усі пари 10/20 і 11/21 розділу ENTITIES (ASCII DXF). Блоки (BLOCKS) не беруться — там локальні координати."""
    L = open(path, encoding='cp1251', errors='replace').read().split('\n')
    sec, pts, x = None, [], {}
    for i in range(0, len(L) - 1, 2):
        c, v = L[i].strip(), L[i + 1].strip()
        if c == '0':
            if v == 'SECTION': sec = None
            x = {}
            continue
        if c == '2' and sec is None: sec = v; continue
        if sec != 'ENTITIES': continue
        if c in ('10', '11'):
            try: x[c] = float(v)
            except ValueError: x.pop(c, None)
        elif c in ('20', '21') and str(int(c) - 10) in x:
            try: pts.append((x.pop(str(int(c) - 10)), float(v)))
            except ValueError: pass
    if not pts and L and L[0].startswith('AutoCAD Binary DXF'):
        raise ValueError('двійковий DXF не підтримується — збережіть як ASCII DXF')
    return pts


def dwg_points(path):
    import dwgread
    with open(path, 'rb') as f: ver = f.read(6).decode('ascii', 'replace')
    if ver < 'AC1018' or ver == 'AC1021':
        raise ValueError('DWG версії %s не читається (потрібен DWG 2004, 2010–2018) — збережіть як DXF' % ver)
    try: ver, out, layers, errs = dwgread.parse(path, 0)
    except Exception as e:
        raise ValueError('не вдалося прочитати DWG %s (%s) — збережіть як DXF' % (ver, type(e).__name__))
    pts = []
    for e in out:
        for p in e.get('pts') or []:
            if len(p) >= 2 and all(isinstance(v, (int, float)) for v in p[:2]): pts.append((float(p[0]), float(p[1])))
    return pts


def points(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == '.dxf': pts = dxf_points(path)
    elif ext == '.dwg': pts = dwg_points(path)
    else: raise ValueError('потрібен DXF або DWG')
    P = np.array([p for p in pts if all(map(math.isfinite, p)) and (abs(p[0]) > 1e-9 or abs(p[1]) > 1e-9)])
    if not len(P): raise ValueError('у файлі немає координат об\'єктів')
    return P


def locate(path, system=None):
    """Центр зйомки (медіана вершин) → система координат → широта/довгота.
    system=None — визначити автоматично (crs.guess); інакше — проєкція з crs_keys.json.
    Повертає dict(lat, lon, system, k, E, N, span, n, others)."""
    P = points(path)
    c = np.median(P, 0)
    # відкинути далекі від медіани (елементи блоків у локальних координатах, випадкові об'єкти біля нуля)
    far = np.abs(P - c).max(1); near = P[far <= max(20000.0, 20 * float(np.median(far)))]
    if len(near) >= 0.5 * len(P): P = near
    lo, hi = P.min(0), P.max(0)  # далекі точки вже відкинуто
    c = (lo + hi) / 2  # центр зйомки — середина охоплення
    span = float(max(hi - lo))
    PR = crs.load_proj()
    for k in UNITS:
        E, N = float(c[0] * k), float(c[1] * k)
        if system:
            if system not in PR and system not in SK63: raise ValueError('система «%s» не є проєкцією з crs_keys.json' % system)
            try: lat, lon = sk63_geo(E, N, SK63[system]) if system in SK63 else crs.tm_inverse(E, N, PR[system])
            except (ValueError, OverflowError, ZeroDivisionError): continue
            if crs.UA[0] <= lat <= crs.UA[1] and crs.UA[2] <= lon <= crs.UA[3]:
                return dict(lat=lat, lon=lon, system=system, k=k, E=E, N=N, span=span * k, n=len(P), others=[])
            continue
        g = crs.guess(E, N)
        if g:
            name, _, lat, lon = g[0]
            return dict(lat=lat, lon=lon, system=name, k=k, E=E, N=N, span=span * k, n=len(P), others=[x[0] for x in g[1:]])
        g = sk63_guess(E, N)
        if g:
            return dict(lat=g[1], lon=g[2], system=g[0], k=k, E=E, N=N, span=span * k, n=len(P), others=[])
    raise ValueError('координати не схожі на жодну відому систему (МСК, УСК-2000, СК-63) у межах України (центр %.2f %.2f) — '
                     'імовірно, локальні координати; виберіть систему вручну' % (c[0], c[1]) if not system else
                     'у системі «%s» центр зйомки (%.2f %.2f) не потрапляє в Україну' % (system, c[0], c[1]))


def systems():
    """Вибір системи вручну: проєкції crs_keys.json + СК-63 (наближено, лише для карти)."""
    return list(crs.load_proj()) + list(SK63)


def zoom(span, lat, px=900):
    """Масштаб Google Maps, щоб зйомка (span, м) вмістилась у ~px пікселів."""
    span = max(span, 150.0)
    z = math.log2(156543.03392 * math.cos(math.radians(lat)) * px / span)
    return int(max(3, min(19, math.floor(z))))


def gmaps_url(lat, lon, span=300.0):
    return 'https://www.google.com/maps/place/%.6f,%.6f/@%.6f,%.6f,%dz' % (lat, lon, lat, lon, zoom(span, lat))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    r = locate(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print('%s: %.6f, %.6f (одиниці ×%g, вершин %d, охоплення %.0f м)' % (r['system'], r['lat'], r['lon'], r['k'], r['n'], r['span']))
    print(gmaps_url(r['lat'], r['lon'], r['span']))
