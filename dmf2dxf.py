"""DMF (Digitals, Version 1.10) -> DXF R12 converter.

Formats reverse-engineered on 2026-11-08 from own survey files with DMF+DXF pairs
(see CLAUDE/07_DMF_to_Archicad.md). Not an official Digitals tool: always check the result.

Usage:  python dmf2dxf.py input.dmf [output.dxf]
Output: <name>.dxf (DXF R12, cp1251) + <name>_semantics.csv (attributes of objects).

DXF axes: X = east (geodetic Y), Y = north (geodetic X). Units: metres. Coordinates unchanged
(the DMF coordinate system name is printed, e.g. SK63(1) = CK-63 zone 1).
"""
import csv, os, re, struct, sys, zlib

BREAK = -2684354.56          # vertex value used by Digitals as a polyline part separator
SEP_FIELD, SEP_VAL, SEP_PARAM, SEP_END = '\x01', '\x03', '\x05', '\x02'


def ext80(b, o):
    m, e = struct.unpack_from('<QH', b, o)
    s = -1.0 if e & 0x8000 else 1.0
    e &= 0x7FFF
    if e == 0 and m == 0:
        return 0.0
    return s * m / 2**63 * 2.0**(e - 16383)


def load(path):
    d = open(path, 'rb').read()
    if not d.startswith(b'DMF'):
        raise SystemExit('Not a DMF file: %r' % d[:32])
    body = d[32:]
    if body[:1] == b'\x78':          # v1.10 C: zlib-compressed; v1.15: stored as is
        body = zlib.decompressobj().decompress(body)
    return d[:31].decode('ascii', 'replace'), body


def walk(raw, h):
    """Yield objects from header offset h; return None if chain is not valid."""
    objs = []
    while h + 56 <= len(raw):
        if raw[h:h + 4] != b'\x2c\x00\x00\x00':
            return None
        cnt, a, b, code, oid, c180 = struct.unpack_from('<6i', raw, h + 4)
        alen = struct.unpack_from('<i', raw, h + 48)[0]
        if (c180 & 0x180) != 0x180 or not (0 <= cnt < 10**6) or not (0 <= alen < 10**5):
            return None
        v0 = h + 56 + alen
        if v0 + 34 * cnt - 14 > len(raw):   # last record may be stored without its tail
            return None
        verts = [(ext80(raw, v0 + 34 * k), ext80(raw, v0 + 34 * k + 10)) for k in range(cnt)]
        attr = raw[h + 52:h + 52 + alen].decode('cp1251', 'replace')
        objs.append(dict(code=code, oid=oid, verts=verts, attr=attr))
        h = v0 + 34 * cnt + 2
    return objs


def find_objects(raw):
    for m in re.finditer(rb'\x2c\x00\x00\x00', raw):
        h = m.start()
        if h + 28 > len(raw) or (struct.unpack_from("<i", raw, h + 24)[0] & 0x180) != 0x180:
            continue
        objs = walk(raw, h)
        if objs:
            return h, objs
    raise SystemExit('Object table not found (unsupported DMF variant)')


def layer_names(raw, limit):
    names = []
    for m in re.finditer(rb'[\x05\x0b\x0f](?:Arial|Courier New|Times New Roman)', raw[:limit]):
        e = m.start()
        for ln in range(1, 160):
            s = e - ln - 1
            if s > 0 and raw[s] == ln:
                names.append(raw[s + 1:e].decode('cp1251', 'replace'))
                break
    return names


def coord_system(raw):
    m = re.search(rb'(S[CK]\d\d\(\d+\)|USK2000[^\x00]{0,10}|\x55\x43\x4b[^\x00]{0,10})', raw[:5000])
    return m.group().decode('ascii', 'replace') if m else 'невідомо'


def parse_attr(attr):
    """-> list of (code, value, params dict)."""
    out = []
    for part in attr.split(SEP_FIELD)[1:]:
        part = part.split(SEP_END)[0]
        if SEP_VAL not in part:
            out.append((part, '', {}))
            continue
        code, rest = part.split(SEP_VAL, 1)
        chunks = rest.split(SEP_PARAM)
        params = {c[0]: c[1:] for c in chunks[1:] if c}
        out.append((code, chunks[0], params))
    return out


