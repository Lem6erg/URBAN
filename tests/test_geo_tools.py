"""Тести geo / KML ↔ DXF / калькулятора / прив'язки растру / очищення (ТЗ Markdown/urban_geo_tools_spec.md).
Лише синтетичні дані: точки в довільному місці Львівщини, документи створюються в тесті."""
import os, sys, math, shutil, tempfile, unittest, zipfile, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import geo, kml_dxf, coord_calc, raster_geo, file_clean  # noqa: E402

MSK = 'МСК-46 (Львівська обл.)'; USK8 = 'УСК-2000, 3° зона 8 (24°)'; X1 = 'СК-63, зона X1 (наближено)'


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='urban_geo_'); self.addCleanup(shutil.rmtree, self.dir, True)

    def p(self, name): return os.path.join(self.dir, name)


class Geo(unittest.TestCase):
    def test_round_trip_all_systems(self):
        for s in geo.systems():
            E, N = geo.from_wgs(s, 49.6, 24.0); la, lo = geo.to_wgs(s, E, N)
            self.assertLess(abs(la - 49.6) + abs(lo - 24.0), 1e-8, s)

    def test_ellipsoid_shift_applied(self):
        # УСК-2000 на Красовському: широта WGS-84 відрізняється на ~2–3 м від «сирої» широти Красовського
        import crs
        E, N = crs.tm_forward(49.5, 24.1, crs.load_proj()[MSK]); la, _ = geo.to_wgs(MSK, E, N)
        self.assertTrue(1.0 < abs(la - 49.5) * 111200 < 5.0)

    def test_exact_path_between_projections(self):
        E, N = geo.from_wgs(MSK, 49.5, 24.1)
        e2, n2 = geo.converter(MSK, USK8)(E, N)
        self.assertAlmostEqual(e2 - 8200000, E - 0, delta=0.001)  # λ0 обох 24°, FE 300 000 vs 8 500 000
        self.assertAlmostEqual(n2, N, delta=0.001)


class Calc(unittest.TestCase):
    def test_parse_formats(self):
        r = coord_calc.parse('Т1 5485333.5 307243.7\nТ2;5496450,9;300000\n\n# коментар\n5490000\t303000')
        self.assertEqual([x[0] for x in r], ['Т1', 'Т2', '3'])
        self.assertEqual(r[1][1:3], (5496450.9, 300000.0))
        with self.assertRaises(ValueError): coord_calc.parse('Т1 abc 5')

    def test_wgs_round_trip_and_order(self):
        _, t = coord_calc.convert('A 49.5 24.1', geo.WGS, MSK, 'XY')
        x, y = map(float, t.split('\t')[1:])
        self.assertGreater(x, 5e6); self.assertLess(y, 1e6)  # X — північ першою
        _, t2 = coord_calc.convert(t, MSK, geo.WGS, 'XY')
        la, lo = map(float, t2.split('\t')[1:]); self.assertAlmostEqual(la, 49.5, 7); self.assertAlmostEqual(lo, 24.1, 7)
        _, t3 = coord_calc.convert('A %s %s' % (y, x), MSK, geo.WGS, 'EN')
        self.assertEqual(t3, t2)


