"""Локація: межа ДПТ → KML (Google Earth) і відстані ЦЗ по дорогах (ТЗ Markdown/urban_pz_cadastre_cz_spec.md, Р5–Р7).
Відстані: укриття (точки шару DXF/DWG і OSM shelter_type=bomb_shelter) — пішки; пожежна частина, лікарня / швидка — авто.
Джерела: OSM Overpass (об'єкти), OSRM (маршрути), Nominatim (адреси). У мережу йдуть лише координати WGS-84.
Створено 27.11.2026 (CLAUDE)."""
import os, re, math, json, time, urllib.request, urllib.parse
from xml.sax.saxutils import escape
import numpy as np
import geo, site_map, kml_dxf
from pdf_raster import unique

UA = {'User-Agent': 'URBAN-desktop/1.2 (https://github.com/Lem6erg/URBAN)'}
OVERPASS = ['https://maps.mail.ru/osm/tools/overpass/api/interpreter', 'https://overpass-api.de/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter', 'https://overpass.private.coffee/api/interpreter']
OSRM = {'car': 'https://router.project-osrm.org/route/v1/driving/',
        'foot': 'https://routing.openstreetmap.de/routed-foot/route/v1/driving/'}
NOMINATIM = 'https://nominatim.openstreetmap.org/reverse'
# тип → (підпис, профіль маршруту, радіус пошуку OSM, м, фільтри Overpass)
KINDS = {'shelter_dxf': ('Укриття (зі зйомки)', 'foot', 0, []),
         'shelter_osm': ('Укриття (OSM)', 'foot', 3000, ['["shelter_type"="bomb_shelter"]']),
         'fire': ('Пожежна частина', 'car', 25000, ['["amenity"="fire_station"]']),
         'hospital': ('Лікарня / швидка', 'car', 25000, ['["amenity"="hospital"]', '["emergency"="ambulance_station"]'])}
NEAREST = 3


# ---------- шари зйомки ----------
def _dxf_marks(path):
    """ASCII DXF: POINT / INSERT / CIRCLE у ENTITIES → [(шар, E, N)]."""
    with open(path, encoding='cp1251', errors='replace') as fh: L = fh.read().split('\n')
    out, sec, cur = [], None, None
    for i in range(0, len(L) - 1, 2):
        c, v = L[i].strip(), L[i + 1].strip()
        if c == '0':
            if cur and 'x' in cur and 'y' in cur: out.append((cur['l'], cur['x'], cur['y']))
            cur = dict(l='0') if sec == 'ENTITIES' and v in ('POINT', 'INSERT', 'CIRCLE') else None
            continue
        if c == '2' and v in ('ENTITIES', 'BLOCKS', 'TABLES', 'HEADER', 'OBJECTS', 'CLASSES'): sec = v
        if cur is None: continue
        if c == '8': cur['l'] = v
        elif c == '10' and 'x' not in cur: cur['x'] = float(v)
        elif c == '20' and 'y' not in cur: cur['y'] = float(v)
    return out


def objects(path):
    """→ [dict(kind='line'|'mark', layer, pts, closed)] для DXF/DWG."""
    if path.lower().endswith('.dwg'):
        site_map.dwg_points(path)
        import dwgread
        _, ents, _, _ = dwgread.parse(path, 0); res = []
        for e in ents:
            t = e.get('t'); lay = e.get('layer', '0').rstrip('\x00')
            pts = [tuple(map(float, p[:2])) for p in (e.get('pts') or []) if len(p) >= 2]
            if not pts: continue
            if t in (27, 7, 18): res.append(dict(kind='mark', layer=lay, pts=pts[:1], closed=False))
            elif t in (19, 77, 16) and len(pts) >= 2: res.append(dict(kind='line', layer=lay, pts=pts, closed=bool(e.get('closed'))))
        return res
    res = [dict(o, kind='line') for o in kml_dxf.dxf_objects(path) if o['kind'] == 'line']
    res += [dict(kind='mark', layer=l, pts=[(x, y)], closed=False) for l, x, y in _dxf_marks(path)]
    return res


