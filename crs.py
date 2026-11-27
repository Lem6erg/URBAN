"""Перерахунок плоских координат між системами (СК-63 ↔ УСК-2000 / МСК) за ключами з crs_keys.json.

Ключі НЕ вигадуються: файл crs_keys.json заповнюється лише з офіційних параметрів переходу
(Держгеокадастр / геодезист). Без файлу перерахунок недоступний.

Підтримувані типи переходу (поле "type" у ключі):
  "helmert2d"  — x' = a + c·x − d·y ; y' = b + d·x + c·y           (параметри a, b, c, d)
  "affine2d"   — x' = a0 + a1·x + a2·y ; y' = b0 + b1·x + b2·y    (a0,a1,a2,b0,b1,b2)
  "geodetic"   — плоскі ТМ (src) → геодезичні → 7 параметрів Гельмерта → геодезичні → плоскі ТМ (dst)
                 src/dst: {"ellipsoid": "krassowsky"|"grs80"|[a, 1/f], "lon0": град, "lat0": 0, "k0": 1,
                           "fe": хибне сх., "fn": хибна півн., "swap": false}
                 helmert: {"dx","dy","dz" (м), "rx","ry","rz" (кут. сек), "ds" (ppm), "convention": "position"|"frame"}
Усі координати тут — DXF-порядок: x = схід (E), y = північ (N).
Створено 27.11.2026 (CLAUDE).
"""
import json, math, os, sys

KEYS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'crs_keys.json')
if getattr(sys, 'frozen', False):  # встановлена програма URBAN: ключі користувача — у %APPDATA%\URBAN (папка програми лише для читання)
    _u = os.path.join(os.environ.get('APPDATA') or os.path.dirname(KEYS), 'URBAN', 'crs_keys.json')
    if not os.path.exists(_u) and os.path.exists(KEYS):
        import shutil
        os.makedirs(os.path.dirname(_u), exist_ok=True); shutil.copy(KEYS, _u)
    KEYS = _u
ELL = {'krassowsky': (6378245.0, 298.3), 'grs80': (6378137.0, 298.257222101), 'wgs84': (6378137.0, 298.257223563)}


def load_keys():
    if not os.path.exists(KEYS):
        return []
    return json.load(open(KEYS, encoding='utf-8')).get('transforms', [])


UA = (44.0, 52.5, 22.0, 40.3)  # широта, довгота: межі України з запасом


def guess(E, N):
    """Проєкції з crs_keys.json, у яких точка (E, N) лягає в Україну і в межі своєї зони.
    Повертає [(назва, |lon - lon0|, lat, lon)], найближчі до осьового меридіана — першими."""
    out = []
    for n, p in load_proj().items():
        try:
            lat, lon = tm_inverse(E, N, p)
        except (ValueError, OverflowError, ZeroDivisionError):
            continue
        zoned = p.get('fe', 0) >= 1e6  # FE з номером зони (4500000, 8500000…)
        half = (3.3 if '6°' in n else 1.8) if zoned else 3.0
        if UA[0] <= lat <= UA[1] and UA[2] <= lon <= UA[3] and abs(lon - p['lon0']) <= half:
            out.append((n, abs(lon - p['lon0']), lat, lon))
    return sorted(out, key=lambda t: t[1])


def load_proj():
    if not os.path.exists(KEYS):
        return {}
    return json.load(open(KEYS, encoding='utf-8')).get('projections', {})


def systems():
    s = list(load_proj())
    for k in load_keys():
        for n in (k['from'], k['to']):
            if n not in s: s.append(n)
    return s


# --- еліпсоїд / ТМ ---------------------------------------------------------
def _ell(e):
    a, rf = ELL[e] if isinstance(e, str) else e
    f = 1 / rf
    return a, f, 2 * f - f * f


def _tm_consts(a, f):
    n = f / (2 - f)
    A = a / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    al = [n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16 + 41 * n ** 4 / 180, 13 * n ** 2 / 48 - 3 * n ** 3 / 5 + 557 * n ** 4 / 1440,
          61 * n ** 3 / 240 - 103 * n ** 4 / 140, 49561 * n ** 4 / 161280]
    be = [n / 2 - 2 * n ** 2 / 3 + 37 * n ** 3 / 96 - n ** 4 / 360, n ** 2 / 48 + n ** 3 / 15 - 437 * n ** 4 / 1440,
          17 * n ** 3 / 480 - 37 * n ** 4 / 840, 4397 * n ** 4 / 161280]
    de = [2 * n - 2 * n ** 2 / 3 - 2 * n ** 3 + 116 * n ** 4 / 45, 7 * n ** 2 / 3 - 8 * n ** 3 / 5 - 227 * n ** 4 / 45,
          56 * n ** 3 / 15 - 136 * n ** 4 / 35, 4279 * n ** 4 / 630]
    return n, A, al, be, de


