"""Прив'язка растру (скан, викопіювання, скріншот карти) за точками → растр північчю вгору для Archicad
+ кути й розмір у метрах + world-файл (ТЗ Markdown/urban_geo_tools_spec.md, Р1, Р9).
Точки: (px, py, E, N) — px, py у пікселях оригіналу (0,0 — лівий верхній кут), E — схід, N — північ.
2 точки → Гельмерт (зсув, поворот, масштаб); ≥ 3 → афінне (МНК) з нев'язками.
Створено 27.11.2026 (CLAUDE)."""
import os, math
import numpy as np
from PIL import Image
from pdf_raster import unique

Image.MAX_IMAGE_PIXELS = None
WORLD = {'.jpg': '.jgw', '.jpeg': '.jgw', '.png': '.pgw', '.tif': '.tfw', '.tiff': '.tfw', '.bmp': '.bpw', '.gif': '.gfw'}


def fit(pts):
    """→ (матриця 2×3 [[a0, a1, a2], [b0, b1, b2]]: E = a0 + a1·px + a2·py, N = b0 + b1·px + b2·py; нев'язки м; СКП)."""
    P = np.array(pts, float)
    if len(P) < 2: raise ValueError('потрібно щонайменше 2 точки')
    px, py, E, N = P.T
    if len(P) == 2:
        # подібність з дзеркалом осі y (у растрі y донизу): E = a + c·px + d·py ; N = b + d·px − c·py
        A = np.zeros((4, 4)); r = np.zeros(4)
        for i in range(2):
            A[2 * i] = [1, 0, px[i], py[i]]; r[2 * i] = E[i]
            A[2 * i + 1] = [0, 1, -py[i], px[i]]; r[2 * i + 1] = N[i]
        if abs(np.linalg.det(A)) < 1e-12: raise ValueError('точки збігаються')
        a, b, c, d = np.linalg.solve(A, r)
        M = np.array([[a, c, d], [b, d, -c]])
    else:
        G = np.column_stack([np.ones(len(P)), px, py])
        if np.linalg.matrix_rank(G) < 3: raise ValueError('точки лежать на одній прямій — потрібні 3 точки не на прямій')
        M = np.array([np.linalg.lstsq(G, E, rcond=None)[0], np.linalg.lstsq(G, N, rcond=None)[0]])
    pr = M @ np.vstack([np.ones(len(P)), px, py])
    res = np.hypot(pr[0] - E, pr[1] - N)
    # СКП — лише коли є надлишкові точки (2 точки для Гельмерта і 3 для афінного визначають перетворення точно)
    rms = float(math.sqrt((res ** 2).sum() / (2 * len(P) - 6))) if len(P) > 3 else float('nan')
    return M, res, rms


def apply(M, px, py):
    return M[0, 0] + M[0, 1] * px + M[0, 2] * py, M[1, 0] + M[1, 1] * px + M[1, 2] * py


def world_text(M, shift=(0.0, 0.0)):
    """World-файл для оригіналу: A, D, B, E, C, F (C, F — центр лівого верхнього пікселя)."""
    C, F = apply(M, 0.5, 0.5)
    return '\n'.join('%.10f' % v for v in (M[0, 1], M[1, 1], M[0, 2], M[1, 2], C - shift[0], F - shift[1])) + '\n'


def rectify(src, pts, shift=(0.0, 0.0), progress=None):
    """Пише «<назва> (прив'язано).png» (північ угору, прозоре тло), «… (прив'язано).txt» і world-файл оригіналу.
    Повертає dict(png, txt, world, size_m, corner_ll, corner_ul, pixel, res, rms)."""
    M, res, rms = fit(pts)
    with Image.open(src) as im0:
        im = im0.convert('RGBA'); W, H = im.size
    det = M[0, 1] * M[1, 2] - M[0, 2] * M[1, 1]
    if abs(det) < 1e-18: raise ValueError('вироджене перетворення')
    s = math.sqrt(abs(det))  # розмір пікселя, м
    cx = [apply(M, x, y) for x, y in ((0, 0), (W, 0), (0, H), (W, H))]
    E0, E1 = min(c[0] for c in cx), max(c[0] for c in cx); N0, N1 = min(c[1] for c in cx), max(c[1] for c in cx)
    w, h = max(1, int(math.ceil((E1 - E0) / s - 1e-6))), max(1, int(math.ceil((N1 - N0) / s - 1e-6)))  # 1e-6: 200.0000001 → 200
    if w * h > 400e6: raise ValueError('результат завеликий (%d×%d) — перевірте точки' % (w, h))
    Mi = np.linalg.inv(np.array([[M[0, 1], M[0, 2]], [M[1, 1], M[1, 2]]]))
    # вихідний піксель (x, y) → E = E0 + s·x, N = N1 − s·y → вхідний піксель = Mi·(E − a0, N − b0)
    a, b = Mi[0, 0] * s, -Mi[0, 1] * s; d, e = Mi[1, 0] * s, -Mi[1, 1] * s
    c = Mi[0, 0] * (E0 - M[0, 0]) + Mi[0, 1] * (N1 - M[1, 0]); f = Mi[1, 0] * (E0 - M[0, 0]) + Mi[1, 1] * (N1 - M[1, 0])
    if progress: progress(0.3)
    out = im.transform((w, h), Image.AFFINE, (a, b, c, d, e, f), resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    if progress: progress(0.8)
    base = os.path.splitext(src)[0]
    png = unique(base + " (прив'язано).png"); out.save(png)
    world = unique(base + WORLD.get(os.path.splitext(src)[1].lower(), '.wld'))
    with open(world, 'w', encoding='ascii') as fh: fh.write(world_text(M, shift))
    sx, sy = shift
    ll, ul = (E0 - sx, N0 - sy), (E0 - sx, N1 - sy)
    lines = ['Прив\'язка растру — %s' % os.path.basename(src),
             'Точок: %d, перетворення: %s' % (len(pts), 'Гельмерт (2 точки)' if len(pts) == 2 else 'афінне'),
             'Нев\'язки, м: ' + ', '.join('%.3f' % r for r in res) + ('   СКП %.3f м' % rms if rms == rms else
                                                                    '   (контролю немає — для перевірки додайте ще точку)'),
             '' if not any(shift) else 'Зсув до локального нуля: E %.3f, N %.3f (віднято від координат нижче)' % shift,
             '',
             'Для Archicad (інструмент «Рисунок», файл %s):' % os.path.basename(png),
             '  розмір: ширина %.3f м × висота %.3f м  (%.1f × %.1f мм)' % (w * s, h * s, w * s * 1000, h * s * 1000),
             '  лівий нижній кут: X(схід) = %.3f, Y(північ) = %.3f' % ll,
             '  лівий верхній кут: X(схід) = %.3f, Y(північ) = %.3f' % ul,
             '  растр повернуто північчю вгору — обертати не потрібно',
             '  розмір пікселя: %.4f м' % s,
             '',
             'World-файл оригіналу (QGIS, AutoCAD Map): %s' % os.path.basename(world)]
    txt = unique(base + " (прив'язано).txt")
    with open(txt, 'w', encoding='utf-8-sig') as fh: fh.write('\n'.join(l for l in lines if l is not None) + '\n')
    if progress: progress(1.0)
    return dict(png=png, txt=txt, world=world, size_m=(w * s, h * s), corner_ll=ll, corner_ul=ul, pixel=s, res=res, rms=rms)
