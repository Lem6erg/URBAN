"""Очищення метаданих перед відправкою замовнику (ТЗ Markdown/urban_geo_tools_spec.md, Р3, Р4, Р10).
DOCX/XLSX/PPTX: автор, змінив, організація, менеджер, назва, тема, ключові слова, опис, категорія, шаблон,
власні властивості (custom.xml), надбудови (webextensions). Вміст документа, коментарі й виділення не змінюються.
PDF: Author = поле; Title, Subject, Keywords, Creator, Producer — стерти; XMP — прибрати.
Результат — копія поруч «<назва> (чисто).<розш>»; оригінал не змінюється.
Створено 27.11.2026 (CLAUDE)."""
import os, re, zipfile
from xml.sax.saxutils import escape
from pdf_raster import unique

OOXML = ('.docx', '.docm', '.xlsx', '.xlsm', '.pptx', '.pptm', '.dotx')
CORE_CLEAR = ('title', 'subject', 'keywords', 'description', 'category', 'contentStatus', 'identifier', 'version', 'lastPrinted')
APP_CLEAR = ('Manager', 'Template', 'HyperlinkBase')


def _set_el(xml, tag, value):
    """Замінити/стерти вміст елемента <prefix:tag …>…</prefix:tag> (або порожнього <…/>)."""
    pat = re.compile(r'<((?:\w+:)?%s)(\s[^>]*)?(?:/>|>.*?</\1>)' % re.escape(tag), re.S)
    if value is None: return pat.sub('', xml)
    return pat.sub(lambda m: '<%s%s>%s</%s>' % (m.group(1), m.group(2) or '', escape(value), m.group(1)), xml)


def _old(xml, tag):
    m = re.search(r'<(?:\w+:)?%s(?:\s[^>]*)?>(.*?)</' % re.escape(tag), xml, re.S)
    return m.group(1).strip() if m else ''


def clean_ooxml(src, author='', org='', dst=None):
    """→ (шлях, список змін). author/org порожні — поля стираються."""
    dst = dst or unique('%s (чисто)%s' % os.path.splitext(src))
    changes = []
    with zipfile.ZipFile(src) as zin:
        names = zin.namelist()
        drop = {n for n in names if n.startswith(('word/webextensions/', 'xl/webextensions/', 'ppt/webextensions/'))
                or n in ('docProps/custom.xml',)}
        if any('webextensions' in n for n in drop): changes.append('прибрано надбудови (webextensions)')
        if 'docProps/custom.xml' in drop: changes.append('прибрано власні властивості (custom.xml)')
        with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                n = info.filename
                if n in drop: continue
                data = zin.read(n)
                if n == 'docProps/core.xml':
                    x = data.decode('utf-8')
                    for tag, val in (('creator', author), ('lastModifiedBy', author)):
                        o = _old(x, tag)
                        if o != val: changes.append('%s: «%s» → «%s»' % ('автор' if tag == 'creator' else 'змінив', o, val))
                        x = _set_el(x, tag, val) if (val or o) else x
                    for tag in CORE_CLEAR:
                        o = _old(x, tag)
                        if o: changes.append('стерто %s: «%s»' % (tag, o[:60])); x = _set_el(x, tag, None)
                    data = x.encode('utf-8')
                elif n == 'docProps/app.xml':
                    x = data.decode('utf-8'); o = _old(x, 'Company')
                    if o != org: changes.append('організація: «%s» → «%s»' % (o, org))
                    if '<Company' in x: x = _set_el(x, 'Company', org)
                    elif org: x = x.replace('</Properties>', '<Company>%s</Company></Properties>' % escape(org))
                    for tag in APP_CLEAR:
                        o = _old(x, tag)
                        if o: changes.append('стерто %s: «%s»' % (tag, o[:60])); x = _set_el(x, tag, None)
                    data = x.encode('utf-8')
                elif n == '[Content_Types].xml' and drop:
                    x = data.decode('utf-8')
                    for d in drop: x = re.sub(r'<Override[^>]*PartName="/%s"[^>]*/>' % re.escape(d), '', x)
                    data = x.encode('utf-8')
                elif n.endswith('.rels') and drop:
                    x = data.decode('utf-8')
                    x = re.sub(r'<Relationship[^>]*Target="[^"]*(?:webextensions/|custom\.xml)[^"]*"[^>]*/>', '', x)
                    data = x.encode('utf-8')
                zout.writestr(info, data)
    return dst, changes


def clean_pdf(src, author='', dst=None):
    from pypdf import PdfReader, PdfWriter
    dst = dst or unique('%s (чисто)%s' % os.path.splitext(src))
    r = PdfReader(src)
    if r.is_encrypted: raise ValueError('PDF захищено паролем')
    old = {k: str(v) for k, v in (r.metadata or {}).items()}
    w = PdfWriter(clone_from=r)
    w.xmp_metadata = None                                     # XMP
    w.metadata = None                                         # старий Info повністю
    w.add_metadata({'/Author': author, '/Producer': '', '/Creator': ''})
    with open(dst, 'wb') as fh: w.write(fh)
    changes = ['%s: «%s»' % (k.lstrip('/'), v[:60]) for k, v in old.items() if v and k not in ('/CreationDate', '/ModDate')]
    return dst, (['стерто/замінено — ' + c for c in changes] or ['метаданих не було']) + (['автор: «%s»' % author] if author else [])


def clean(src, author='', org=''):
    e = os.path.splitext(src)[1].lower()
    if e in OOXML: return clean_ooxml(src, author, org)
    if e == '.pdf': return clean_pdf(src, author)
    raise ValueError('підтримуються DOCX, XLSX, PPTX і PDF')
