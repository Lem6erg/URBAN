"""Оновлення URBAN з GitHub Releases (ТЗ: Markdown/urban_autoupdate_spec.md). Без tkinter — логіка окремо від вікна.

Реліз: тег vX.Y.Z, файли URBAN_Setup.exe і URBAN_Setup.exe.sha256. Програма порівнює версію, після згоди
користувача завантажує інсталятор у %TEMP%, перевіряє SHA-256 і запускає його тихо поверх встановленої версії."""
import os, re, sys, json, time, hashlib, subprocess, urllib.request, urllib.error

from version import VERSION, REPO

API = 'https://api.github.com/repos/%s/releases/latest' % REPO
DL_PREFIX = 'https://github.com/%s/releases/download/' % REPO
ASSET = 'URBAN_Setup.exe'
UA = {'User-Agent': 'URBAN-updater/' + VERSION, 'Accept': 'application/vnd.github+json'}
DAY = 24 * 3600


def parse(v):
    """'v1.2.10' → (1, 2, 10); нечислове → ()."""
    m = re.match(r'^\s*v?(\d+(?:\.\d+)*)\s*$', v or '')
    return tuple(int(x) for x in m.group(1).split('.')) if m else ()


def newer(a, b):
    """Чи версія a новіша за b (числове порівняння, бракуючі компоненти = 0)."""
    pa, pb = parse(a), parse(b)
    if not pa or not pb: return False
    n = max(len(pa), len(pb))
    return pa + (0,) * (n - len(pa)) > pb + (0,) * (n - len(pb))


def _get(url, timeout=10):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def release_info(data):
    """Відповідь GitHub API (dict) → {version, notes, url, sha_url} або None, якщо немає інсталятора."""
    if data.get('draft') or data.get('prerelease'): return None
    ver = (data.get('tag_name') or '').lstrip('vV')
    assets = {a.get('name'): a.get('browser_download_url', '') for a in data.get('assets') or []}
    url, sha = assets.get(ASSET, ''), assets.get(ASSET + '.sha256', '')
    if not parse(ver) or not url.startswith(DL_PREFIX) or not sha.startswith(DL_PREFIX): return None
    return dict(version=ver, notes=(data.get('body') or '').strip(), url=url, sha_url=sha)


def latest(timeout=10):
    """Останній випуск на GitHub або None. Мережеві помилки — виняток (викликач вирішує, чи мовчати)."""
    try: data = _get(API, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404: return None  # випусків ще немає
        raise
    return release_info(json.loads(data.decode('utf-8')))


def check(timeout=10):
    """(інформація про новішу версію або None)."""
    info = latest(timeout)
    return info if info and newer(info['version'], VERSION) else None


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def expected_sha(text):
    """Вміст .sha256 ('<hex>  URBAN_Setup.exe' або лише hex) → hex у нижньому регістрі."""
    m = re.search(r'\b([0-9a-fA-F]{64})\b', text or '')
    return m.group(1).lower() if m else ''


def download(info, progress=None, folder=None):
    """Завантажити інсталятор і перевірити SHA-256. Повертає шлях; при незбігу файл видаляється, ValueError."""
    folder = folder or os.path.join(os.environ.get('TEMP') or os.path.expanduser('~'), 'URBAN_update')
    os.makedirs(folder, exist_ok=True)
    want = expected_sha(_get(info['sha_url'], 20).decode('utf-8', 'replace'))
    if not want: raise ValueError('у випуску немає коректної контрольної суми')
    dst = os.path.join(folder, 'URBAN_Setup_%s.exe' % info['version']); part = dst + '.part'
    with urllib.request.urlopen(urllib.request.Request(info['url'], headers=UA), timeout=30) as r, open(part, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0); got = 0
        while True:
            b = r.read(1 << 16)
            if not b: break
            f.write(b); got += len(b)
            if progress and total: progress(got / total)
    if sha256(part) != want:
        os.remove(part); raise ValueError('контрольна сума не збігається — файл пошкоджено, оновлення скасовано')
    if os.path.exists(dst): os.remove(dst)
    os.replace(part, dst)
    return dst


def run_installer(path):
    """Запустити інсталятор тихо (він закриє URBAN, поставить нову версію й запустить її). Викликач завершує програму."""
    subprocess.Popen([path, '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS'],
                     close_fds=True, creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))


def can_install():
    """Ставити оновлення може лише встановлена програма (exe); робоча версія з Python — лише повідомляє."""
    return bool(getattr(sys, 'frozen', False))


def due(settings, now=None):
    """Чи пора автоперевірка (увімкнена і минула доба)."""
    if not settings.get('update_auto', True): return False
    return (now or time.time()) - float(settings.get('update_checked', 0) or 0) >= DAY


def mark_checked(settings, now=None):
    settings['update_checked'] = int(now or time.time()); return settings


if __name__ == '__main__':  # ручна перевірка з консолі
    if sys.stdout: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    i = latest()
    print('встановлено %s; на GitHub: %s' % (VERSION, i['version'] if i else 'немає випуску'))
    print('є оновлення' if i and newer(i['version'], VERSION) else 'оновлень немає')
