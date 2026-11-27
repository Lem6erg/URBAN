"""DXF з Archicad -> DXF R12 для Digitals у системі координат топо (МСК).

Використання:
  python -I dxf_digitals.py "експорт.dxf" "топо.dmf" ["вихід.dxf"]

Що робить:
  1. Одиниці: $INSUNITS 4 (мм) -> ×0,001; 6 (м) -> ×1.
  2. Зсув: підбирає сталу трансляцію, що кладе вершини шару «…Межі ділянок» на шар
     «Земельна ділянка (JSON)» топо DMF (найближча вершина, ітеративно). Вимога: ≥ 95 % вершин ≤ 1 мм,
     інакше зупиняється без запису.
  3. Пише R12: POLYLINE/VERTEX (дуги — bulge), HATCH з 3–4 вершин -> SOLID, MTEXT/TEXT -> TEXT, cp1251.
  4. Шари: назва шару Archicad (без «_Ном._пера__N»), а щоб Digitals бачив кольори (він бере колір шару),
     для шару з кількома кольорами — «<шар> (перо N)» або «<шар> (колір C)»; колір шару = колір об'єктів.
Створено 27.11.2026 (CLAUDE). Див. CLAUDE/07_DMF_to_Archicad.md.
"""
import sys, os, re, math, collections
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dmf2dxf as D
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr: sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # повідомлення SystemExit — у stderr; GUI читає UTF-8

src, dmf = sys.argv[1], sys.argv[2]
dst = sys.argv[3] if len(sys.argv) > 3 else os.path.splitext(src)[0] + ' (МСК, Digitals).dxf'
L = open(src, encoding='cp1251', errors='replace').read().split('\n')
P = [(L[i].strip(), L[i + 1].rstrip('\r')) for i in range(0, len(L) - 1, 2)]

units, sec, hv = None, None, None  # $INSUNITS; немає / 0 → визначити за розміром креслення відносно топо
E, cur, laycol = [], None, {}
for i, (c, v) in enumerate(P):
    if c == '0':
        if cur: E.append(cur); cur = None
        if v == 'SECTION': sec = P[i + 1][1]
        if sec == 'ENTITIES' and v in ('LWPOLYLINE', 'HATCH', 'MTEXT', 'TEXT'):
            cur = dict(t=v, pts=[], bul=[], flag=0, col=256, body=False, txt='', h=2.5, ang=0.0, layer='0')
        if sec == 'TABLES' and v == 'LAYER': cur = dict(t='LAYER')
        continue
    if sec == 'HEADER':
        if c == '9': hv = v
        elif hv == '$INSUNITS' and c == '70': units = int(v)
        continue
    if cur is None: continue
    t = cur['t']
    if t == 'LAYER':
        if c == '2': cur['name'] = v
        if c == '62': laycol[cur.get('name')] = abs(int(v))
        continue
    if c == '8': cur['layer'] = v
    elif c == '62': cur['col'] = int(v)
    elif t == 'LWPOLYLINE' and c == '70': cur['flag'] = int(v)
    elif t == 'HATCH' and c == '91': cur['body'] = True
    elif c == '10' and (t != 'HATCH' or cur['body']): cur['pts'].append([float(v), 0.0]); cur['bul'].append(0.0)
    elif c == '20' and (t != 'HATCH' or cur['body']) and cur['pts']: cur['pts'][-1][1] = float(v)
    elif c == '42' and t == 'LWPOLYLINE' and cur['bul']: cur['bul'][-1] = float(v)
    elif t in ('MTEXT', 'TEXT') and c in ('1', '3'): cur['txt'] += v
    elif t in ('MTEXT', 'TEXT') and c == '40': cur['h'] = float(v)
    elif t in ('MTEXT', 'TEXT') and c == '50': cur['ang'] = float(v)
E = [e for e in E if e['t'] != 'LAYER' and e['pts']]
print('прочитано: %d об\'єктів' % len(E))
hdr, raw = D.load(dmf); start, objs = D.find_objects(raw); names = D.layer_names(raw, start)
TV = np.array([(ea, n) for o in objs if 'JSON' in names[o['code'] + 3]
               for n, ea in o['verts'] if abs(n - D.BREAK) > 1])
# прив'язка — лише по існуючих межах (шар 1-x «Межі ділянок», узятий з топо); проєктні 2-x не збігаються з топо
def parcels():
    s = np.array([p for e in E if 'Межі ділянок' in e['layer'] and e['layer'].startswith('1-') and e['t'] == 'LWPOLYLINE' for p in e['pts']])
    if not len(s):
        s = np.array([p for e in E if 'Межі ділянок' in e['layer'] and e['t'] == 'LWPOLYLINE' for p in e['pts']])
    return s
S = parcels()
if not len(S): raise SystemExit('У DXF немає шару «Межі ділянок» — нема по чому прив\'язати')

# --- одиниці: $INSUNITS 4 мм, 5 см, 6 м; не вказано / 0 — за розміром ділянок відносно топо ---
k = {4: 0.001, 6: 1.0, 5: 0.01}.get(units)
if k is None:
    if units not in (None, 0): raise SystemExit('Невідомі одиниці $INSUNITS=%s' % units)
    span = lambda A: max(float(np.max(A.max(0) - A.min(0))), 1e-9)
    k = min((1.0, 0.01, 0.001), key=lambda c: abs(math.log(span(S) * c / span(TV))))
    print('одиниці в DXF не вказано — визначено за розміром креслення: ×%g' % k)
for e in E:
    e['pts'] = [[x * k, y * k] for x, y in e['pts']]; e['h'] *= k
S = S * k

