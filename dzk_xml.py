"""Обмінний файл XML ДЗК (UkrainianCadastralExchangeFile) → DXF R12 + TXT-зведення
(ТЗ Markdown/urban_pz_cadastre_cz_spec.md, Р3–Р4). Офлайн; у мережу нічого не надсилається.
Координати файлу: X — північ, Y — схід. Система — за координатами (site_map.detect), назва з файлу — у звіт.
Створено 27.11.2026 (CLAUDE)."""
import os, re, math
import xml.etree.ElementTree as ET
import geo, site_map
from pdf_raster import unique

KN = re.compile(r'^\d{10}:\d{2}:\d{3}:\d{4}$')
KIND = {'ParcelMetricInfo': 'Ділянка', 'ParcelInfo': 'Ділянка', 'LandParcelInfo': 'Угіддя', 'LandsParcel': 'Угіддя',
        'RestrictionInfo': 'Обмеження', 'Restrictions': 'Обмеження', 'LeaseInfo': 'Оренда', 'Leases': 'Оренда',
        'SubleaseInfo': 'Суборенда', 'Subleases': 'Суборенда', 'CadastralQuarterInfo': 'Квартал',
        'CadastralZoneInfo': 'Зона', 'AdjacentUnitInfo': 'Суміжник', 'AdjacentUnits': 'Суміжник'}


def _t(e): return e.tag.rsplit('}', 1)[-1]


def _kid(e, name):
    for c in e:
        if _t(c) == name: return c
    return None


def _txt(e, *path):
    for name in path:
        if e is None: return ''
        e = _kid(e, name)
    return (e.text or '').strip() if e is not None else ''


def _num(s):
    return float(s.replace(',', '.').replace(' ', ''))


def kn_url(kn):
    kn = kn.strip()
    if not KN.match(kn): raise ValueError('кадастровий номер має вигляд 0000000000:00:000:0000')
    return 'https://kadastr.com.ua/parcel/' + kn


