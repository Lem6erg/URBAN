"""Тести оновлення URBAN (ТЗ Markdown/urban_autoupdate_spec.md §5.1). Без мережі: GitHub API — фікстура,
завантаження — локальний HTTP-сервер 127.0.0.1. Запуск: python -m unittest discover -s tests -v"""
import os, sys, json, hashlib, tempfile, threading, unittest, http.server, functools

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import updater  # noqa: E402

DL = updater.DL_PREFIX


def rel(tag='v1.0.1', assets=('URBAN_Setup.exe', 'URBAN_Setup.exe.sha256'), prefix=DL, **kw):
    d = dict(tag_name=tag, body='- виправлення', draft=False, prerelease=False,
             assets=[dict(name=a, browser_download_url=prefix + tag + '/' + a) for a in assets])
    d.update(kw); return d


class Versions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updater.parse('v1.2.10'), (1, 2, 10))
        self.assertEqual(updater.parse('1.0'), (1, 0))
        self.assertEqual(updater.parse('beta'), ())

    def test_newer_numeric_not_text(self):
        self.assertTrue(updater.newer('1.0.10', '1.0.9'))
        self.assertTrue(updater.newer('v1.1.0', '1.0.99'))
        self.assertFalse(updater.newer('1.0.0', '1.0.0'))
        self.assertFalse(updater.newer('1.0', '1.0.0'))
        self.assertFalse(updater.newer('0.9.9', '1.0.0'))
        self.assertFalse(updater.newer('garbage', '1.0.0'))


class ReleaseInfo(unittest.TestCase):
    def test_valid(self):
        i = updater.release_info(rel())
        self.assertEqual(i['version'], '1.0.1')
        self.assertTrue(i['url'].endswith('/v1.0.1/URBAN_Setup.exe'))
        self.assertTrue(i['sha_url'].endswith('.sha256'))

    def test_rejects_draft_prerelease_missing_assets_foreign_host(self):
        self.assertIsNone(updater.release_info(rel(draft=True)))
        self.assertIsNone(updater.release_info(rel(prerelease=True)))
        self.assertIsNone(updater.release_info(rel(assets=('URBAN_Setup.exe',))))
        self.assertIsNone(updater.release_info(rel(prefix='https://evil.example/releases/download/')))
        self.assertIsNone(updater.release_info(rel(tag='latest')))

    def test_check_compares_with_installed(self):
        orig = updater.latest
        try:
            updater.latest = lambda timeout=10: updater.release_info(rel('v' + updater.VERSION))
            self.assertIsNone(updater.check())
            updater.latest = lambda timeout=10: updater.release_info(rel('v99.0.0'))
            self.assertEqual(updater.check()['version'], '99.0.0')
        finally:
            updater.latest = orig


class Schedule(unittest.TestCase):
    def test_due_once_a_day_and_switch(self):
        self.assertTrue(updater.due({}, now=10 ** 9))
        s = updater.mark_checked({}, now=10 ** 9)
        self.assertFalse(updater.due(s, now=10 ** 9 + 3600))
        self.assertTrue(updater.due(s, now=10 ** 9 + updater.DAY))
        self.assertFalse(updater.due({'update_auto': False}, now=10 ** 9))


class Download(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='urban_upd_test_')
        cls.payload = os.urandom(300_000)
        with open(os.path.join(cls.dir, 'URBAN_Setup.exe'), 'wb') as f: f.write(cls.payload)
        good = hashlib.sha256(cls.payload).hexdigest()
        with open(os.path.join(cls.dir, 'good.sha256'), 'w') as f: f.write(good + '  URBAN_Setup.exe\n')
        with open(os.path.join(cls.dir, 'bad.sha256'), 'w') as f: f.write('0' * 64 + '  URBAN_Setup.exe\n')
        h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=cls.dir)
        h.log_message = lambda *a: None
        cls.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), h)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:%d/' % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        import shutil; shutil.rmtree(cls.dir, ignore_errors=True)

    def tmp(self):
        import shutil
        d = tempfile.mkdtemp(prefix='urban_upd_out_'); self.addCleanup(shutil.rmtree, d, True); return d

    def info(self, sha):
        return dict(version='9.9.9', notes='', url=self.base + 'URBAN_Setup.exe', sha_url=self.base + sha)

    def test_good_checksum(self):
        out = self.tmp(); seen = []
        p = updater.download(self.info('good.sha256'), seen.append, folder=out)
        with open(p, 'rb') as f: self.assertEqual(f.read(), self.payload)
        self.assertAlmostEqual(seen[-1], 1.0)
        self.assertEqual(os.listdir(out), [os.path.basename(p)])

    def test_bad_checksum_leaves_nothing(self):
        out = self.tmp()
        with self.assertRaises(ValueError): updater.download(self.info('bad.sha256'), folder=out)
        self.assertEqual(os.listdir(out), [])

    def test_expected_sha_formats(self):
        h = 'A' * 64
        self.assertEqual(updater.expected_sha(h), 'a' * 64)
        self.assertEqual(updater.expected_sha(h + '  URBAN_Setup.exe\n'), 'a' * 64)
        self.assertEqual(updater.expected_sha('немає'), '')


if __name__ == '__main__':
    unittest.main()