# --- зсув до топо ---
def nn(X):
    d = np.empty(len(X)); ii = np.empty(len(X), int)
    for a in range(0, len(X), 400):
        DD = ((X[a:a + 400, None] - TV[None]) ** 2).sum(-1); ii[a:a + 400] = DD.argmin(1); d[a:a + 400] = np.sqrt(DD.min(1))
    return d, ii
best = None
for init in (TV.min(0) - S.min(0), np.median(TV, 0) - np.median(S, 0), TV.max(0) - S.max(0)):
    b = init
    for _ in range(12):
        d, ii = nn(S + b); m = d < max(np.percentile(d, 50), 0.002); b = np.median(TV[ii[m]] - S[m], 0)
    d, _ = nn(S + b); ok = (d <= 0.001).mean()
    if best is None or ok > best[1]: best = (b, ok)
b, ok = best
print('одиниці ×%g, зсув %.4f %.4f, вершин ділянок ≤1 мм: %.1f %%' % (k, b[0], b[1], ok * 100))
if ok < 0.95: raise SystemExit('Прив\'язка до топо не знайдена (≥95 % не досягнуто) — файл не записано')
for e in E: e['pts'] = [[x + b[0], y + b[1]] for x, y in e['pts']]

# --- шари й кольори ---
def arch(n):
    n = re.sub(r'_?Ном\._пера__\d+$', '', n); n = re.sub(r'^(\d+-\d+) _', r'\1 ', n); return n.strip() or '0'
def col(e):
    c = e['col']
    if c in (0, 256, 257): c = laycol.get(e['layer'], 7)
    return 7 if c in (0, 256, 257) else abs(c)
cols = collections.defaultdict(set)
for e in E: cols[arch(e['layer'])].add(col(e))
def lname(e):
    a = arch(e['layer']); m = re.search(r'Ном\._пера__(\d+)$', e['layer'])
    if len(cols[a]) == 1: return a
    return '%s (перо %s)' % (a, m.group(1)) if m else '%s (колір %d)' % (a, col(e))
LAY = {}
for e in E: LAY.setdefault(lname(e), col(e))

o = []; w = o.append
xs = [p[0] for e in E for p in e['pts']]; ys = [p[1] for e in E for p in e['pts']]
w('0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n9\n$DWGCODEPAGE\n3\nANSI_1251\n9\n$INSBASE\n10\n0.0\n20\n0.0\n30\n0.0\n')
w('9\n$EXTMIN\n10\n%.4f\n20\n%.4f\n30\n0.0\n9\n$EXTMAX\n10\n%.4f\n20\n%.4f\n30\n0.0\n0\nENDSEC\n' % (min(xs), min(ys), max(xs), max(ys)))
w('0\nSECTION\n2\nTABLES\n0\nTABLE\n2\nLTYPE\n70\n1\n0\nLTYPE\n2\nCONTINUOUS\n70\n0\n3\nSolid line\n72\n65\n73\n0\n40\n0.0\n0\nENDTAB\n')
w('0\nTABLE\n2\nLAYER\n70\n%d\n0\nLAYER\n2\n0\n70\n0\n62\n7\n6\nCONTINUOUS\n' % (len(LAY) + 1))
for n, c in sorted(LAY.items()):
    if n != '0': w('0\nLAYER\n2\n%s\n70\n0\n62\n%d\n6\nCONTINUOUS\n' % (n, c))
w('0\nENDTAB\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n')
cnt = collections.Counter()
for e in E:
    ln, c = lname(e), col(e)
    if e['t'] == 'LWPOLYLINE':
        w('0\nPOLYLINE\n8\n%s\n62\n%d\n66\n1\n10\n0.0\n20\n0.0\n30\n0.0\n70\n%d\n' % (ln, c, 1 if e['flag'] & 1 else 0))
        for (x, y), bu in zip(e['pts'], e['bul']):
            w('0\nVERTEX\n8\n%s\n10\n%.4f\n20\n%.4f\n30\n0.0\n' % (ln, x, y) + ('42\n%.10f\n' % bu if bu else ''))
        w('0\nSEQEND\n8\n%s\n' % ln)
    elif e['t'] == 'HATCH':
        p = e['pts']
        if len(p) == 3: p = p + [p[2]]
        elif len(p) == 4: p = [p[0], p[1], p[3], p[2]]
        else:
            w('0\nPOLYLINE\n8\n%s\n62\n%d\n66\n1\n70\n1\n' % (ln, c) + ''.join('0\nVERTEX\n8\n%s\n10\n%.4f\n20\n%.4f\n30\n0.0\n' % (ln, x, y) for x, y in p) + '0\nSEQEND\n8\n%s\n' % ln)
            cnt['HATCH-контур'] += 1; continue
        w('0\nSOLID\n8\n%s\n62\n%d\n' % (ln, c) + ''.join('%d\n%.4f\n%d\n%.4f\n%d\n0.0\n' % (10 + j, x, 20 + j, y, 30 + j) for j, (x, y) in enumerate(p)))
    else:
        txt = re.sub(r'\\[A-Za-z][^;\\]*;|\\P|[{}]', ' ', e['txt']).strip()
        if not txt: continue
        x, y = e['pts'][0]
        w('0\nTEXT\n8\n%s\n62\n%d\n10\n%.4f\n20\n%.4f\n30\n0.0\n40\n%.4f\n1\n%s\n50\n%.3f\n' % (ln, c, x, y, e['h'], txt, e['ang']))
    cnt[e['t']] += 1
w('0\nENDSEC\n0\nEOF\n')
open(dst, 'w', encoding='cp1251', errors='replace', newline='\r\n').write(''.join(o))
print('записано:', dst)
print('об\'єктів: %d ліній, %d заливок, %d текстів; шарів: %d' % (cnt['LWPOLYLINE'], cnt['HATCH'] + cnt['HATCH-контур'], cnt['MTEXT'] + cnt['TEXT'], len(LAY)))