def _closed(o):
    P = o['pts']
    return o['kind'] == 'line' and len(P) >= 3 and (o['closed'] or (abs(P[0][0] - P[-1][0]) < 1e-6 and abs(P[0][1] - P[-1][1]) < 1e-6))


def layers(path):
    """→ {шар: (замкнених контурів, об'єктів усього)}."""
    out = {}
    for o in objects(path):
        a, b = out.get(o['layer'], (0, 0)); out[o['layer']] = (a + _closed(o), b + 1)
    return out


def _area(P):
    return abs(sum(P[i][0] * P[i - 1][1] - P[i - 1][0] * P[i][1] for i in range(len(P)))) / 2


def _centroid(P):
    A = 0; cx = cy = 0
    for i in range(len(P)):
        x0, y0 = P[i - 1]; x1, y1 = P[i]; c = x0 * y1 - x1 * y0; A += c; cx += (x0 + x1) * c; cy += (y0 + y1) * c
    if abs(A) < 1e-9: return tuple(np.mean(P, 0))
    return cx / (3 * A), cy / (3 * A)


def rings(objs, layer):
    R = []
    for o in objs:
        if o['layer'] == layer and _closed(o):
            P = list(o['pts'])
            if len(P) > 3 and abs(P[0][0] - P[-1][0]) < 1e-6 and abs(P[0][1] - P[-1][1]) < 1e-6: P = P[:-1]
            R.append(P)
    return R


# ---------- межа → KML ----------
def boundary_kml(path, layer, system=None):
    """Замкнені контури шару → «<назва> (межа).kml». → (шлях, система, кількість, площа м²)."""
    loc = site_map.locate(path, system); k = loc['k']; sysn = loc['system']
    R = rings(objects(path), layer)
    if not R: raise ValueError('на шарі «%s» немає замкнених контурів' % layer)
    f = geo.converter(sysn, geo.WGS)
    k_ = ['<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
          '<name>%s</name><Style id="b"><LineStyle><color>ff0000ff</color><width>3</width></LineStyle>'
          '<PolyStyle><color>330000ff</color></PolyStyle></Style>' % escape(os.path.basename(path) + ' — межа')]
    total = 0.0
    for i, P in enumerate(sorted(R, key=_area, reverse=True), 1):
        a = _area(P) * k * k; total += a
        ll = [f(x * k, y * k) for x, y in P] + [f(P[0][0] * k, P[0][1] * k)]
        cs = ' '.join('%.8f,%.8f,0' % (lo, la) for la, lo in ll)
        k_.append('<Placemark><name>Межа %d</name><description>Площа %.4f га (%.0f м²), %s</description><styleUrl>#b</styleUrl>'
                  '<Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing><coordinates>%s</coordinates></LinearRing>'
                  '</outerBoundaryIs></Polygon></Placemark>' % (i, a / 10000, a, escape(sysn), cs))
    k_.append('</Document></kml>\n')
    dst = unique(os.path.splitext(path)[0] + ' (межа).kml')
    with open(dst, 'w', encoding='utf-8') as fh: fh.write(''.join(k_))
    return dst, sysn, len(R), total


# ---------- мережа ----------
def _get(url, data=None, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=UA), timeout=timeout) as f:
        return json.loads(f.read().decode('utf-8'))


def haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def osm_objects(lat, lon, kinds, log=print):
    """Overpass: об'єкти потрібних типів навколо точки → {тип: [dict(name, lat, lon, addr)]}. Перебір дзеркал."""
    parts = ''.join('nwr%s(around:%d,%.6f,%.6f);' % (flt, KINDS[k][2], lat, lon) for k in kinds for flt in KINDS[k][3])
    q = '[out:json][timeout:40];(%s);out center tags;' % parts
    err = None
    for url in OVERPASS:
        try:
            js = _get(url, urllib.parse.urlencode({'data': q}).encode(), timeout=45); break
        except Exception as e:
            err = e; log('   Overpass %s: %s' % (url.split('/')[2], str(e)[:60]))
    else:
        raise RuntimeError('OSM Overpass недоступний (%s) — спробуйте пізніше' % err)
    out = {k: [] for k in kinds}
    for el in js.get('elements', []):
        t = el.get('tags', {}); c = el.get('center') or el
        if 'lat' not in c: continue
        if t.get('amenity') == 'fire_station': k = 'fire'
        elif t.get('amenity') == 'hospital' or t.get('emergency') == 'ambulance_station': k = 'hospital'
        elif t.get('shelter_type') == 'bomb_shelter': k = 'shelter_osm'
        else: continue
        if k not in out: continue
        addr = ', '.join(x for x in (t.get('addr:city') or t.get('addr:place'), t.get('addr:street'), t.get('addr:housenumber')) if x)
        out[k].append(dict(name=t.get('name:uk') or t.get('name') or KINDS[k][0], lat=c['lat'], lon=c['lon'], addr=addr))
    return out


