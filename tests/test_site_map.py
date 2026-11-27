"""Тести «Локація» (ТЗ Markdown/urban_site_map_spec.md). Синтетичні DXF у довільній точці Львівщини —
не дані об'єктів."""
import os, sys, shutil, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crs  # noqa: E402
import geo  # noqa: E402
import site_map as M  # noqa: E402

LAT, LON = 49.5, 24.1  # синтетична точка
MSK = 'МСК-46 (Львівська обл.)'


def dxf(path, pts, units=None):
    """ASCII DXF: одна замкнена LWPOLYLINE з вершин pts (+ необов'язковий $INSUNITS)."""
    w = (['0', 'SECTION', '2', 'HEADER', '9', '$INSUNITS', '70', str(units), '0', 'ENDSEC'] if units else [])
    w += ['0', 'SECTION', '2', 'BLOCKS', '0', 'BLOCK', '8', '0', '10', '0.0', '20', '0.0', '0', 'ENDBLK', '0', 'ENDSEC']
    w += ['0', 'SECTION', '2', 'ENTITIES', '0', 'LWPOLYLINE', '8', 'Межі', '90', str(len(pts)), '70', '1']
    for x, y in pts: w += ['10', '%.4f' % x, '20', '%.4f' % y]
    w += ['0', 'ENDSEC', '0', 'EOF']
    open(path, 'w', encoding='cp1251', newline='\r\n').write('\n'.join(w) + '\n')


def square(E, N, half=100.0, k=1.0):
    return [((E + dx) / k, (N + dy) / k) for dx, dy in ((-half, -half), (half, -half), (half, half), (-half, half))]


class Locate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='urban_map_'); self.addCleanup(shutil.rmtree, self.dir, True)
        self.E, self.N = geo.from_wgs(MSK, LAT, LON)

    def f(self, name, pts, units=None):
        p = os.path.join(self.dir, name); dxf(p, pts, units); return p

    def test_msk_metres(self):
        r = M.locate(self.f('m.dxf', square(self.E, self.N)))
        self.assertEqual(r['system'], MSK); self.assertEqual(r['k'], 1.0)
        self.assertAlmostEqual(r['lat'], LAT, places=6); self.assertAlmostEqual(r['lon'], LON, places=6)
        self.assertAlmostEqual(r['span'], 200.0, places=3)

    def test_block_geometry_majority(self):
        """Урок 27.11.2026: у DWG 90 % вершин — геометрія блоків біля нуля; центр має бути на зйомці, а не біля (1; 3,5)."""
        junk = [(i % 7 * 0.1, i % 5 * 0.1) for i in range(400)]
        r = M.locate(self.f('b.dxf', square(self.E, self.N) + square(self.E + 300, self.N + 200) + junk))
        self.assertEqual(r['system'], MSK); self.assertAlmostEqual(r['lat'], geo.to_wgs(MSK, self.E + 150, self.N + 100)[0], places=6)

    def test_millimetres(self):
        r = M.locate(self.f('mm.dxf', square(self.E, self.N, k=0.001)))
        self.assertEqual(r['k'], 0.001); self.assertAlmostEqual(r['lat'], LAT, places=6)

    def test_usk_zone(self):
        z = 'УСК-2000, 3° зона 8 (24°)'; E, N = geo.from_wgs(z, LAT, LON)
        r = M.locate(self.f('u.dxf', square(E, N)))
        self.assertEqual(r['system'], z); self.assertAlmostEqual(r['lon'], LON, places=6)

    def test_sk63_x1_approx(self):
        p = M.SK63['СК-63, зона X1 (наближено)']; E, N = crs.tm_forward(LAT, 23.6, p)
        r = M.locate(self.f('s.dxf', square(E, N)))
        self.assertEqual(r['system'], 'СК-63, зона X1 (наближено)')
        # Пулково-42 → WGS-84 зсуває точку на десятки–сотню метрів, не більше
        self.assertLess(abs(r['lat'] - LAT), 0.002); self.assertLess(abs(r['lon'] - 23.6), 0.003)
        self.assertGreater(abs(r['lat'] - LAT) + abs(r['lon'] - 23.6), 1e-5)

    def test_outliers_near_zero_ignored(self):
        pts = square(self.E, self.N) * 3 + [(0.5, 0.5), (1.0, 2.0)]
        r = M.locate(self.f('o.dxf', pts))
        self.assertAlmostEqual(r['lat'], LAT, places=6); self.assertLess(r['span'], 300)

    def test_manual_system_and_errors(self):
        r = M.locate(self.f('m2.dxf', square(self.E, self.N)), MSK); self.assertEqual(r['system'], MSK)
        with self.assertRaises(ValueError): M.locate(self.f('loc.dxf', square(500, 500)))  # локальні координати
        with self.assertRaises(ValueError): M.locate(self.f('m3.dxf', square(self.E, self.N)), 'немає такої')
        with self.assertRaises(ValueError): M.locate(os.path.join(self.dir, 'x.txt'))

    def test_old_dwg_message(self):
        p = os.path.join(self.dir, 'old.dwg')
        with open(p, 'wb') as fh: fh.write(b'AC1021' + b'\0' * 200)
        with self.assertRaisesRegex(ValueError, 'AC1021'): M.locate(p)

    def test_url_and_zoom(self):
        u = M.gmaps_url(LAT, LON, 200)
        self.assertTrue(u.startswith('https://www.google.com/maps/place/49.500000,24.100000/@49.500000,24.100000,'))
        self.assertGreater(M.zoom(200, LAT), M.zoom(5000, LAT))
        self.assertLessEqual(M.zoom(1, LAT), 19); self.assertGreaterEqual(M.zoom(1e7, LAT), 3)


if __name__ == '__main__':
    unittest.main()
