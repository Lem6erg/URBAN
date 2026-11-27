"""Система координат ↔ WGS-84 (широта, довгота) — спільне для «Локації», KML ↔ DXF і калькулятора
(ТЗ Markdown/urban_geo_tools_spec.md, Р5). Координати в DXF-порядку: E (схід), N (північ).

- Проєкції crs_keys.json з основою УСК-2000: ТМ → широта/довгота на своєму еліпсоїді → геоцентричні XYZ →
  WGS-84. УСК-2000 вважається геоцентричною (≈ ITRF; розбіжність з WGS-84 до ~1 м).
- СК-63 зони X1–X3 — наближено: EPSG:7825–7827 + TOWGS84 з EPSG (кілька метрів). Лише для пошуку й карти.
- Системи, що є лише в ключах (напр. СК-63 за пунктами): ключ → проєкція УСК-2000 → WGS-84.
Створено 27.11.2026 (CLAUDE)."""
import crs

WGS = 'WGS-84 (широта, довгота)'

# СК-63, зони X (захід України) — наближено. Параметри EPSG:7825–7827 (ТМ, Красовський, φ0 = 0°05′).
SK63 = {'СК-63, зона X%d (наближено)' % z: dict(ellipsoid='krassowsky', lon0=lon0, lat0=1 / 12.0, k0=1, fe=fe, fn=0,
                                               west=w, east=e)
        for z, lon0, fe, w, e in ((1, 23.5, 1300000, 22.0, 25.0), (2, 26.5, 2300000, 25.0, 28.0), (3, 29.5, 3300000, 28.0, 31.0))}
TOWGS84 = dict(dx=23.57, dy=-140.95, dz=-79.8, rx=0.0, ry=-0.35, rz=-0.79, ds=-0.22, convention='position')


def _ell_of(p):
    return p.get('ellipsoid', 'krassowsky')


def _proj_to_wgs(E, N, p):
    lat, lon = crs.tm_inverse(E, N, p)
    X, Y, Z = crs._geo2xyz(lat, lon, 0.0, _ell_of(p))
    lat, lon, _ = crs._xyz2geo(X, Y, Z, 'wgs84')
    return lat, lon


def _wgs_to_proj(lat, lon, p):
    X, Y, Z = crs._geo2xyz(lat, lon, 0.0, 'wgs84')
    lat, lon, _ = crs._xyz2geo(X, Y, Z, _ell_of(p))
    return crs.tm_forward(lat, lon, p)


def _sk63_to_wgs(E, N, p):
    lat, lon = crs.tm_inverse(E, N, p)
    X, Y, Z = crs._geo2xyz(lat, lon, 0.0, 'krassowsky')
    X, Y, Z = crs._helmert(X, Y, Z, TOWGS84)
    lat, lon, _ = crs._xyz2geo(X, Y, Z, 'wgs84')
    return lat, lon


def _wgs_to_sk63(lat, lon, p):
    X, Y, Z = crs._geo2xyz(lat, lon, 0.0, 'wgs84')
    X, Y, Z = crs._helmert(X, Y, Z, TOWGS84, inverse=True)
    lat, lon, _ = crs._xyz2geo(X, Y, Z, 'krassowsky')
    return crs.tm_forward(lat, lon, p)


def systems(approx=True):
    """Усі системи: проєкції й ключі crs_keys.json + (approx) СК-63 наближено."""
    s = list(crs.systems())
    if approx: s += [n for n in SK63 if n not in s]
    return s


def _via(name):
    """Для системи лише з ключем: (до проєкції, від проєкції, назва проєкції)."""
    PR = crs.load_proj()
    for mid in PR:
        try:
            f, g = crs.transformer(name, mid), crs.transformer(mid, name)
            if f and g: return f, g, PR[mid]
        except KeyError:
            continue
    raise KeyError('Немає ключа, що зв\'язує «%s» з УСК-2000' % name)


def to_wgs(name, E, N):
    """(E, N) у системі name → (широта, довгота) WGS-84."""
    PR = crs.load_proj()
    if name in PR: return _proj_to_wgs(E, N, PR[name])
    if name in SK63: return _sk63_to_wgs(E, N, SK63[name])
    f, _, p = _via(name); return _proj_to_wgs(*f(E, N), p)


def from_wgs(name, lat, lon):
    """(широта, довгота) WGS-84 → (E, N) у системі name."""
    PR = crs.load_proj()
    if name in PR: return _wgs_to_proj(lat, lon, PR[name])
    if name in SK63: return _wgs_to_sk63(lat, lon, SK63[name])
    _, g, p = _via(name); return g(*_wgs_to_proj(lat, lon, p))


def is_approx(name):
    return name in SK63


def converter(src, dst):
    """Функція (a, b) → (a', b'). Для WGS — (широта, довгота); для решти — (E, N).
    Точний шлях crs.transformer — перевага; інакше через WGS-84."""
    if src == dst: return lambda a, b: (a, b)
    if src == WGS: return lambda lat, lon: from_wgs(dst, lat, lon)
    if dst == WGS: return lambda E, N: to_wgs(src, E, N)
    if src not in SK63 and dst not in SK63:
        try:
            f = crs.transformer(src, dst)
            if f: return f
        except KeyError:
            pass
    return lambda E, N: from_wgs(dst, *to_wgs(src, E, N))
