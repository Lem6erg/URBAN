"""KML/KMZ (Google Earth) ↔ DXF R12 у системі координат (ТЗ Markdown/urban_geo_tools_spec.md, Р6–Р7).

Використання:
  python kml_dxf.py межа.kml "МСК-46 (Львівська обл.)"      → «межа (МСК-46 (Львівська обл.)).dxf»
  python kml_dxf.py зйомка.dxf [система]                     → «зйомка.kml»
Створено 27.11.2026 (CLAUDE)."""
import os, re, sys, zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo, site_map
from pdf_raster import unique


# ---------- KML → об'єкти ----------
def _tag(e): return e.tag.rsplit('}', 1)[-1]


def _coords(text):
    pts = []
    for tok in (text or '').split():
        v = tok.split(',')
        if len(v) >= 2:
            try: pts.append((float(v[1]), float(v[0])))  # (широта, довгота)
            except ValueError: pass
    return pts


def read_kml(path):
    """Список об'єктів: dict(kind='point'|'line'|'poly', layer, name, pts=[(lat, lon)…])."""
    if path.lower().endswith('.kmz'):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith('.kml')]
            if not names: raise ValueError('у KMZ немає KML')
            data = z.read('doc.kml' if 'doc.kml' in names else names[0])
    else:
        with open(path, 'rb') as f: data = f.read()
    root = ET.fromstring(data)
    out = []

    def geom(g, layer, name):
        t = _tag(g)
        if t == 'Point':
            c = [x for x in g.iter() if _tag(x) == 'coordinates']
            if c and _coords(c[0].text): out.append(dict(kind='point', layer=layer, name=name, pts=_coords(c[0].text)[:1]))
        elif t in ('LineString', 'LinearRing'):
            c = [x for x in g.iter() if _tag(x) == 'coordinates']
            if c and len(_coords(c[0].text)) >= 2:
                out.append(dict(kind='poly' if t == 'LinearRing' else 'line', layer=layer, name=name, pts=_coords(c[0].text)))
        elif t == 'Polygon':
            for ring in g.iter():
                if _tag(ring) == 'LinearRing': geom(ring, layer, name)
        elif t == 'MultiGeometry':
            for ch in g: geom(ch, layer, name)

    def walk(node, path):
        for ch in node:
            t = _tag(ch)
            if t in ('Folder', 'Document'):
                nm = next((x.text for x in ch if _tag(x) == 'name' and x.text), '')
                walk(ch, path + [nm.strip()] if (t == 'Folder' and nm.strip()) else path)
            elif t == 'Placemark':
                nm = next((x.text for x in ch if _tag(x) == 'name' and x.text), '') or ''
                for g in ch:
                    if _tag(g) in ('Point', 'LineString', 'LinearRing', 'Polygon', 'MultiGeometry'):
                        geom(g, ' - '.join(path) or 'KML', nm.strip())
            else:
                walk(ch, path)
    walk(root, [])
    if not out: raise ValueError('у KML немає точок, ліній чи полігонів')
    return out


def _lay(s):
    s = re.sub(r'[<>/\\":;?*|=`]', '_', s).strip()[:60]
    return s or 'KML'


def kml_to_dxf(path, system, dst=None):
    """KML/KMZ → DXF R12 у системі system. Повертає (шлях, кількість об'єктів)."""
    objs = read_kml(path)
    f = geo.converter(geo.WGS, system)
    o = ['0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n9\n$DWGCODEPAGE\n3\nANSI_1251\n9\n$INSUNITS\n70\n6\n0\nENDSEC\n',
         '0\nSECTION\n2\nENTITIES\n']
    for ob in objs:
        ln = _lay(ob['layer']); P = [f(la, lo) for la, lo in ob['pts']]
        if ob['kind'] == 'point':
            (x, y), = P
            o.append('0\nPOINT\n8\n%s\n10\n%.4f\n20\n%.4f\n30\n0.0\n' % (ln, x, y))
            if ob['name']: o.append('0\nTEXT\n8\n%s\n10\n%.4f\n20\n%.4f\n30\n0.0\n40\n1.5\n1\n%s\n' % (ln, x + 0.5, y + 0.5, ob['name']))
            continue
        closed = ob['kind'] == 'poly'
        if closed and len(P) > 2 and abs(P[0][0] - P[-1][0]) < 1e-6 and abs(P[0][1] - P[-1][1]) < 1e-6: P = P[:-1]
        o.append('0\nPOLYLINE\n8\n%s\n66\n1\n10\n0.0\n20\n0.0\n30\n0.0\n70\n%d\n' % (ln, 1 if closed else 0))
        o += ['0\nVERTEX\n8\n%s\n10\n%.4f\n20\n%.4f\n30\n0.0\n' % (ln, x, y) for x, y in P]
        o.append('0\nSEQEND\n8\n%s\n' % ln)
    o.append('0\nENDSEC\n0\nEOF\n')
    dst = dst or unique('%s (%s).dxf' % (os.path.splitext(path)[0], re.sub(r'[\\/:*?"<>|]', '_', system)))
    with open(dst, 'w', encoding='cp1251', errors='replace', newline='\r\n') as fh: fh.write(''.join(o))
    return dst, len(objs)


