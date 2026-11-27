"""Калькулятор координат: стовпчик точок з однієї системи в іншу (ТЗ Markdown/urban_geo_tools_spec.md, Р8).
Рядок: «[назва] a b» — для плоских систем a, b = X (північ), Y (схід), як у Digitals (або E, N при order='EN');
для WGS-84 — широта, довгота в градусах. Роздільники: пробіл, таб, «;», «,» (кома — лише якщо дроби з крапкою).
Створено 27.11.2026 (CLAUDE)."""
import re
import geo

NUM = re.compile(r'^[+-]?\d+(?:[.,]\d+)?$')


def parse(text):
    """→ [(назва, a, b, № рядка)]; ValueError з номером рядка, якщо рядок не розібрано."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith('#'): continue
        if ';' in s or '\t' in s: toks = [t.strip() for t in re.split(r'[;\t]+', s) if t.strip()]
        elif re.search(r'\d,\d', s) and len(s.split()) >= 2: toks = s.split()  # «49,5 24,1» — кома десяткова
        else: toks = [t for t in re.split(r'[\s,]+', s) if t]
        if len(toks) < 2 or not (NUM.match(toks[-1]) and NUM.match(toks[-2])):
            raise ValueError('рядок %d: наприкінці мають бути два числа — «%s»' % (n, s))
        a, b = (float(t.replace(',', '.')) for t in toks[-2:])
        name = ' '.join(toks[:-2]) or str(len(out) + 1)
        out.append((name, a, b, n))
    if not out: raise ValueError('немає точок')
    return out


def convert(text, src, dst, order='XY'):
    """Перерахунок. order='XY' — X північ, Y схід (геодезичний); 'EN' — E, N (DXF). Повертає (рядки, текст)."""
    f = geo.converter(src, dst); rows = []
    for name, a, b, _ in parse(text):
        if src == geo.WGS: u, v = a, b
        else: u, v = (b, a) if order == 'XY' else (a, b)  # → E, N
        p, q = f(u, v)
        if dst == geo.WGS: rows.append((name, p, q))
        else: rows.append((name,) + ((q, p) if order == 'XY' else (p, q)))
    fmt = '%s\t%.8f\t%.8f' if dst == geo.WGS else '%s\t%.3f\t%.3f'
    return rows, '\n'.join(fmt % r for r in rows)