def route(profile, a, b):
    """OSRM: a, b = (lat, lon) → dict(m, s, line=[(lat, lon)])."""
    url = OSRM[profile] + '%.6f,%.6f;%.6f,%.6f?overview=full&geometries=geojson' % (a[1], a[0], b[1], b[0])
    js = _get(url, timeout=30)
    if js.get('code') != 'Ok' or not js.get('routes'): raise RuntimeError('маршрут не знайдено (%s)' % js.get('code'))
    r = js['routes'][0]
    return dict(m=r['distance'], s=r['duration'], line=[(la, lo) for lo, la in r['geometry']['coordinates']])


def address(lat, lon):
    """Nominatim reverse → «місто, вулиця, будинок» (≤ 1 запит/с — пауза в caller)."""
    js = _get(NOMINATIM + '?' + urllib.parse.urlencode(dict(format='jsonv2', lat='%.6f' % lat, lon='%.6f' % lon, zoom=18,
                                                              **{'accept-language': 'uk'})), timeout=20)
    a = js.get('address', {})
    city = a.get('city') or a.get('town') or a.get('village') or a.get('hamlet') or ''
    return ', '.join(x for x in (city, a.get('road') or a.get('pedestrian') or '', a.get('house_number') or '') if x) \
        or js.get('display_name', '')[:80]