# ---------- DXF / DWG → KML ----------
def dxf_objects(path):
    """ASCII DXF: LWPOLYLINE, POLYLINE(+VERTEX), LINE, POINT з розділу ENTITIES → [dict(kind, layer, pts=[(E, N)], closed)]."""
    L = open(path, encoding='cp1251', errors='replace').read().split('\n')
    P = [(L[i].strip(), L[i + 1].strip()) for i in range(0, len(L) - 1, 2)]
    out, sec, cur, poly = [], None, None, None
    def close():
        nonlocal cur
        if cur is not None:
            if cur['t'] == 'VERTEX':
                if poly is not None: poly['pts'] += cur['pts']
            elif cur['t'] != 'POLYLINE' and cur['pts']:
                out.append(dict(kind='point' if cur['t'] == 'POINT' else 'line', layer=cur['layer'], pts=cur['pts'],
                                closed=bool(cur['flag'] & 1)))
        cur = None
    for i, (c, v) in enumerate(P):
        if c == '0':
            close()
            if v == 'SECTION' and i + 1 < len(P): sec = P[i + 1][1]
            if sec != 'ENTITIES': continue
            if v in ('LWPOLYLINE', 'LINE', 'POINT', 'VERTEX'): cur = dict(t=v, layer='0', pts=[], flag=0, x={})
            elif v == 'POLYLINE': poly = cur = dict(t='POLYLINE', layer='0', pts=[], flag=0, x={})
            elif v == 'SEQEND' and poly is not None:
                if len(poly['pts']) >= 2:
                    out.append(dict(kind='line', layer=poly['layer'], pts=poly['pts'], closed=bool(poly['flag'] & 1)))
                poly = None
            continue
        if cur is None or sec != 'ENTITIES': continue
        if c == '8' and cur['t'] != 'VERTEX': cur['layer'] = v
        elif c == '70' and cur['t'] in ('LWPOLYLINE', 'POLYLINE'): cur['flag'] = int(float(v))
        elif cur['t'] == 'POLYLINE': continue  # «0 0 0» у заголовку POLYLINE — не вершина
        elif c in ('10', '11'): cur['x'][c] = float(v)
        elif c in ('20', '21') and str(int(c) - 10) in cur['x']: cur['pts'].append((cur['x'].pop(str(int(c) - 10)), float(v)))
    close()
    return out


def dwg_objects(path):
    site_map.dwg_points(path)  # перевірка версії й зрозумілі помилки
    import dwgread
    _, ents, _, _ = dwgread.parse(path, 0)
    res = []
    for e in ents:
        t = e.get('t'); pts = [tuple(map(float, p[:2])) for p in (e.get('pts') or []) if len(p) >= 2]
        if not pts: continue
        if t == 27: res.append(dict(kind='point', layer=e.get('layer', '0').rstrip('\x00'), pts=pts[:1], closed=False))
        elif t in (19, 77, 16) and len(pts) >= 2:
            res.append(dict(kind='line', layer=e.get('layer', '0').rstrip('\x00'), pts=pts, closed=bool(e.get('closed'))))
    return res


def to_kml(path, system=None, dst=None):
    """DXF/DWG → KML (WGS-84). system=None — визначити за координатами. Повертає (шлях, система, кількість)."""
    objs = dwg_objects(path) if path.lower().endswith('.dwg') else dxf_objects(path)
    if not objs: raise ValueError('у файлі немає ліній чи точок')
    A = np.array([p for o in objs for p in o['pts']])
    m = site_map.survey_mask(A, system); lo, hi = A[m].min(0) - 1000, A[m].max(0) + 1000  # скупчення зйомки + 1 км
    keep = [o for o in objs if (np.array(o['pts']) >= lo).all() and (np.array(o['pts']) <= hi).all()]
    if not keep: raise ValueError('не вдалося відокремити зйомку від далеких об\'єктів')
    B = np.array([p for o in keep for p in o['pts']]); E, N = (B.min(0) + B.max(0)) / 2
    if not system:
        d = site_map.detect(float(E), float(N))
        if not d: raise ValueError('систему координат не визначено (центр %.2f %.2f) — виберіть вручну' % (E, N))
        system = d[0]
    f = geo.converter(system, geo.WGS)
    by = {}
    for o in keep: by.setdefault(o['layer'], []).append(o)
    k = ['<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
         '<name>%s</name><Style id="l"><LineStyle><color>ff0000ff</color><width>2</width></LineStyle>'
         '<PolyStyle><fill>0</fill></PolyStyle></Style>' % escape(os.path.basename(path))]
    n = 0
    for layer in sorted(by):
        k.append('<Folder><name>%s</name>' % escape(layer))
        for o in by[layer]:
            ll = [f(x, y) for x, y in o['pts']]
            cs = ' '.join('%.8f,%.8f,0' % (lo, la) for la, lo in ll)
            if o['kind'] == 'point':
                k.append('<Placemark><Point><coordinates>%s</coordinates></Point></Placemark>' % cs)
            elif o['closed'] and len(ll) >= 3:
                cs += ' %.8f,%.8f,0' % (ll[0][1], ll[0][0])
                k.append('<Placemark><styleUrl>#l</styleUrl><Polygon><outerBoundaryIs><LinearRing><coordinates>%s'
                         '</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>' % cs)
            else:
                k.append('<Placemark><styleUrl>#l</styleUrl><LineString><coordinates>%s</coordinates></LineString></Placemark>' % cs)
            n += 1
        k.append('</Folder>')
    k.append('</Document></kml>\n')
    dst = dst or unique(os.path.splitext(path)[0] + '.kml')
    with open(dst, 'w', encoding='utf-8') as fh: fh.write(''.join(k))
    return dst, system, n


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    if not a: raise SystemExit(__doc__)
    if a[0].lower().endswith(('.kml', '.kmz')):
        d, n = kml_to_dxf(a[0], a[1] if len(a) > 1 else 'МСК-46 (Львівська обл.)'); print('записано %d об\'єктів: %s' % (n, d))
    else:
        d, s, n = to_kml(a[0], a[1] if len(a) > 1 else None); print('%s; записано %d об\'єктів: %s' % (s, n, d))