def dxf_layer(name):
    n = re.sub(r'[<>/\\":;?*|=,`\']', '_', name).strip() or '0'
    return n[:250]


def write_dxf(path, layers, ents):
    L = []
    w = L.append
    xs = [x for e in ents for x, y in e['pts']] or [0]
    ys = [y for e in ents for x, y in e['pts']] or [0]
    w('0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n9\n$DWGCODEPAGE\n3\nANSI_1251\n9\n$INSUNITS\n70\n6\n')
    w('9\n$EXTMIN\n10\n%.3f\n20\n%.3f\n30\n0.0\n9\n$EXTMAX\n10\n%.3f\n20\n%.3f\n30\n0.0\n' % (min(xs), min(ys), max(xs), max(ys)))
    w('0\nENDSEC\n0\nSECTION\n2\nTABLES\n0\nTABLE\n2\nLAYER\n70\n%d\n' % (len(layers) + 1))
    w('0\nLAYER\n2\n0\n70\n0\n62\n7\n6\nCONTINUOUS\n')
    for i, ln in enumerate(sorted(layers)):
        w('0\nLAYER\n2\n%s\n70\n0\n62\n%d\n6\nCONTINUOUS\n' % (ln, 1 + i % 254))
    w('0\nENDTAB\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n')
    for e in ents:
        if e['t'] == 'PL':
            w('0\nPOLYLINE\n8\n%s\n66\n1\n70\n%d\n' % (e['layer'], 1 if e['closed'] else 0))
            for x, y in e['pts']:
                w('0\nVERTEX\n8\n%s\n10\n%.3f\n20\n%.3f\n30\n0.0\n' % (e['layer'], x, y))
            w('0\nSEQEND\n8\n%s\n' % e['layer'])
        elif e['t'] == 'PT':
            x, y = e['pts'][0]
            w('0\nPOINT\n8\n%s\n10\n%.3f\n20\n%.3f\n30\n%.3f\n' % (e['layer'], x, y, e.get('z', 0.0)))
            w('0\nCIRCLE\n8\n%s\n10\n%.3f\n20\n%.3f\n30\n0.0\n40\n0.25\n' % (e['layer'], x, y))
        elif e['t'] == 'TX':
            x, y = e['pts'][0]
            txt = e['text'].replace('\n', ' ')
            w('0\nTEXT\n8\n%s\n10\n%.3f\n20\n%.3f\n30\n0.0\n40\n%.3f\n1\n%s\n50\n%.2f\n72\n1\n11\n%.3f\n21\n%.3f\n31\n0.0\n73\n2\n'
              % (e['layer'], x, y, e['h'], txt, e['ang'], x, y))
    w('0\nENDSEC\n0\nEOF\n')
    with open(path, 'w', encoding='cp1251', errors='replace', newline='\r\n') as f:
        f.write(''.join(L))


def nums(s):
    out = []
    for v in (s or '').split('|'):
        try:
            out.append(float(v))
        except ValueError:
            out.append(0.0)
    return out


