"""Перевірка ПЗ, XML ДЗК → DXF, межа → KML і ЦЗ (мережа підмінена). Синтетичні дані. Створено 27.11.2026 (CLAUDE)."""
import os, sys, shutil, tempfile, unittest, zipfile, re
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import geo, pz_check, dzk_xml, cz_routes, kml_dxf

MSK = 'МСК-46 (Львівська обл.)'
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(path, paras, extra=None):
    body = ''.join('<w:p>%s</w:p>' % r for r in paras)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('word/document.xml', '<?xml version="1.0" encoding="UTF-8"?><w:document %s><w:body>%s</w:body></w:document>' % (W, body))
        z.writestr('docProps/core.xml', '<?xml version="1.0"?><cp:coreProperties xmlns:cp="c" xmlns:dc="d"><dc:creator>Тест Автор</dc:creator>'
                   '<dc:title>Зразок</dc:title></cp:coreProperties>')
        for k, v in (extra or {}).items(): z.writestr(k, v)


def run(t, rpr=''):
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (('<w:rPr>%s</w:rPr>' % rpr) if rpr else '', t)


class PzCheck(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.f = os.path.join(self.d, 'ПЗ тест.docx')
        make_docx(self.f, [
            run('Відповідно до ДБН B.2.2-12:2019 та ДБН Б.1.1-14:2021.'),         # латинська B
            run('Територія рoзташована на пiвдні.'),                              # змішані слова (o, i латинські)
            run('Що я змінив принципово: переписав розділ.'),                      # залишок чату
            run('Площа ХХХХ га.'),                                                # заглушка
            run('Виділений текст', '<w:highlight w:val="yellow"/>'),
            run('Робоча назва', '<w:color w:val="FF0000"/>'),
            run('Таблиця 1 – Баланс'), run('Таблиця 2 – ТЕП'), run('Таблиця 2 – Мережі'), run('Таблиця 4 – Інше'),
            run('Два  пробіли'),
            run('ДБН ') + run('B.1.1-7'),                                         # шифр розірваний між фрагментами
        ], {'word/comments.xml': '<w:comments %s><w:comment w:id="1"/></w:comments>' % W})

    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)

    def test_report_and_fix(self):
        txt, out, n = pz_check.report(self.f, True)
        t = open(txt, encoding='utf-8-sig').read()
        self.assertIn('Латиниця в шифрах норм (ДБН B.… замість В.…): 2', t)
        self.assertRegex(t, r'Змішані слова \(кирилиця \+ латиниця\): 2')
        self.assertIn('Залишки чатів / ШІ, редакторські фрази: 1', t)
        self.assertIn('Заглушки (ХХХ, ___, ???, [уточнити]): 1', t)
        self.assertIn('повтор номера', t); self.assertIn('після 2 іде 4', t)
        self.assertIn('коментарів: 1', t); self.assertIn('автор: «Тест Автор»', t)
        self.assertIn('Червоний текст', t); self.assertIn('yellow: 1 абз.', t)
        x = zipfile.ZipFile(out).read('word/document.xml').decode('utf-8')
        self.assertIn('ДБН В.2.2-12', x); self.assertIn('розташована на півдні', x)
        self.assertNotIn('w:highlight', x)
        self.assertIn('ДБН Б.1.1-14', x)  # кирилиця не змінена
        self.assertIn('лишилось латиниці в шифрах і змішаних словах: 1 (слово розірване', t)  # «ДБН » і «B.1.1-7» — різні фрагменти
        # оригінал не змінено
        self.assertIn('ДБН B.2.2-12', zipfile.ZipFile(self.f).read('word/document.xml').decode('utf-8'))

    def test_fix_text_keeps_latin_words(self):
        self.assertEqual(pz_check.fix_text('PDF-файл Wi-Fi ДСТУ-Н B.1.1-27')[0], 'PDF-файл Wi-Fi ДСТУ-Н В.1.1-27')
        self.assertEqual(pz_check.fix_text('Частина IІ')[0], 'Частина ІІ')


