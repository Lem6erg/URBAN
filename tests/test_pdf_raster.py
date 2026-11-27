"""Тести PDF → JPEG / TIFF (ТЗ Markdown/urban_pdf_raster_spec.md). Синтетичний PDF створюється в тесті."""
import os, sys, shutil, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw  # noqa: E402
import pdf_raster as R  # noqa: E402


def make_pdf(path, sizes=((200, 100), (100, 150), (144, 72))):
    """PDF зі сторінками заданого розміру в пунктах (растр 72 DPI → 1 px = 1 pt): біле тло, чорна рамка й лінія."""
    pages = []
    for w, h in sizes:
        im = Image.new('RGB', (w, h), 'white'); d = ImageDraw.Draw(im)
        d.rectangle((2, 2, w - 3, h - 3), outline='black'); d.line((0, 0, w, h), fill=(200, 30, 30), width=3)
        pages.append(im)
    pages[0].save(path, 'PDF', resolution=72.0, save_all=True, append_images=pages[1:])


class Pages(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(R.parse_pages('усі', 4), [1, 2, 3, 4])
        self.assertEqual(R.parse_pages('', 2), [1, 2])
        self.assertEqual(R.parse_pages('1-3, 5', 6), [1, 2, 3, 5])
        self.assertEqual(R.parse_pages('3-', 5), [3, 4, 5])
        self.assertEqual(R.parse_pages('2,2,1', 3), [2, 1])
        for bad in ('0', '4', '3-2', 'a', '1-9'):
            with self.assertRaises(ValueError): R.parse_pages(bad, 3)


class Convert(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='urban_pdf_'); self.addCleanup(shutil.rmtree, self.dir, True)
        self.pdf = os.path.join(self.dir, 'Тест аркуш.pdf'); make_pdf(self.pdf)  # кирилиця в шляху

    def near(self, size, w, h, dpi):  # PDFium округлює вгору — допуск 1 px
        for got, pt in zip(size, (w, h)): self.assertLessEqual(abs(got - pt * dpi / 72), 1)

    def run_(self, *a, **k):
        return R.convert(self.pdf, *a, log=lambda s: None, **k)

    def test_jpeg_levels_size_and_dpi(self):
        for lvl, (_, dpi, _, _) in R.LEVELS.items():
            out = self.run_('jpeg', lvl, pages=[1])
            with Image.open(out[0]) as im:
                self.assertEqual(im.format, 'JPEG'); self.assertEqual(im.mode, 'RGB')
                self.near(im.size, 200, 100, dpi)
                self.assertEqual(round(im.info['dpi'][0]), dpi)

    def test_tiff_modes_and_compression(self):
        for col, mode, comp in (('color', 'RGB', 'tiff_lzw'), ('gray', 'L', 'tiff_lzw'), ('bw', '1', 'group4')):
            out = self.run_('tiff', 'draft', col, pages=[2])
            with Image.open(out[0]) as im:
                self.assertEqual(im.mode, mode); self.assertEqual(im.info.get('compression'), comp)
                self.near(im.size, 100, 150, 150)

    def test_bw_is_clean_threshold(self):
        out = self.run_('tiff', 'draft', 'bw', pages=[1])
        with Image.open(out[0]) as im:
            self.assertEqual(set(im.convert('L').getdata()) - {0, 255}, set())
            self.assertIn(0, im.convert('L').getdata())  # рамка не зникла

    def test_names_folder_and_no_overwrite(self):
        a = self.run_('jpeg', 'draft'); b = self.run_('jpeg', 'draft', pages=[1])
        od = R.out_dir(self.pdf, 'jpeg')
        self.assertEqual([os.path.basename(p) for p in a], ['Тест аркуш_с01.jpg', 'Тест аркуш_с02.jpg', 'Тест аркуш_с03.jpg'])
        self.assertTrue(all(os.path.dirname(p) == od for p in a))
        self.assertEqual(os.path.basename(b[0]), 'Тест аркуш_с01 (2).jpg')

    def test_errors(self):
        with self.assertRaises(ValueError): self.run_('jpeg', 'print', 'bw')
        with self.assertRaises(ValueError): self.run_('png', 'print')
        with self.assertRaises(ValueError): self.run_('tiff', 'print', pages=[4])
        broken = os.path.join(self.dir, 'broken.pdf')
        with open(broken, 'wb') as f: f.write(b'%PDF-1.4 not really')
        with self.assertRaises(ValueError): R.convert(broken, 'jpeg', 'draft', log=lambda s: None)

    def test_huge_page_dpi_reduced(self):
        old = R.MAX_PIXELS; R.MAX_PIXELS = 50_000; msgs = []
        try: out = R.convert(self.pdf, 'jpeg', 'max', pages=[1], log=msgs.append)
        finally: R.MAX_PIXELS = old
        with Image.open(out[0]) as im: self.assertLessEqual(im.size[0] * im.size[1], 50_000 * 1.05)
        self.assertTrue(any(m.startswith('УВАГА') for m in msgs))

    def test_progress(self):
        seen = []; self.run_('jpeg', 'draft', progress=seen.append)
        self.assertEqual(seen, [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
