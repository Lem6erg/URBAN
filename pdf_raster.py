"""PDF → JPEG / TIFF (ТЗ Markdown/urban_pdf_raster_spec.md). Рушій — pypdfium2 (PDFium), без tkinter.

Використання з командного рядка:
  python pdf_raster.py файл.pdf jpeg|tiff draft|print|max [color|gray|bw] ["1-3,5"]
Результат — папка поруч із PDF «<назва> (JPEG)» / «<назва> (TIFF)»; наявні файли не перезаписуються.
Створено 27.11.2026 (CLAUDE)."""
import os, re, sys
import pypdfium2 as pdfium
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # великі аркуші — наші власні рендери, не сторонні файли

# рівень: (назва, DPI, якість JPEG, subsampling JPEG: 0 = 4:4:4, 2 = 4:2:0)
LEVELS = {'draft': ('Чернетка', 150, 85, 2), 'print': ('Друк', 300, 95, 0), 'max': ('Максимум', 600, 100, 0)}
COLORS = {'color': 'Кольоровий', 'gray': 'Відтінки сірого', 'bw': 'Чорно-білий'}
FORMATS = {'jpeg': ('JPEG', '.jpg'), 'tiff': ('TIFF', '.tif')}
MAX_PIXELS = 150e6   # більше — знижуємо DPI сторінки (пам'ять)
JPEG_SIDE = 65000    # межа формату JPEG


def parse_pages(text, n):
    """«усі»/порожньо → 1..n; «1-3,5» → [1, 2, 3, 5]. Номери з 1; поза межами — ValueError."""
    t = (text or '').strip().lower().replace(' ', '')
    if t in ('', 'усі', 'всі', 'все', 'all', '*'): return list(range(1, n + 1))
    out = []
    for part in t.split(','):
        m = re.fullmatch(r'(\d+)(?:[-–](\d*))?', part)
        if not m: raise ValueError('Сторінки: незрозуміло «%s» (приклад: 1-3,5)' % part)
        a = int(m.group(1)); b = a if m.group(2) is None else (int(m.group(2)) if m.group(2) else n)
        if a < 1 or b > n or a > b: raise ValueError('Сторінки %s: у PDF лише %d стор.' % (part, n))
        out += [p for p in range(a, b + 1) if p not in out]
    return out


def unique(path):
    """Не перезаписувати: «x.jpg» → «x (2).jpg», «x (3).jpg» …"""
    if not os.path.exists(path): return path
    b, e = os.path.splitext(path); i = 2
    while os.path.exists('%s (%d)%s' % (b, i, e)): i += 1
    return '%s (%d)%s' % (b, i, e)


def out_dir(pdf, fmt):
    b = os.path.splitext(pdf)[0]
    return '%s (%s)' % (b, FORMATS[fmt][0])


def open_pdf(pdf):
    """Відкрити PDF через файловий об'єкт (кирилиця в шляху). Пароль — зрозуміла помилка."""
    f = open(pdf, 'rb')
    try:
        doc = pdfium.PdfDocument(f, autoclose=True)
    except pdfium.PdfiumError as e:
        f.close()
        msg = str(e)
        if 'password' in msg.lower(): raise ValueError('PDF захищено паролем — зніміть пароль і повторіть')
        raise ValueError('не вдалося відкрити PDF (%s)' % msg)
    return doc


def page_count(pdf):
    doc = open_pdf(pdf)
    try: return len(doc)
    finally: doc.close()


def render(page, dpi, color):
    """Сторінка → PIL у потрібному режимі. Повертає (зображення, фактичний DPI)."""
    w, h = page.get_size()
    px = w * h * (dpi / 72.0) ** 2
    real = dpi
    if px > MAX_PIXELS: real = int(dpi * (MAX_PIXELS / px) ** 0.5)
    bm = page.render(scale=real / 72.0, may_draw_forms=True, draw_annots=True,
                     fill_color=(255, 255, 255, 255), grayscale=(color != 'color'))
    im = bm.to_pil()
    if color == 'color': im = im.convert('RGB')
    else:
        im = im.convert('L')
        if color == 'bw': im = im.point(lambda v: 255 if v >= 128 else 0).convert('1', dither=Image.Dither.NONE)
    return im, real


def save(im, path, fmt, level, dpi):
    if fmt == 'jpeg':
        _, _, q, ss = LEVELS[level]
        im.save(path, 'JPEG', quality=q, subsampling=ss, optimize=True, dpi=(dpi, dpi))
    else:
        im.save(path, 'TIFF', compression='group4' if im.mode == '1' else 'tiff_lzw', dpi=(dpi, dpi))


def convert(pdf, fmt, level, color='color', pages=None, progress=None, log=print):
    """Перетворити вибрані сторінки одного PDF. pages — список номерів з 1 (None = усі).
    progress(k) — після кожної сторінки, k = скільки готово. Повертає список записаних файлів."""
    if fmt not in FORMATS: raise ValueError('формат: jpeg або tiff')
    if level not in LEVELS: raise ValueError('якість: draft, print або max')
    if color not in COLORS: raise ValueError('колір: color, gray або bw')
    if fmt == 'jpeg' and color == 'bw': raise ValueError('Чорно-білий режим — лише для TIFF')
    dpi = LEVELS[level][1]; ext = FORMATS[fmt][1]
    doc = open_pdf(pdf)
    try:
        n = len(doc)
        pages = pages or list(range(1, n + 1))
        bad = [p for p in pages if p < 1 or p > n]
        if bad: raise ValueError('у PDF %d стор., немає: %s' % (n, ', '.join(map(str, bad))))
        try: doc.init_forms()
        except Exception: pass
        od = out_dir(pdf, fmt); os.makedirs(od, exist_ok=True)
        name = os.path.splitext(os.path.basename(pdf))[0]; wd = max(2, len(str(n)))
        out = []
        for k, p in enumerate(pages, 1):
            page = doc[p - 1]
            try:
                im, real = render(page, dpi, color)
            finally:
                page.close()
            if fmt == 'jpeg' and max(im.size) > JPEG_SIDE:
                f = JPEG_SIDE / max(im.size); real = int(real * f)
                im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.LANCZOS)
            if real != dpi:
                log('УВАГА: стор. %d завелика для %d DPI — записано з %d DPI' % (p, dpi, real))
            path = unique(os.path.join(od, '%s_с%0*d%s' % (name, wd, p, ext)))
            save(im, path, fmt, level, real)
            out.append(path)
            log('   стор. %d → %s (%d×%d, %d DPI)' % (p, os.path.basename(path), im.width, im.height, real))
            im.close()
            if progress: progress(k)
        return out
    finally:
        doc.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    if len(a) < 3: raise SystemExit(__doc__)
    pdf, fmt, level = a[0], a[1].lower(), a[2].lower()
    color = a[3].lower() if len(a) > 3 else 'color'
    pages = parse_pages(a[4] if len(a) > 4 else '', page_count(pdf))
    files = convert(pdf, fmt, level, color, pages)
    print('записано: %d файл(ів) у %s' % (len(files), out_dir(pdf, fmt)))