def dzk_sample(path, E0=300000.0, N0=5520000.0):
    """Ділянка 40×25 м = 0,1000 га (кути 1–4) з обмеженням-трикутником; X — північ, Y — схід."""
    P = [(1, N0, E0), (2, N0 + 25, E0), (3, N0 + 25, E0 + 40), (4, N0, E0 + 40), (5, N0 + 5, E0 + 5), (6, N0 + 15, E0 + 5), (7, N0 + 5, E0 + 15)]
    pts = ''.join('<Point><UIDP>%d</UIDP><PN>%d</PN><X>%.2f</X><Y>%.2f</Y></Point>' % (i, i, x, y) for i, x, y in P)
    pl = '<PL><ULID>1</ULID><Points><P>1</P><P>2</P><P>3</P></Points></PL><PL><ULID>2</ULID><Points><P>1</P><P>4</P><P>3</P></Points></PL>' \
         '<PL><ULID>3</ULID><Points><P>5</P><P>6</P><P>7</P><P>5</P></Points></PL>'
    x = ('<?xml version="1.0" encoding="windows-1251"?><UkrainianCadastralExchangeFile><InfoPart><MetricInfo>'
         '<CoordinateSystem><Local>МСК-46</Local></CoordinateSystem><PointInfo>%s</PointInfo><Polylines>%s</Polylines></MetricInfo>'
         '<CadastralZoneInfo><KOATUU>1234567890</KOATUU><CadastralZoneNumber>01</CadastralZoneNumber><CadastralQuarters>'
         '<CadastralQuarterInfo><CadastralQuarterNumber>002</CadastralQuarterNumber><Parcels><ParcelInfo>'
         '<ParcelMetricInfo><ParcelID>0003</ParcelID><Area><MeasurementUnit>га</MeasurementUnit><Size>0.1000</Size></Area>'
         '<Externals><Boundary><Lines><Line><ULID>1</ULID><FP>1</FP><TP>3</TP></Line><Line><ULID>2</ULID><FP>3</FP><TP>1</TP></Line>'
         '</Lines></Boundary></Externals></ParcelMetricInfo>'
         '<CategoryPurposeInfo><Category>Землі житлової та громадської забудови</Category><Purpose>02.01</Purpose></CategoryPurposeInfo>'
         '<OwnershipInfo><Code>100</Code></OwnershipInfo>'
         '<Restrictions><RestrictionInfo><RestrictionCode>01.08</RestrictionCode><RestrictionName>Охоронна зона</RestrictionName>'
         '<Externals><Boundary><Lines><Line><ULID>3</ULID></Line></Lines></Boundary></Externals></RestrictionInfo></Restrictions>'
         '</ParcelInfo></Parcels></CadastralQuarterInfo></CadastralQuarters></CadastralZoneInfo></InfoPart>'
         '</UkrainianCadastralExchangeFile>') % (pts, pl)
    with open(path, 'w', encoding='cp1251') as fh: fh.write(x)


class Dzk(unittest.TestCase):
    def setUp(self): self.d = tempfile.mkdtemp(); self.f = os.path.join(self.d, 'ділянка.xml'); dzk_sample(self.f)
    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)

    def test_parse(self):
        d = dzk_xml.parse(self.f)
        self.assertEqual(d['info']['kn'], '1234567890:01:002:0003')
        kinds = sorted(o['kind'] for o in d['objects']); self.assertEqual(kinds, ['Ділянка', 'Обмеження'])
        parcel = [o for o in d['objects'] if o['kind'] == 'Ділянка'][0]
        self.assertEqual(len(parcel['rings'][0]), 4); self.assertAlmostEqual(parcel['area_decl'], 1000.0)

    def test_dxf(self):
        r = dzk_xml.to_dxf(self.f)
        self.assertAlmostEqual(r['area'], 1000.0, places=3); self.assertEqual(r['system'], MSK)
        objs = kml_dxf.dxf_objects(r['dxf'])
        lays = sorted({o['layer'] for o in objs}); self.assertEqual(lays, ['ДЗК - Ділянка', 'ДЗК - Обмеження', 'ДЗК - Точки'])
        par = [o for o in objs if o['layer'] == 'ДЗК - Ділянка'][0]
        self.assertTrue(par['closed']); self.assertIn((300040.0, 5520025.0), par['pts'])  # E = Y, N = X
        self.assertIn('Площа за контуром: 0.1000 га', open(r['txt'], encoding='utf-8-sig').read())

    def test_dxf_converted(self):
        r = dzk_xml.to_dxf(self.f, 'УСК-2000, 3° зона 8 (24°)')
        par = [o for o in kml_dxf.dxf_objects(r['dxf']) if o['layer'] == 'ДЗК - Ділянка'][0]
        E, N = geo.converter(MSK, 'УСК-2000, 3° зона 8 (24°)')(300000.0, 5520000.0)
        self.assertTrue(any(abs(x - E) < 0.01 and abs(y - N) < 0.01 for x, y in par['pts']))

    def test_kn_url(self):
        self.assertEqual(dzk_xml.kn_url(' 1234567890:01:002:0003 '), 'https://kadastr.com.ua/parcel/1234567890:01:002:0003')
        with self.assertRaises(ValueError): dzk_xml.kn_url('12345:1:2')

    def test_not_dzk(self):
        p = os.path.join(self.d, 'x.xml'); open(p, 'w').write('<a/>')
        with self.assertRaises(ValueError): dzk_xml.parse(p)


