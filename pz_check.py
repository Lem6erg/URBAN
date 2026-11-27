"""Перевірка пояснювальної записки (DOCX) перед видачею (ТЗ Markdown/urban_pz_cadastre_cz_spec.md, Р1–Р2).
Звіт «<назва> (перевірка).txt» + виправлена копія «<назва> (виправлено).docx»; оригінал не змінюється.
Виправляється лише безпечне: латинські літери-двійники в шифрах норм і в змішаних словах, жовте виділення.
Створено 27.11.2026 (CLAUDE)."""
import os, re, zipfile, datetime
from xml.sax.saxutils import escape, unescape
from pdf_raster import unique

# латинська літера → кирилична-двійник
LAT2CYR = dict(zip('ABCEHIKMOPTXaceiopxy', 'АВСЕНІКМОРТХасеіорху'))
PREFIX = r'(?:ДБН|ДСТУ|ДСН|ДСП|ДСанПіН|ДНАОП|НПАОП|СНиП|СНіП|ВСН|ГБН|СОУ|НАПБ|ДК)'
CODE = re.compile(r'(?<![\w])(%s(?:[\s ]*-?[\s ]*Н)?[\s ]+)([A-Za-z])(?=\.\s?\d)' % PREFIX)
WORD = re.compile(r"[A-Za-zА-ЩЬЮЯҐЄІЇа-щьюяґєії’'ʼ]+")
CYR = re.compile('[А-ЩЬЮЯҐЄІЇа-щьюяґєії]'); LAT = re.compile('[A-Za-z]')
AI = [r'що я змінив', r'\bя (?:змінив|додав|виправив|прибрав|переписав)', r'^\s*ось\b', r'\bзвісно\b', r'сподіваюся',
      r'мовна модель', r'chatgpt', r'\bclaude\b', r'\bgpt\b', r'нижче наведено', r'оновлений текст', r'на аркуші видно',
      r'у файлах не знайш', r'у вихідних даних відсутн', r'\bне знайшов\b', r'уточнити у замовника', r'\btodo\b',
      r'\bfixme\b', r'\*\*', r'^\s*#{1,6}\s', r'```', r'примітка редактора', r'як ші\b', r'штучн\w+ інтелект']
STUB = [r'[XХ]{3,}', r'_{4,}', r'\?{2,}', r'\[(?:уточн|встав|додат|todo)[^\]]*\]', r'\bРозр\.\s*$']
PARTS = re.compile(r'^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$')
PARA = re.compile(r'<w:p[ >].*?</w:p>', re.S)
TNODE = re.compile(r'(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)', re.S)


def para_text(px):
    return ''.join(unescape(m.group(2)) for m in TNODE.finditer(re.sub(r'<w:tab/>', '<w:t>\t</w:t>', px)))


def fix_text(t):
    """→ (новий текст, кількість замінених літер)."""
    n = [0]
    def code(m): n[0] += 1; return m.group(1) + LAT2CYR.get(m.group(2), m.group(2))
    t = CODE.sub(code, t)
    def word(m):
        w = m.group(0); lat = LAT.findall(w)
        if not lat or not CYR.search(w) or any(c not in LAT2CYR for c in lat) or len(CYR.findall(w)) < len(lat): return w
        n[0] += len(lat); return ''.join(LAT2CYR.get(c, c) for c in w)
    t = WORD.sub(word, t)
    return t, n[0]


def _snip(t, i, j, k=40):
    return ('…' if i > k else '') + t[max(0, i - k):j + k].replace('\n', ' ').strip() + ('…' if j + k < len(t) else '')