def parse(path):
    """→ dict(points {uidp: (X, Y, PN)}, objects [dict(kind, name, rings [[uidp…]], area_decl, holes)], info, cs)."""
    root = ET.parse(path).getroot()
    if _t(root) != 'UkrainianCadastralExchangeFile':
        raise ValueError('це не обмінний файл ДЗК (немає UkrainianCadastralExchangeFile)')
    parent = {c: p for p in root.iter() for c in p}
    pts, lines = {}, {}
    for e in root.iter():
        t = _t(e)
        if t == 'Point' and _kid(e, 'UIDP') is not None and _kid(e, 'X') is not None:
            pts[_txt(e, 'UIDP')] = (_num(_txt(e, 'X')), _num(_txt(e, 'Y')), _txt(e, 'PN') or _txt(e, 'UIDP'))
        elif t == 'PL' and _kid(e, 'ULID') is not None:
            P = _kid(e, 'Points')
            lines[_txt(e, 'ULID')] = [(c.text or '').strip() for c in (P if P is not None else []) if _t(c) == 'P']
    if not pts: raise ValueError('у файлі немає точок (MetricInfo/PointInfo)')
    cs = ''
    for e in root.iter():
        if _t(e) == 'CoordinateSystem':
            c = list(e)
            cs = ' '.join([_t(c[0])] + [(_t(x) if not (x.text or '').strip() else (x.text or '').strip()) for x in c[0]] +
                          ([(c[0].text or '').strip()] if c and (c[0].text or '').strip() else [])) if c else (e.text or '').strip()
            break

    def ring(bnd):
        """Boundary → список uidp по колу (лінії зшиваються за FP/TP або кінцями)."""
        segs = []
        for ln in bnd.iter():
            if _t(ln) != 'Line': continue
            seq = list(lines.get(_txt(ln, 'ULID'), []))
            fp, tp = _txt(ln, 'FP'), _txt(ln, 'TP')
            if seq and fp and seq[0] != fp and seq[-1] == fp: seq.reverse()
            elif seq and tp and seq[-1] != tp and seq[0] == tp: seq.reverse()
            if len(seq) >= 2: segs.append(seq)
        if not segs: return []
        out = list(segs.pop(0))
        while segs:
            for i, s in enumerate(segs):
                if s[0] == out[-1]: out += s[1:]; segs.pop(i); break
                if s[-1] == out[-1]: out += s[::-1][1:]; segs.pop(i); break
            else:
                s = segs.pop(0); out += s  # розрив — приєднати як є
        if len(out) > 2 and out[0] == out[-1]: out.pop()
        return [u for u in out if u in pts]

    objs = []
    for ex in root.iter():
        if _t(ex) != 'Externals': continue
        own = parent.get(ex)
        kind = 'Об\'єкт'; e = own
        while e is not None:
            if _t(e) in KIND: kind = KIND[_t(e)]; break
            e = parent.get(e)
        rings = [r for b in ex.iter() if _t(b) == 'Boundary' and parent.get(b) is ex for r in [ring(b)] if len(r) >= 3]
        inner = _kid(ex, 'Internals')
        holes = [r for b in (inner.iter() if inner is not None else []) if _t(b) == 'Boundary' for r in [ring(b)] if len(r) >= 3]
        if not rings: continue
        area = None
        for a in own.iter() if own is not None else []:
            if _t(a) == 'Area' and _kid(a, 'Size') is not None:
                try:
                    v = _num(_txt(a, 'Size')); u = _txt(a, 'MeasurementUnit').lower()
                    area = v * 10000 if ('га' in u or 'ha' in u) else v
                except ValueError: pass
                break
        name = ''
        if kind == 'Угіддя': name = _txt(own, 'LandCode') or _txt(parent.get(own), 'LandCode')
        elif kind == 'Обмеження':
            o = own if _kid(own, 'RestrictionCode') is not None else parent.get(own)
            name = ' '.join(x for x in (_txt(o, 'RestrictionCode'), _txt(o, 'RestrictionName')) if x)
        objs.append(dict(kind=kind, name=name, rings=rings, holes=holes, area_decl=area))
    info = {}
    for e in root.iter():
        t = _t(e)
        if t == 'CadastralZoneInfo':
            info['koatuu'] = _txt(e, 'KOATUU'); info['zone'] = _txt(e, 'CadastralZoneNumber')
        elif t == 'CadastralQuarterInfo': info['quarter'] = _txt(e, 'CadastralQuarterNumber')
        elif t == 'ParcelMetricInfo': info['parcel'] = _txt(e, 'ParcelID')
        elif t == 'CategoryPurposeInfo':
            info['category'] = _txt(e, 'Category'); info['purpose'] = _txt(e, 'Purpose'); info['use'] = _txt(e, 'Use')
        elif t == 'OwnershipInfo': info['ownership'] = _txt(e, 'Code')
    if all(info.get(k) for k in ('koatuu', 'zone', 'quarter', 'parcel')):
        info['kn'] = '%s:%s:%s:%s' % (info['koatuu'], info['zone'].zfill(2), info['quarter'].zfill(3), info['parcel'].zfill(4))
    return dict(points=pts, objects=objs, info=info, cs=cs)


def _area(P):
    return abs(sum(P[i][0] * P[i - 1][1] - P[i - 1][0] * P[i][1] for i in range(len(P)))) / 2


def detect_system(data):
    """Система файлу за координатами (E = Y, N = X); None — не визначено."""
    X = [p[0] for p in data['points'].values()]; Y = [p[1] for p in data['points'].values()]
    E, N = (min(Y) + max(Y)) / 2, (min(X) + max(X)) / 2
    d = site_map.detect(E, N)
    return d[0] if d else None