def dxf_survey(path, E0=300000.0, N0=5520000.0):
    """Межа 100×50 м на шарі «Межа ДПТ», укриття — POINT та INSERT на шарі «Укриття», дорога — лінія."""
    def pl(layer, P, closed):
        s = '0\nPOLYLINE\n8\n%s\n66\n1\n70\n%d\n' % (layer, closed)
        s += ''.join('0\nVERTEX\n8\n%s\n10\n%.3f\n20\n%.3f\n' % (layer, x, y) for x, y in P)
        return s + '0\nSEQEND\n8\n%s\n' % layer
    e = pl('Межа ДПТ', [(E0, N0), (E0 + 100, N0), (E0 + 100, N0 + 50), (E0, N0 + 50)], 1)
    e += pl('Дорога', [(E0 - 200, N0 - 10), (E0 + 300, N0 - 10)], 0)
    e += '0\nPOINT\n8\nУкриття\n10\n%.3f\n20\n%.3f\n30\n0\n' % (E0 + 400, N0 + 300)
    e += '0\nINSERT\n8\nУкриття\n2\nBLK\n10\n%.3f\n20\n%.3f\n30\n0\n' % (E0 - 300, N0 - 200)
    with open(path, 'w', encoding='cp1251') as fh: fh.write('0\nSECTION\n2\nENTITIES\n%s0\nENDSEC\n0\nEOF\n' % e)


class Cz(unittest.TestCase):
    def setUp(self): self.d = tempfile.mkdtemp(); self.f = os.path.join(self.d, 'зйомка.dxf'); dxf_survey(self.f)
    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)

    def test_layers(self):
        L = cz_routes.layers(self.f)
        self.assertEqual(L['Межа ДПТ'], (1, 1)); self.assertEqual(L['Укриття'], (0, 2)); self.assertEqual(L['Дорога'], (0, 1))

    def test_boundary_kml(self):
        dst, s, n, a = cz_routes.boundary_kml(self.f, 'Межа ДПТ')
        self.assertEqual((s, n), (MSK, 1)); self.assertAlmostEqual(a, 5000.0, places=3)
        k = open(dst, encoding='utf-8').read(); self.assertIn('Площа 0.5000 га', k)
        la, lo = geo.to_wgs(MSK, 300000.0, 5520000.0)
        self.assertIn('%.8f,%.8f,0' % (lo, la), k)
        with self.assertRaises(ValueError): cz_routes.boundary_kml(self.f, 'Дорога')

    def test_compute_offline(self):
        o = geo.to_wgs(MSK, 300050.0, 5520025.0)  # центр межі
        fire = geo.to_wgs(MSK, 302000.0, 5521000.0)
        def fake_route(prof, a, b):
            return dict(m=cz_routes.haversine(a, b) * 1.3, s=600.0, line=[a, b])
        osm = {'fire': [dict(name='ПЧ-1', lat=fire[0], lon=fire[1], addr='вул. Тестова, 1')], 'hospital': []}
        with mock.patch.object(cz_routes, 'route', fake_route), mock.patch.object(cz_routes, 'osm_objects', return_value=osm), \
                mock.patch.object(cz_routes, 'address', return_value='вул. Синтетична'), mock.patch.object(cz_routes.time, 'sleep'):
            r = cz_routes.compute(self.f, ['shelter_dxf', 'fire', 'hospital'], None, 'Межа ДПТ', 'Укриття', log=lambda s: None)
        self.assertAlmostEqual(r['origin'][0], o[0], places=7); self.assertAlmostEqual(r['origin'][1], o[1], places=7)
        kinds = [x['kind'] for x in r['rows']]; self.assertEqual(kinds.count('shelter_dxf'), 2); self.assertEqual(kinds.count('fire'), 1)
        sh = sorted(x['straight'] for x in r['rows'] if x['kind'] == 'shelter_dxf')
        # від центру (50, 25): INSERT (−300, −200) і POINT (400, 300); допуск — масштаб проєкції проти сфери
        self.assertAlmostEqual(sh[0], (350 ** 2 + 225 ** 2) ** 0.5, delta=3.0)
        self.assertAlmostEqual(sh[1], (350 ** 2 + 275 ** 2) ** 0.5, delta=3.0)
        objs = kml_dxf.dxf_objects(r['dxf'])
        self.assertIn('ЦЗ - Пожежна частина - маршрути', {x['layer'] for x in objs})
        pts = [x for x in objs if x['layer'] == 'ЦЗ - Пожежна частина' and x['kind'] == 'point'][0]['pts'][0]
        self.assertAlmostEqual(pts[0], 302000.0, delta=0.01); self.assertAlmostEqual(pts[1], 5521000.0, delta=0.01)
        t = open(r['txt'], encoding='utf-8-sig').read(); self.assertIn('ПЧ-1', t); self.assertIn('вул. Синтетична', t)

    def test_osm_unavailable(self):
        with mock.patch.object(cz_routes, '_get', side_effect=OSError('offline')), mock.patch.object(cz_routes.time, 'sleep'):
            logs = []
            r = cz_routes.compute(self.f, ['fire'], None, None, None, log=logs.append)
        self.assertEqual(r['rows'], []); self.assertTrue(any('Overpass недоступний' in l for l in logs))


if __name__ == '__main__':
    unittest.main()