def tm_forward(lat, lon, p):
    a, f, e2 = _ell(p['ellipsoid']); n, A, al, be, de = _tm_consts(a, f)
    k0 = p.get('k0', 1.0); lam = math.radians(lon - p['lon0']); phi = math.radians(lat)
    e = math.sqrt(e2)
    t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
    xi_ = math.atan2(t, math.cos(lam)); eta_ = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    xi = xi_ + sum(al[j] * math.sin(2 * (j + 1) * xi_) * math.cosh(2 * (j + 1) * eta_) for j in range(4))
    eta = eta_ + sum(al[j] * math.cos(2 * (j + 1) * xi_) * math.sinh(2 * (j + 1) * eta_) for j in range(4))
    N = k0 * A * xi - k0 * A * _merid0(p, A, al)
    E = k0 * A * eta
    return E + p.get('fe', 0.0), N + p.get('fn', 0.0)


def _merid0(p, A, al):
    lat0 = math.radians(p.get('lat0', 0.0))
    if lat0 == 0: return 0.0
    a, f, e2 = _ell(p['ellipsoid']); e = math.sqrt(e2)
    t = math.sinh(math.atanh(math.sin(lat0)) - e * math.atanh(e * math.sin(lat0)))
    xi_ = math.atan2(t, 1.0)
    return xi_ + sum(al[j] * math.sin(2 * (j + 1) * xi_) for j in range(4))


def tm_inverse(E, N, p):
    a, f, e2 = _ell(p['ellipsoid']); n, A, al, be, de = _tm_consts(a, f)
    k0 = p.get('k0', 1.0)
    xi = (N - p.get('fn', 0.0)) / (k0 * A) + _merid0(p, A, al); eta = (E - p.get('fe', 0.0)) / (k0 * A)
    xi_ = xi - sum(be[j] * math.sin(2 * (j + 1) * xi) * math.cosh(2 * (j + 1) * eta) for j in range(4))
    eta_ = eta - sum(be[j] * math.cos(2 * (j + 1) * xi) * math.sinh(2 * (j + 1) * eta) for j in range(4))
    chi = math.asin(math.sin(xi_) / math.cosh(eta_))
    phi = chi + sum(de[j] * math.sin(2 * (j + 1) * chi) for j in range(4))
    lam = math.atan2(math.sinh(eta_), math.cos(xi_))
    return math.degrees(phi), p['lon0'] + math.degrees(lam)


def _geo2xyz(lat, lon, h, ell):
    a, f, e2 = _ell(ell); la, lo = math.radians(lat), math.radians(lon)
    N = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return ((N + h) * math.cos(la) * math.cos(lo), (N + h) * math.cos(la) * math.sin(lo), (N * (1 - e2) + h) * math.sin(la))


def _xyz2geo(X, Y, Z, ell):
    a, f, e2 = _ell(ell); lo = math.atan2(Y, X); p = math.hypot(X, Y); la = math.atan2(Z, p * (1 - e2))
    for _ in range(10):
        N = a / math.sqrt(1 - e2 * math.sin(la) ** 2); h = p / math.cos(la) - N
        la = math.atan2(Z, p * (1 - e2 * N / (N + h)))
    return math.degrees(la), math.degrees(lo), h


def _helmert(X, Y, Z, h, inverse=False):
    s = 1 + h.get('ds', 0.0) * 1e-6
    r = [math.radians(h.get(k, 0.0) / 3600) for k in ('rx', 'ry', 'rz')]
    if h.get('convention', 'position') == 'frame': r = [-v for v in r]
    dx, dy, dz = h.get('dx', 0.0), h.get('dy', 0.0), h.get('dz', 0.0)
    if inverse:
        s = 1 / s; r = [-v for v in r]; X, Y, Z = X - dx, Y - dy, Z - dz; dx = dy = dz = 0.0
    rx, ry, rz = r
    return (dx + s * (X - rz * Y + ry * Z), dy + s * (rz * X + Y - rx * Z), dz + s * (-ry * X + rx * Y + Z))