class Kml(Tmp):
    KML = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           '<Folder><name>Межа</name><Placemark><name>ДПТ</name><Polygon><outerBoundaryIs><LinearRing><coordinates>'
           '24.1,49.5,0 24.102,49.5,0 24.102,49.501,0 24.1,49.501,0 24.1,49.5,0</coordinates></LinearRing></outerBoundaryIs>'
           '</Polygon></Placemark></Folder><Placemark><name>Т1</name><Point><coordinates>24.101,49.5005,0</coordinates></Point>'
           '</Placemark><Placemark><LineString><coordinates>24.099,49.4995 24.103,49.5015</coordinates></LineString></Placemark>'
           '</Document></kml>')

    def test_kml_dxf_kml(self):
        k = self.p('a.kml'); open(k, 'w', encoding='utf-8').write(self.KML)
        d, n = kml_dxf.kml_to_dxf(k, MSK); self.assertEqual(n, 3)
        objs = kml_dxf.dxf_objects(d)
        poly = [o for o in objs if o['closed']][0]
        self.assertEqual(poly['layer'], 'Межа'); self.assertEqual(len(poly['pts']), 4)
        E, N = geo.from_wgs(MSK, 49.5, 24.1); self.assertAlmostEqual(poly['pts'][0][0], E, delta=0.001)
        k2, s, n2 = kml_dxf.to_kml(d); self.assertEqual(s, MSK); self.assertEqual(n2, 3)
        back = kml_dxf.read_kml(k2); pol = [o for o in back if o['kind'] == 'poly'][0]
        self.assertAlmostEqual(pol['pts'][0][0], 49.5, 7); self.assertAlmostEqual(pol['pts'][0][1], 24.1, 7)

    def test_kmz_and_no_overwrite(self):
        z = self.p('b.kmz')
        with zipfile.ZipFile(z, 'w') as f: f.writestr('doc.kml', self.KML)
        d1, _ = kml_dxf.kml_to_dxf(z, MSK); d2, _ = kml_dxf.kml_to_dxf(z, MSK)
        self.assertNotEqual(d1, d2); self.assertTrue(d2.endswith(' (2).dxf'))

    def test_dxf_polyline_vertex_reading(self):
        E, N = geo.from_wgs(MSK, 49.5, 24.1)
        s = ['0', 'SECTION', '2', 'ENTITIES', '0', 'POLYLINE', '8', 'L1', '66', '1', '10', '0.0', '20', '0.0', '70', '1']
        for dx, dy in ((0, 0), (50, 0), (50, 50)): s += ['0', 'VERTEX', '8', 'L1', '10', str(E + dx), '20', str(N + dy)]
        s += ['0', 'SEQEND', '0', 'LINE', '8', 'L2', '10', str(E), '20', str(N), '11', str(E + 10), '21', str(N + 10),
              '0', 'POINT', '8', 'L3', '10', str(E), '20', str(N), '0', 'ENDSEC', '0', 'EOF']
        f = self.p('c.dxf'); open(f, 'w', encoding='cp1251').write('\n'.join(s) + '\n')
        o = kml_dxf.dxf_objects(f)
        self.assertEqual([(x['layer'], len(x['pts']), x['closed']) for x in o], [('L1', 3, True), ('L2', 2, False), ('L3', 1, False)])


class Raster(Tmp):
    def test_fit_exact_and_residuals(self):
        th, s = math.radians(15), 0.5
        g = lambda px, py: (1000 + s * (px * math.cos(th) + py * math.sin(th)), 2000 + s * (px * math.sin(th) - py * math.cos(th)))
        pts = [(px, py) + g(px, py) for px, py in ((10, 10), (300, 20), (150, 250), (20, 280))]
        for n in (2, 3, 4):
            M, res, rms = raster_geo.fit(pts[:n])
            e = [a - b for a, b in zip(raster_geo.apply(M, 77, 99), g(77, 99))]
            self.assertLess(math.hypot(*e), 1e-6)
            self.assertEqual(rms == rms, n == 4)  # СКП лише з надлишковими точками
        bad = pts[:3] + [(pts[3][0], pts[3][1], pts[3][2] + 2.0, pts[3][3])]
        _, res, rms = raster_geo.fit(bad); self.assertGreater(max(res), 0.3)
        with self.assertRaises(ValueError): raster_geo.fit([(0, 0, 1, 1), (10, 0, 2, 1), (20, 0, 3, 1)])  # на одній прямій

    def test_rectify_outputs(self):
        from PIL import Image
        src = self.p('скан.png'); Image.new('RGB', (200, 100), 'white').save(src)
        pts = [(0, 0, 500.0, 1100.0), (200, 0, 600.0, 1100.0), (0, 100, 500.0, 1050.0)]
        r = raster_geo.rectify(src, pts, shift=(500.0, 1000.0))
        self.assertAlmostEqual(r['pixel'], 0.5, 9)
        self.assertAlmostEqual(r['corner_ll'][0], 0.0, 6); self.assertAlmostEqual(r['corner_ll'][1], 50.0, 6)
        self.assertAlmostEqual(r['size_m'][0], 100.0, 6)
        w = [float(x) for x in open(r['world']).read().split()]
        self.assertEqual(len(w), 6); self.assertAlmostEqual(w[0], 0.5); self.assertAlmostEqual(w[3], -0.5)
        self.assertAlmostEqual(w[4], 0.25 - 0.0, 6)  # центр першого пікселя після зсуву: 500.25 − 500
        with Image.open(r['png']) as im: self.assertEqual(im.size, (200, 100))