def convert(src, dst=None, shift=None):
    """shift=(E, N): subtract this base point from all coordinates (local origin for Archicad)."""
    header, raw = load(src)
    start, objs = find_objects(raw)
    names = layer_names(raw, start)
    cs = coord_system(raw)
    dst = dst or os.path.splitext(src)[0] + '_claude.dxf'
    ents, layers, sem, spot = [], set(), [], []
    for ob in objs:
        idx = ob['code'] + 3
        lname = dxf_layer(names[idx] if 0 <= idx < len(names) else 'CODE_%d' % ob['code'])
        layers.add(lname)
        parts, cur = [], []
        for n, e in ob['verts']:
            if abs(n - BREAK) < 1 or abs(e - BREAK) < 1:
                if cur:
                    parts.append(cur)
                cur = []
            else:
                cur.append((e, n))   # DXF x=east, y=north
        if cur:
            parts.append(cur)
        good = [p for part in parts for p in part]
        fields = parse_attr(ob['attr'])
        z = None
        if 'висот' in lname.lower() and len(good) == 1:     # survey spot heights (пікети)
            for code, val, prm in fields:
                if re.fullmatch(r'-?\d{1,4}[.,]\d{1,3}', val.strip()):
                    z = float(val.strip().replace(',', '.'))
            if z is not None:
                pid = next((v for c, v, p in fields if c == '1'), ob['oid'])
                spot.append((pid, good[0][0], good[0][1], z))
        for part in parts:
            if len(part) == 1:
                ents.append(dict(t='PT', layer=lname, pts=part, z=z or 0.0))
            elif len(part) > 1:
                closed = len(part) > 2 and part[0] == part[-1]
                ents.append(dict(t='PL', layer=lname, pts=part[:-1] if closed else part, closed=closed))
        if good:
            cx = (min(p[0] for p in good) + max(p[0] for p in good)) / 2
            cy = (min(p[1] for p in good) + max(p[1] for p in good)) / 2
        for code, val, prm in fields:
            sem.append(dict(layer=lname, object_id=ob['oid'], field_code=code, value=val.replace('|', ' / '),
                            x_east=round(good[0][0], 3) if good else '', y_north=round(good[0][1], 3) if good else ''))
            if 'X' not in prm or not val or not good:
                continue
            dn, de = nums(prm.get('X')), nums(prm.get('Y'))
            ang = [a / 10.0 for a in nums(prm.get('O'))]
            hgt = (nums(prm['S'])[0] / 3545.0) if prm.get('S') else 1.4
            if hgt <= 0:
                hgt = 1.4
            lines = val.split('|')
            for k in range(len(dn)):
                x = cx + (de[k] if k < len(de) else 0.0)
                y = cy + dn[k]
                a = ang[k] if k < len(ang) else (ang[0] if ang else 0.0)
                if len(dn) > 1:
                    ents.append(dict(t='TX', layer=lname, pts=[(x, y)], text=val.replace('|', ' '), h=hgt, ang=a))
                else:
                    import math
                    for j, line in enumerate(lines):
                        off = (j - (len(lines) - 1) / 2) * hgt * 1.5
                        ents.append(dict(t='TX', layer=lname, pts=[(x + off * math.sin(math.radians(a)),
                                                                    y - off * math.cos(math.radians(a)))],
                                         text=line, h=hgt, ang=a))
    if shift:
        sx, sy = shift
        for e in ents:
            e['pts'] = [(x - sx, y - sy) for x, y in e['pts']]
        spot = [(pid, x - sx, y - sy, zz) for pid, x, y, zz in spot]
        for r in sem:
            if r['x_east'] != '':
                r['x_east'] = round(r['x_east'] - sx, 3)
                r['y_north'] = round(r['y_north'] - sy, 3)
    write_dxf(dst, layers, ents)
    csv_path = os.path.splitext(dst)[0] + '_semantics.csv'
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=['layer', 'object_id', 'field_code', 'value', 'x_east', 'y_north'], delimiter=';')
        wr.writeheader()
        wr.writerows(sem)
    if spot:
        pts_path = os.path.splitext(dst)[0] + '_points.txt'
        with open(pts_path, 'w', encoding='utf-8', newline='\r\n') as f:
            f.write('# name\tE(x)\tN(y)\tH\n')
            for pid, x, y, zz in spot:
                f.write('%s\t%.3f\t%.3f\t%.2f\n' % (pid, x, y, zz))
    stats = dict(spot_heights=len(spot), header=header.strip(), coord_system=cs, objects=len(objs), layers_used=len(layers),
                 polylines=sum(e['t'] == 'PL' for e in ents), points=sum(e['t'] == 'PT' for e in ents),
                 texts=sum(e['t'] == 'TX' for e in ents), dxf=dst, csv=csv_path)
    if ents:
        stats['extent_east'] = (round(min(x for e in ents for x, y in e['pts']), 2), round(max(x for e in ents for x, y in e['pts']), 2))
        stats['extent_north'] = (round(min(y for e in ents for x, y in e['pts']), 2), round(max(y for e in ents for x, y in e['pts']), 2))
    return stats


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    args = sys.argv[1:]
    shift = None
    if '--shift' in args:            # --shift E N   (e.g. --shift 1253300 5349150)
        i = args.index('--shift')
        shift = (float(args[i + 1]), float(args[i + 2]))
        del args[i:i + 3]
    st = convert(args[0], args[1] if len(args) > 1 else None, shift)
    if shift:
        st['shift_base_point'] = 'E %.3f, N %.3f -> (0, 0)' % shift
    for k, v in st.items():
        print('%s: %s' % (k, v))