# --- побудова функції перерахунку -------------------------------------------
def _one(k, inverse):
    t = k['type']
    if t == 'helmert2d':
        a, b, c, d = k['a'], k['b'], k['c'], k['d']
        if not inverse: return lambda x, y: (a + c * x - d * y, b + d * x + c * y)
        D = c * c + d * d
        return lambda x, y: ((c * (x - a) + d * (y - b)) / D, (-d * (x - a) + c * (y - b)) / D)
    if t == 'affine2d':
        a0, a1, a2, b0, b1, b2 = (k[n] for n in ('a0', 'a1', 'a2', 'b0', 'b1', 'b2'))
        if not inverse: return lambda x, y: (a0 + a1 * x + a2 * y, b0 + b1 * x + b2 * y)
        D = a1 * b2 - a2 * b1
        return lambda x, y: ((b2 * (x - a0) - a2 * (y - b0)) / D, (-b1 * (x - a0) + a1 * (y - b0)) / D)
    if t == 'geodetic':
        src, dst, h = (k['dst'], k['src'], k['helmert']) if inverse else (k['src'], k['dst'], k['helmert'])
        def f(x, y):
            if src.get('swap'): x, y = y, x
            lat, lon = tm_inverse(x, y, src)
            P0 = _geo2xyz(lat, lon, 0.0, src['ellipsoid'])
            if not inverse:
                X, Y, Z = _helmert(*P0, h)
            else:  # точне обернення ітераціями прямого переходу
                X, Y, Z = P0
                for _ in range(6):
                    F = _helmert(X, Y, Z, h); X, Y, Z = X - (F[0] - P0[0]), Y - (F[1] - P0[1]), Z - (F[2] - P0[2])
            lat2, lon2, _ = _xyz2geo(X, Y, Z, dst['ellipsoid'])
            E, N = tm_forward(lat2, lon2, dst)
            return (N, E) if dst.get('swap') else (E, N)
        return f
    raise ValueError('Невідомий тип ключа: %s' % t)


def _proj(frm, to, PR):
    if frm in PR and to in PR and PR[frm].get('datum') == PR[to].get('datum'):
        a, b = PR[frm], PR[to]   # одна геодезична основа — точна зміна проєкції
        def f(x, y):
            lat, lon = tm_inverse(x, y, a)
            return tm_forward(lat, lon, b)
        return f
    return None


def _key(frm, to):
    for k in load_keys():
        if k['from'] == frm and k['to'] == to: return _one(k, False)
        if k['from'] == to and k['to'] == frm and k.get('reversible', True): return _one(k, True)
    return None


def transformer(frm, to):
    """Функція (x, y) -> (x', y') з системи frm у to, або None, якщо frm == to. KeyError, якщо ключа немає.
    Проєкції з однією основою (поле "projections", однаковий "datum") перераховуються точно, без ключів.
    Ланцюжок (без рекурсії): ключ до проєкції + зміна проєкції, напр. СК-63 → МСК-46 → УСК-2000 зона 4."""
    if frm == to: return None
    PR = load_proj()
    f = _proj(frm, to, PR) or _key(frm, to)
    if f: return f
    for mid in PR:
        if mid in (frm, to): continue
        f1, f2 = _key(frm, mid), _proj(mid, to, PR)
        if not (f1 and f2): f1, f2 = _proj(frm, mid, PR), _key(mid, to)
        if f1 and f2: return lambda x, y, f1=f1, f2=f2: f2(*f1(x, y))
    raise KeyError('Немає ключа переходу %s → %s у %s' % (frm, to, KEYS))