def check_paras(paras):
    """paras: [(частина, № абзацу, текст)] → {категорія: [рядки]}."""
    R = {k: [] for k in ('code', 'mixed', 'ai', 'stub', 'space', 'num')}
    caps = {}
    for part, n, t in paras:
        where = 'абз. %d' % n if part == 'document' else '%s, абз. %d' % (part, n)
        for m in CODE.finditer(t): R['code'].append('%s: «%s»' % (where, _snip(t, m.start(), m.end())))
        for m in WORD.finditer(t):
            w = m.group(0)
            if LAT.search(w) and CYR.search(w): R['mixed'].append('%s: «%s»' % (where, w))
        for p in AI:
            m = re.search(p, t, re.I | re.M)
            if m: R['ai'].append('%s: «%s»' % (where, _snip(t, m.start(), m.end(), 60))); break
        for p in STUB:
            m = re.search(p, t, re.I)
            if m: R['stub'].append('%s: «%s»' % (where, _snip(t, m.start(), m.end()))); break
        if re.search(r'\S {2,}\S', t): R['space'].append(where)
        m = re.match(r'\s*(Таблиця|Рисунок|Рис\.)\s+(\d+(?:\.\d+)*)', t) if part == 'document' else None
        if m:
            kind = 'Рисунок' if m.group(1).startswith('Рис') else 'Таблиця'
            nums = m.group(2).split('.'); caps.setdefault((kind, '.'.join(nums[:-1])), []).append((int(nums[-1]), where))
    for (kind, pre), lst in sorted(caps.items()):
        seen = [v for v, _ in lst]
        for i, (v, w) in enumerate(lst):
            if v in seen[:i]: R['num'].append('%s: %s %s — повтор номера' % (w, kind, (pre + '.' if pre else '') + str(v)))
        exp = 1
        for v in sorted(set(seen)):
            if v != exp: R['num'].append('%s %s… — пропуск: після %d іде %d' % (kind, (pre + '.' if pre else ''), exp - 1, v))
            exp = v + 1
    return R


def _meta(z):
    out = []
    names = z.namelist()
    if 'docProps/core.xml' in names:
        x = z.read('docProps/core.xml').decode('utf-8', 'replace')
        for tag, lab in (('creator', 'автор'), ('lastModifiedBy', 'змінив'), ('title', 'назва'), ('subject', 'тема'),
                         ('description', 'опис'), ('keywords', 'ключові слова')):
            m = re.search(r'<(?:\w+:)?%s(?:\s[^>]*)?>(.*?)</' % tag, x, re.S)
            if m and m.group(1).strip(): out.append('%s: «%s»' % (lab, unescape(m.group(1).strip())[:80]))
    if 'docProps/app.xml' in names:
        x = z.read('docProps/app.xml').decode('utf-8', 'replace')
        for tag, lab in (('Company', 'організація'), ('Manager', 'менеджер'), ('Template', 'шаблон')):
            m = re.search(r'<%s>(.*?)</%s>' % (tag, tag), x, re.S)
            if m and m.group(1).strip() and m.group(1).strip() != 'Normal.dotm': out.append('%s: «%s»' % (lab, unescape(m.group(1).strip())[:80]))
    if any(n.startswith('word/webextensions/') for n in names): out.append('є надбудови Office (webextensions)')
    if 'docProps/custom.xml' in names: out.append('є власні властивості (custom.xml)')
    return out


def check(src):
    """→ dict(paras, R, colors, red, comments, ins, dele, meta) для DOCX."""
    with zipfile.ZipFile(src) as z:
        paras, hl, red, ins, dele = [], {}, [], 0, 0
        for name in sorted(z.namelist(), key=lambda n: (n != 'word/document.xml', n)):
            m = PARTS.match(name)
            if not m: continue
            x = z.read(name).decode('utf-8', 'replace'); part = m.group(1)
            ins += len(re.findall(r'<w:ins\s', x)); dele += len(re.findall(r'<w:del\s', x))
            for i, pm in enumerate(PARA.finditer(x), 1):
                px = pm.group(0); t = para_text(px)
                if not t.strip(): continue
                paras.append((part, i, t))
                where = 'абз. %d' % i if part == 'document' else '%s, абз. %d' % (part, i)
                for c in re.findall(r'<w:highlight w:val="(\w+)"', px): hl.setdefault(c, []).append(where)
                for c in re.findall(r'<w:shd [^>]*w:fill="(FFFF00)"', px, re.I): hl.setdefault('yellow', []).append(where)
                if re.search(r'<w:color w:val="(?:FF0000|C00000|EE0000)"', px, re.I): red.append('%s: «%s»' % (where, t.strip()[:80]))
        comments = len(re.findall(r'<w:comment\s', z.read('word/comments.xml').decode('utf-8', 'replace'))) \
            if 'word/comments.xml' in z.namelist() else 0
        meta = _meta(z)
    for k in hl: hl[k] = sorted(set(hl[k]), key=hl[k].index)
    return dict(paras=len(paras), R=check_paras(paras), hl=hl, red=red, comments=comments, ins=ins, dele=dele, meta=meta)