def make_docx(path):
    files = {
        '[Content_Types].xml': '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                               '<Override PartName="/docProps/custom.xml" ContentType="x"/><Override PartName="/word/document.xml" ContentType="y"/></Types>',
        '_rels/.rels': '<?xml version="1.0"?><Relationships xmlns="r"><Relationship Id="1" Target="word/document.xml"/>'
                       '<Relationship Id="2" Target="docProps/custom.xml"/><Relationship Id="3" Target="word/webextensions/taskpanes.xml"/></Relationships>',
        'docProps/core.xml': '<?xml version="1.0"?><cp:coreProperties xmlns:cp="c" xmlns:dc="d"><dc:title>Чужий об\'єкт</dc:title>'
                             '<dc:creator>Старий Автор</dc:creator><cp:lastModifiedBy>Хтось</cp:lastModifiedBy><cp:keywords>к</cp:keywords></cp:coreProperties>',
        'docProps/app.xml': '<?xml version="1.0"?><Properties xmlns="a"><Template>Зразок.dotm</Template><Company>Стара фірма</Company></Properties>',
        'docProps/custom.xml': '<x/>', 'word/webextensions/taskpanes.xml': '<x/>',
        'word/document.xml': '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>Текст ПЗ</w:t></w:r></w:p></w:body></w:document>'}
    with zipfile.ZipFile(path, 'w') as z:
        for n, d in files.items(): z.writestr(n, d)


class Clean(Tmp):
    def test_docx_metadata_only(self):
        src = self.p('ПЗ.docx'); make_docx(src)
        dst, ch = file_clean.clean(src, 'Новий Автор', 'Нова фірма')
        self.assertTrue(dst.endswith('ПЗ (чисто).docx')); self.assertTrue(os.path.exists(src))
        z = zipfile.ZipFile(dst); n = z.namelist()
        core, app = z.read('docProps/core.xml').decode(), z.read('docProps/app.xml').decode()
        self.assertIn('<dc:creator>Новий Автор</dc:creator>', core); self.assertIn('<cp:lastModifiedBy>Новий Автор</cp:lastModifiedBy>', core)
        self.assertNotIn('title', core); self.assertNotIn('keywords', core)
        self.assertIn('<Company>Нова фірма</Company>', app); self.assertNotIn('Template', app)
        self.assertNotIn('docProps/custom.xml', n); self.assertFalse(any('webextensions' in x for x in n))
        self.assertNotIn('custom.xml', z.read('_rels/.rels').decode()); self.assertNotIn('webextensions', z.read('_rels/.rels').decode())
        self.assertNotIn('custom.xml', z.read('[Content_Types].xml').decode())
        self.assertEqual(z.read('word/document.xml'), zipfile.ZipFile(src).read('word/document.xml'))
        import xml.dom.minidom as md
        for x in ('docProps/core.xml', 'docProps/app.xml', '_rels/.rels', '[Content_Types].xml'): md.parseString(z.read(x))
        self.assertTrue(any('Старий Автор' in c for c in ch))

    def test_empty_author_erases(self):
        src = self.p('a.docx'); make_docx(src); dst, _ = file_clean.clean(src, '', '')
        z = zipfile.ZipFile(dst)
        self.assertNotIn('Старий Автор', z.read('docProps/core.xml').decode()); self.assertNotIn('Стара фірма', z.read('docProps/app.xml').decode())

    def test_pdf(self):
        from pypdf import PdfWriter, PdfReader
        src = self.p('a.pdf'); w = PdfWriter(); w.add_blank_page(100, 100)
        w.add_metadata({'/Author': 'Старий', '/Title': 'Чужий', '/Creator': 'Archicad', '/Producer': 'X'})
        with open(src, 'wb') as f: w.write(f)
        dst, ch = file_clean.clean(src, 'Новий')
        m = PdfReader(dst).metadata
        self.assertEqual(m.get('/Author'), 'Новий'); self.assertFalse(m.get('/Title')); self.assertFalse(m.get('/Creator'))
        self.assertEqual(len(PdfReader(dst).pages), 1)
        with self.assertRaises(ValueError): file_clean.clean(self.p('x.txt'))


if __name__ == '__main__':
    unittest.main()