# ---------- ЦЗ ----------
def compute(path, kinds, system=None, boundary_layer=None, shelter_layer=None, log=print, progress=None):
    """Відстані ЦЗ від центру межі (або зйомки). → dict(txt, dxf, rows)."""
    loc = site_map.locate(path, system); k = loc['k']; sysn = loc['system']
    objs = objects(path); to_w = geo.converter(sysn, geo.WGS); from_w = geo.converter(geo.WGS, sysn)
    if boundary_layer:
        R = rings(objs, boundary_layer)
        if not R: raise ValueError('на шарі «%s» немає замкнених контурів' % boundary_layer)
        E0, N0 = _centroid(max(R, key=_area)); E0 *= k; N0 *= k; src = 'центр межі (шар «%s»)' % boundary_layer
    else:
        E0, N0, src = loc['E'], loc['N'], 'центр зйомки'
    o = to_w(E0, N0)
    log('   відлік: %s — %.6f, %.6f' % (src, o[0], o[1]))
    cand = {kk: [] for kk in kinds}
    if 'shelter_dxf' in kinds:
        if not shelter_layer: raise ValueError('виберіть шар укриттів')
        for ob in objs:
            if ob['layer'] != shelter_layer: continue
            P = ob['pts']; c = _centroid(P) if _closed(ob) else tuple(np.mean(P, 0))
            la, lo = to_w(c[0] * k, c[1] * k); cand['shelter_dxf'].append(dict(name='Укриття', lat=la, lon=lo, addr=''))
        if not cand['shelter_dxf']: log('УВАГА: на шарі «%s» немає об\'єктів' % shelter_layer)
    osm = [kk for kk in kinds if kk != 'shelter_dxf']
    if osm:
        try: cand.update(osm_objects(o[0], o[1], osm, log))
        except RuntimeError as e: log('УВАГА: %s; рахую лише укриття зі зйомки' % e)
    jobs = []
    for kk in kinds:
        L = sorted(cand.get(kk, []), key=lambda c: haversine(o, (c['lat'], c['lon'])))[:NEAREST]
        if not L and kk != 'shelter_dxf': log('   %s: в OSM поблизу не знайдено' % KINDS[kk][0])
        jobs += [(kk, c) for c in L]
    rows = []
    for i, (kk, c) in enumerate(jobs):
        prof = KINDS[kk][1]; straight = haversine(o, (c['lat'], c['lon']))
        try: r = route(prof, o, (c['lat'], c['lon']))
        except Exception as e: r = None; log('   маршрут до «%s»: %s' % (c['name'], str(e)[:60]))
        if not c['addr']:
            try: time.sleep(1.1); c['addr'] = address(c['lat'], c['lon'])
            except Exception: c['addr'] = ''
        rows.append(dict(kind=kk, name=c['name'], addr=c['addr'], lat=c['lat'], lon=c['lon'], straight=straight,
                         road=r['m'] if r else None, time=r['s'] if r else None, line=r['line'] if r else None, prof=prof))
        time.sleep(0.3)
        if progress: progress((i + 1) / len(jobs))
    # TXT
    base = os.path.splitext(path)[0] + ' (ЦЗ)'
    T = ['Відстані ЦЗ — %s' % os.path.basename(path), 'Відлік: %s; система %s' % (src, sysn),
         'Маршрути: OSRM (OpenStreetMap), укриття — пішки, решта — авто. Адреси: OSM / Nominatim. Дані OSM — довідкові,',
         'перед внесенням у ПЗ звірити з даними ДСНС і громади.', '',
         '%-22s %-34s %-44s %9s %9s %7s' % ('Тип', 'Назва', 'Адреса', 'Пряма, м', 'Шлях, км', 'Хв')]
    for r in rows:
        T.append('%-22s %-34s %-44s %9.0f %9s %7s' % (KINDS[r['kind']][0], r['name'][:34], (r['addr'] or '—')[:44], r['straight'],
                                                     '%.2f' % (r['road'] / 1000) if r['road'] is not None else '—',
                                                     '%.0f' % (r['time'] / 60) if r['time'] is not None else '—'))
    if not rows: T.append('(об\'єктів не знайдено)')
    txt = unique(base + '.txt')
    with open(txt, 'w', encoding='utf-8-sig') as fh: fh.write('\n'.join(T) + '\n')
    # DXF у системі й одиницях зйомки
    h = 2.0 / k
    def xy(la, lo):
        E, N = from_w(la, lo); return E / k, N / k
    d = ['0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n9\n$DWGCODEPAGE\n3\nANSI_1251\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n']
    x0, y0 = E0 / k, N0 / k
    d.append('0\nPOINT\n8\nЦЗ - Відлік\n10\n%.3f\n20\n%.3f\n30\n0.0\n' % (x0, y0))
    for r in rows:
        lay = 'ЦЗ - ' + re.sub(r'[<>/\\":;?*|=`()]', '', KINDS[r['kind']][0]).strip()
        x, y = xy(r['lat'], r['lon'])
        d.append('0\nPOINT\n8\n%s\n10\n%.3f\n20\n%.3f\n30\n0.0\n' % (lay, x, y))
        lab = '%s %s' % (r['name'][:40], '%.2f км' % (r['road'] / 1000) if r['road'] is not None else '%.0f м по прямій' % r['straight'])
        d.append('0\nTEXT\n8\n%s\n10\n%.3f\n20\n%.3f\n30\n0.0\n40\n%.3f\n1\n%s\n' % (lay, x + h / 2, y + h / 2, h, lab))
        if r['line']:
            lm = lay + ' - маршрути'
            d.append('0\nPOLYLINE\n8\n%s\n66\n1\n10\n0.0\n20\n0.0\n30\n0.0\n70\n0\n' % lm)
            d.extend('0\nVERTEX\n8\n%s\n10\n%.3f\n20\n%.3f\n30\n0.0\n' % ((lm,) + xy(la, lo)) for la, lo in r['line'])
            d.append('0\nSEQEND\n8\n%s\n' % lm)
    d.append('0\nENDSEC\n0\nEOF\n')
    dxf = unique(base + '.dxf')
    with open(dxf, 'w', encoding='cp1251', errors='replace', newline='\r\n') as fh: fh.write(''.join(d))
    return dict(txt=txt, dxf=dxf, rows=rows, origin=o, system=sysn, lines=T)