def fix_copy(src, dst=None):
    """Виправлена копія: шифри/змішані слова (у межах одного фрагмента тексту), жовте виділення. → (шлях, літер, виділень)."""
    dst = dst or unique('%s (виправлено)%s' % os.path.splitext(src))
    letters = marks = 0
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if PARTS.match(info.filename):
                x = data.decode('utf-8')
                def node(m):
                    nonlocal letters
                    t, n = fix_text(unescape(m.group(2)))
                    if not n: return m.group(0)
                    letters += n; return m.group(1) + escape(t) + m.group(3)
                x = TNODE.sub(node, x)
                x, k1 = re.subn(r'<w:highlight w:val="yellow"/>', '', x)
                x, k2 = re.subn(r'<w:shd [^>]*w:fill="FFFF00"[^>]*/>', '', x, flags=re.I)
                marks += k1 + k2
                data = x.encode('utf-8')
            zout.writestr(info, data)
    return dst, letters, marks


LABELS = [('code', 'Латиниця в шифрах норм (ДБН B.… замість В.…)'), ('mixed', 'Змішані слова (кирилиця + латиниця)'),
          ('ai', 'Залишки чатів / ШІ, редакторські фрази'), ('stub', 'Заглушки (ХХХ, ___, ???, [уточнити])'),
          ('num', 'Нумерація таблиць і рисунків'), ('space', 'Подвійні пробіли всередині абзацу')]


def report(src, fix=True, lim=30):
    """Перевірка + (fix) виправлена копія. → (шлях звіту, шлях копії або None, кількість зауважень)."""
    r = check(src); R = r['R']
    L = ['Перевірка ПЗ — %s' % os.path.basename(src), 'Дата: %s' % datetime.date.today().strftime('%d.%m.%Y'),
         'Абзаців з текстом: %d' % r['paras'], '']
    total = 0
    def block(title, items):
        nonlocal total
        total += len(items)
        L.append('== %s: %d' % (title, len(items)))
        L.extend('   ' + s for s in items[:lim])
        if len(items) > lim: L.append('   … ще %d' % (len(items) - lim))
        L.append('')
    for k, title in LABELS: block(title, R[k])
    block('Виділення кольором', ['%s: %d абз. (%s%s)' % (c, len(v), ', '.join(v[:8]), '…' if len(v) > 8 else '')
                                 for c, v in r['hl'].items()])
    block('Червоний текст (робочі назви — перевірити)', r['red'])
    block('Коментарі Word', ['коментарів: %d' % r['comments']] if r['comments'] else [])
    block('Записані виправлення (рецензування)', ['вставок %d, видалень %d — прийняти або відхилити' % (r['ins'], r['dele'])]
          if r['ins'] or r['dele'] else [])
    block('Метадані файлу (очистити кнопкою «Очищення файлів»)', r['meta'])
    out = None
    if fix:
        out, letters, marks = fix_copy(src)
        r2 = check(out)
        left = len(r2['R']['code']) + len(r2['R']['mixed'])
        L += ['== Виправлена копія: %s' % os.path.basename(out),
              '   замінено латинських літер: %d; знято жовтих виділень: %d' % (letters, marks),
              '   лишилось латиниці в шифрах і змішаних словах: %d%s' % (left, ' (слово розірване між фрагментами тексту'
                                                                       ' або є не-двійники — виправити вручну)' if left else ''),
              '   решту зауважень виправляє автор — у копії вони не змінені.', '']
    txt = unique('%s (перевірка).txt' % os.path.splitext(src)[0])
    with open(txt, 'w', encoding='utf-8-sig') as fh: fh.write('\n'.join(L) + '\n')
    return txt, out, total