def to_dxf(path, out_system=None):
    """XML ДЗК → «<назва> (ДЗК).dxf» + «<назва> (ДЗК).txt». out_system=None — як у файлі.
    → dict(dxf, txt, kn, area, area_decl, system, n_obj)."""
    d = parse(path); src = detect_system(d)
    if out_system and out_system != src:
        if not src: raise ValueError('систему координат файлу не визначено — перерахунок неможливий; виберіть «як у файлі»')
        f = geo.converter(src, out_system)
    else:
        f = lambda E, N: (E, N)
    XY = {u: f(y, x) + (pn,) for u, (x, y, pn) in d['points'].items()}  # → (E, N, PN)
    kn = d['info'].get('kn', '')
    o = ['0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n9\n$DWGCODEPAGE\n3\nANSI_1251\n9\n$INSUNITS\n70\n6\n0\nENDSEC\n',
         '0\nSECTION\n2\nENTITIES\n']
    def poly(layer, P):
        o.append('0\nPOLYLINE\n8\n%s\n66\n1\n10\n0.0\n20\n0.0\n30\n0.0\n70\n1\n' % layer)
        o.extend('0\nVERTEX\n8\n%s\n10\n%.3f\n20\n%.3f\n30\n0.0\n' % (layer, x, y) for x, y in P)
        o.append('0\nSEQEND\n8\n%s\n' % layer)
    def text(layer, x, y, h, s):
        o.append('0\nTEXT\n8\n%s\n10\n%.3f\n20\n%.3f\n30\n0.0\n40\n%.2f\n1\n%s\n' % (layer, x, y, h, s))
    main_area = main_decl = None; used = set()
    for ob in d['objects']:
        layer = 'ДЗК - ' + ob['kind']
        for i, r in enumerate(ob['rings'] + ob['holes']):
            P = [XY[u][:2] for u in r]; used.update(r); poly(layer, P)
            if i == 0:
                a = _area(P) - sum(_area([XY[u][:2] for u in h]) for h in ob['holes'])
                cx = sum(p[0] for p in P) / len(P); cy = sum(p[1] for p in P) / len(P)
                if ob['kind'] == 'Ділянка' and main_area is None:
                    main_area, main_decl = a, ob['area_decl']
                    text(layer, cx, cy, 2.0, kn or 'ділянка')
                    text(layer, cx, cy - 3.0, 1.5, 'S = %.4f га' % ((ob['area_decl'] or a) / 10000))
                elif ob['name']: text(layer, cx, cy, 1.5, ob['name'][:60])
    for u in sorted(used, key=lambda u: (len(u), u)):
        x, y, pn = XY[u]
        o.append('0\nPOINT\n8\nДЗК - Точки\n10\n%.3f\n20\n%.3f\n30\n0.0\n' % (x, y))
        text('ДЗК - Точки', x + 0.5, y + 0.5, 1.0, pn)
    o.append('0\nENDSEC\n0\nEOF\n')
    base = os.path.splitext(path)[0] + ' (ДЗК)'
    dxf = unique(base + '.dxf')
    with open(dxf, 'w', encoding='cp1251', errors='replace', newline='\r\n') as fh: fh.write(''.join(o))
    inf = d['info']
    L = ['Обмінний файл ДЗК — %s' % os.path.basename(path),
         'Кадастровий номер: %s' % (kn or 'не визначено'),
         'Площа за файлом: %s' % ('%.4f га' % (main_decl / 10000) if main_decl else '—'),
         'Площа за контуром: %s' % ('%.4f га' % (main_area / 10000) if main_area is not None else '—')]
    if main_decl and main_area is not None:
        L.append('Різниця: %.1f м² (%.2f %%)' % (main_area - main_decl, 100 * (main_area - main_decl) / main_decl))
    L += ['Категорія земель: %s' % (inf.get('category') or '—'), 'Цільове призначення (код): %s' % (inf.get('purpose') or '—'),
          'Використання: %s' % (inf.get('use') or '—'), 'Форма власності (код): %s' % (inf.get('ownership') or '—'),
          'Система у файлі: %s' % (d['cs'] or 'не вказано'), 'Система за координатами: %s' % (src or 'не визначено'),
          'Система DXF: %s' % (out_system if out_system and out_system != src else (src or 'як у файлі')),
          'Об\'єктів: %d (%s), точок: %d' % (len(d['objects']), ', '.join(sorted({o['kind'] for o in d['objects']})), len(used)),
          '', 'DXF: %s' % os.path.basename(dxf)]
    txt = unique(base + '.txt')
    with open(txt, 'w', encoding='utf-8-sig') as fh: fh.write('\n'.join(L) + '\n')
    return dict(dxf=dxf, txt=txt, kn=kn, area=main_area, area_decl=main_decl, system=src, n_obj=len(d['objects']), lines=L)