def transform_dxf_r12(path_in, path_out, fn, progress=None):
    """Перераховує всі точки (коди 10–18 / 20–28) в ENTITIES і $EXTMIN/$EXTMAX DXF R12; кути текстів (50) — на локальний поворот."""
    L = open(path_in, encoding='cp1251', errors='replace').read().replace('\r\n', '\n').split('\n')
    P = [[L[i].strip(), L[i + 1]] for i in range(0, len(L) - 1, 2)]
    sec = None; hv = None; ent = None; first = None
    step = max(1, len(P) // 50)
    for i, (c, v) in enumerate(P):
        if progress and i % step == 0: progress(i / len(P))
        if c == '0':
            ent = v; first = None
            if v == 'SECTION': sec = P[i + 1][1].strip()
            continue
        if sec == 'HEADER' and c == '9': hv = v.strip(); continue
        hit = (sec == 'ENTITIES') or (sec == 'HEADER' and hv in ('$EXTMIN', '$EXTMAX'))
        if hit and c.isdigit() and 10 <= int(c) <= 18 and i + 1 < len(P) and P[i + 1][0] == str(int(c) + 10):
            x, y = float(v), float(P[i + 1][1])
            nx, ny = fn(x, y)
            P[i][1] = '%.4f' % nx; P[i + 1][1] = '%.4f' % ny
            if c == '10' and first is None: first = (x, y)
        elif sec == 'ENTITIES' and ent == 'TEXT' and c == '50' and first:
            x, y = first; a0 = fn(x, y); a1 = fn(x + math.cos(math.radians(float(v))), y + math.sin(math.radians(float(v))))
            P[i][1] = '%.3f' % math.degrees(math.atan2(a1[1] - a0[1], a1[0] - a0[0]))
    open(path_out, 'w', encoding='cp1251', errors='replace', newline='\r\n').write(''.join('%s\n%s\n' % (c, v) for c, v in P))
    if progress: progress(1.0)


# --- ключ за спільними пунктами ---------------------------------------------
def read_points(path, geodetic_order=True):
    """Файл TXT/CSV: назва; X1; Y1; X2; Y2 (роздільник ; , таб або пробіл; кома в числах дозволена, якщо роздільник не кома).
    geodetic_order=True: X — північ, Y — схід (як у каталогах). Повертає [(назва, (e1,n1), (e2,n2))]."""
    import re
    out = []
    for line in open(path, encoding='utf-8-sig', errors='replace'):
        line = line.strip()
        if not line or line.startswith('#'): continue
        parts = [p for p in re.split(r'[;\t]|\s{1,}', line) if p != '']
        if len(parts) < 5 and ',' in line and ';' not in line: parts = [p.strip() for p in line.split(',')]
        try: nums = [float(p.replace(',', '.')) for p in parts[-4:]]
        except ValueError: continue
        name = ' '.join(parts[:-4]) or str(len(out) + 1)
        a, b, c, d = nums
        out.append((name, (b, a), (d, c)) if geodetic_order else (name, (a, b), (c, d)))
    return out


def fit(points, kind):
    """kind: helmert2d (≥2 пункти) або affine2d (≥3). Повертає (ключ, нев'язки [(назва, de, dn, d)], СКП)."""
    import numpy as np
    S = np.array([p[1] for p in points], float); T = np.array([p[2] for p in points], float)
    o = S.mean(0); S0 = S - o                     # центрування для стійкості
    n = len(S)
    if kind == 'helmert2d':
        if n < 2: raise ValueError('Для Гельмерта потрібно ≥ 2 пункти')
        A = np.zeros((2 * n, 4)); L = T.reshape(-1)
        A[0::2] = np.c_[np.ones(n), np.zeros(n), S0[:, 0], -S0[:, 1]]
        A[1::2] = np.c_[np.zeros(n), np.ones(n), S0[:, 1], S0[:, 0]]
        a, b, c, d = np.linalg.lstsq(A, L, rcond=None)[0]
        a, b = a - c * o[0] + d * o[1], b - d * o[0] - c * o[1]
        key = dict(type='helmert2d', a=float(a), b=float(b), c=float(c), d=float(d)); dof = 2 * n - 4
    elif kind == 'affine2d':
        if n < 3: raise ValueError('Для афінного потрібно ≥ 3 пункти')
        M = np.c_[np.ones(n), S0]
        px = np.linalg.lstsq(M, T[:, 0], rcond=None)[0]; py = np.linalg.lstsq(M, T[:, 1], rcond=None)[0]
        key = dict(type='affine2d', a0=float(px[0] - px[1] * o[0] - px[2] * o[1]), a1=float(px[1]), a2=float(px[2]),
                   b0=float(py[0] - py[1] * o[0] - py[2] * o[1]), b1=float(py[1]), b2=float(py[2])); dof = 2 * n - 6
    else:
        raise ValueError(kind)
    f = _one(key, False); res = []
    for (nm, s, t) in points:
        x, y = f(*s); res.append((nm, x - t[0], y - t[1], math.hypot(x - t[0], y - t[1])))
    ss = sum(r[1] ** 2 + r[2] ** 2 for r in res)
    rms = math.sqrt(ss / dof) if dof > 0 else float('nan')
    if kind == 'helmert2d':
        key['_масштаб'] = math.hypot(key['c'], key['d']); key['_поворот_сек'] = math.degrees(math.atan2(key['d'], key['c'])) * 3600
    return key, res, rms


def save_key(frm, to, key, source, area=''):
    data = json.load(open(KEYS, encoding='utf-8')) if os.path.exists(KEYS) else {'projections': {}, 'transforms': []}
    data.setdefault('transforms', [])
    data['transforms'] = [t for t in data['transforms'] if not (t['from'] == frm and t['to'] == to)]
    k = {kk: v for kk, v in key.items() if not kk.startswith('_')}
    k.update({'from': frm, 'to': to, 'source': source, 'area': area})
    data['transforms'].append(k)
    json.dump(data, open(KEYS, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
