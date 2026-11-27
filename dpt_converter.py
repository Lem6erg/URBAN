"""URBAN (раніше «Конвертер ДПТ»): Archicad DXF → Digitals (МСК/СК-63/УСК-2000) і DMF → DXF R12.
Запуск: G:\\URBAN\\Документація\\URBAN.bat (pythonw). Створено 27.11.2026 (CLAUDE); код — G:\\URBAN\\URBAN [app].
Перерахунок між системами — лише за ключами з crs_keys.json (див. crs.py); без ключів доступно «як у топо»."""
import os, sys, threading, subprocess, queue, re, traceback, json, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crs
import ui_icons
import updater
import pdf_raster
import site_map
import geo
import kml_dxf
import coord_calc
import raster_geo
import file_clean
import pz_check
import dzk_xml
import cz_routes
from version import VERSION
from dxf_digitals_drop import find_dmf

SAME = 'Як у топо (без перерахунку)'
SK63 = 'СК-63 (немає ключа)'


def sys_choices():
    return crs.systems() + ([SK63] if not any('СК-63' in n for n in crs.systems()) else [])


AUTO = 'Автоматично (за DMF)'
AUTO7 = 'Автоматично (за координатами)'
IMG_EXT = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.gif')


def dmf_system(path):
    try:
        import dmf2dxf as D
        hdr, raw = D.load(path); cs = D.coord_system(raw)
        if cs.startswith('S') and '63' in cs: return 'СК-63'
        if 'USK' in cs or 'UCK' in cs: return 'УСК-2000'
    except Exception:
        pass
    return ''


def detect_system(path):
    """Система координат DMF: за медіанною точкою (яка проєкція кладе її в Україну і в свою зону),
    підказка — назва файлу (СК-63 / УСК / МСК). Повертає (назва або None, пояснення)."""
    import dmf2dxf as D
    base = os.path.basename(path).upper().replace(' ', '')
    if re.search(r'СК-?63|SK-?63|CK-?63', base):
        return next((n for n in sys_choices() if 'СК-63' in n), SK63), 'за назвою файлу'
    hdr, raw = D.load(path); start, objs = D.find_objects(raw)
    E = sorted(ea for o in objs for n, ea in o['verts'] if abs(n - D.BREAK) > 1)
    N = sorted(n for o in objs for n, ea in o['verts'] if abs(n - D.BREAK) > 1)
    if not E: return None, 'у DMF немає координат'
    e, n = E[len(E) // 2], N[len(N) // 2]
    g = crs.guess(e, n)
    hint = 'УСК' if 'УСК' in base or 'USK' in base else 'МСК' if 'МСК' in base or 'MSK' in base else ''
    if hint and any(hint in x[0] for x in g): g = [x for x in g if hint in x[0]]
    if not g:
        return None, 'координати E %.0f, N %.0f не підходять жодній відомій проєкції (можливо, СК-63 чи умовна)' % (e, n)
    why = 'за координатами (E %.0f, N %.0f → %.2f° пн. ш., %.2f° сх. д.)' % (e, n, g[0][2], g[0][3])
    if len(g) > 1: why += '; можливі також: ' + ', '.join(x[0] for x in g[1:])
    return g[0][0], why


def suffix_name(path, tag, ext='.dxf'):
    return os.path.splitext(path)[0] + ' (%s)%s' % (tag, ext)


# ---------- оформлення: світла / темна тема в стилі iOS (системні кольори Apple HIG) ----------
PAL = {
    'light': dict(bg='#F2F2F7', card='#FFFFFF', field='#F2F2F7', text='#000000', text2='#6E6E73', sep='#D1D1D6',
                  accent='#007AFF', accent_hi='#0062CC', fill='#E5F0FF', fill_hi='#CFE3FF', seg='#E3E3E8', segon='#FFFFFF',
                  track='#E5E5EA', hover='#F2F2F7', dis='#E5E5EA', distext='#AEAEB2', green='#248A3D', red='#D70015', orange='#C93400', sel='#CCE4FF'),
    'dark': dict(bg='#000000', card='#1C1C1E', field='#2C2C2E', text='#FFFFFF', text2='#98989D', sep='#38383A',
                 accent='#0A84FF', accent_hi='#409CFF', fill='#132A47', fill_hi='#1B3A61', seg='#1C1C1E', segon='#636366',
                 track='#3A3A3C', hover='#2C2C2E', dis='#2C2C2E', distext='#636366', green='#30D158', red='#FF453A', orange='#FF9F0A', sel='#0A3D73'),
}
CFG = os.path.join(os.environ.get('APPDATA') or HERE, 'URBAN', 'settings.json')
CFG_OLD = os.path.join(os.environ.get('APPDATA') or HERE, 'Конвертер ДПТ', 'settings.json')  # до перейменування


def load_settings():
    for p in (CFG, CFG_OLD):
        try:
            with open(p, encoding='utf-8') as f: return json.load(f)
        except Exception:
            pass
    return {}


def save_settings(d):
    try:
        os.makedirs(os.path.dirname(CFG), exist_ok=True)
        with open(CFG, 'w', encoding='utf-8') as f: json.dump(d, f)
    except Exception:
        pass


def sys_dark():
    """Тема Windows для програм (AppsUseLightTheme = 0 → темна)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as k:
            return winreg.QueryValueEx(k, 'AppsUseLightTheme')[0] == 0
    except Exception:
        return False


TR_NAME = '07 Для Digitals (МСК).Xml'


def translator_path():
    """Файл транслятора Archicad: у встановленій програмі — <папка програми>\\Транслятор Archicad; у робочій — G:\\URBAN\\Документація."""
    c = []
    if getattr(sys, 'frozen', False): c.append(os.path.dirname(sys.executable))
    c.append(installed_dir())  # встановлений URBAN — і для робочої версії
    c.append(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'URBAN'))
    c = [os.path.join(d, 'Транслятор Archicad', TR_NAME) for d in c if d]
    c += [os.path.join(HERE, 'Транслятор Archicad', TR_NAME), os.path.normpath(os.path.join(HERE, '..', 'Документація', TR_NAME))]  # код у G:\URBAN\URBAN [app] (з 27.11.2026)
    return next((p for p in c if os.path.exists(p)), c[0])


def installed_dir():
    """Папка встановленого URBAN з реєстру (запис інсталятора Inno Setup, AppId URBAN)."""
    try:
        import winreg
        k = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8B7F628D-2AB4-45D8-A073-6DA1BAAF9497}_is1'
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, k) as h: return winreg.QueryValueEx(h, 'InstallLocation')[0]
            except OSError:
                pass
    except Exception:
        pass
    return ''


def py_cmd(script):
    """Команда запуску службового скрипта: у встановленій програмі (exe) — той самий exe з ключем --script."""
    if getattr(sys, 'frozen', False): return [sys.executable, '--script', script]
    return [sys.executable, '-I', '-u', script]


ASSETS = os.path.join(HERE, 'assets')  # лого URBAN: urban.ico, urban_icon.png, urban_mark.png (маска знака)


def dpi_aware():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('URBAN.DPT')  # своя іконка на панелі задач
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class App(tk.Tk):
    # меню-рейка (як в ATLAS): групи, іконки, активний пункт — смуга акценту
    RAIL = [('ГОЛОВНА', [('p0', 'activity', 'Процеси')]),
            ('КОНВЕРТАЦІЯ', [('p1', 'layers', 'Archicad → Digitals'), ('p2', 'convert', 'DMF → DXF'), ('p8', 'globe', 'KML ↔ DXF')]),
            ('КООРДИНАТИ', [('p3', 'target', 'Ключ за пунктами'), ('p9', 'calc', 'Калькулятор'), ('p7', 'pin', 'Локація'),
                            ('p12', 'parcel', 'Кадастр (XML ДЗК)')]),
            ('ФАЙЛИ', [('p6', 'image', 'PDF → JPEG / TIFF'), ('p10', 'grid', 'Прив\'язка растру'), ('p11', 'eraser', 'Очищення файлів'),
                       ('p13', 'check', 'Перевірка ПЗ')]),
            ('ARCHICAD', [('p4', 'plug', 'Транслятор')]),
            ('ПРОГРАМА', [('p5', 'refresh', 'Оновлення')])]
    TITLES = {'p0': ('Процеси', 'Усі запущені й завершені процеси цього сеансу, стан програми'),
              'p1': ('Archicad DXF → Digitals', 'DXF з Archicad → система топо, кольори шарів, DXF R12 для Digitals'),
              'p2': ('DMF → DXF', 'Топо Digitals → DXF R12 для Archicad чи CAD'),
              'p3': ('Ключ за пунктами', 'Перехід між системами координат за спільними пунктами (СК-63 тощо)'),
              'p4': ('Транслятор Archicad', 'Підключення «07 Для Digitals (МСК)» в Archicad і експорт DXF'),
              'p5': ('Оновлення', 'Версія програми, що нового, оновлення з GitHub'),
              'p6': ('PDF → JPEG / TIFF', 'Сторінки PDF у растр: три рівні якості, TIFF без втрат (LZW / Ч/Б G4)'),
              'p8': ('KML ↔ DXF', 'Google Earth (KML/KMZ) → DXF R12 у системі координат і назад DXF → KML'),
              'p9': ('Калькулятор координат', 'Стовпчик точок з однієї системи в іншу: МСК, УСК-2000, WGS-84, СК-63'),
              'p10': ('Прив\'язка растру', 'Скан чи викопіювання за точками → растр північчю вгору й розміри для Archicad'),
              'p11': ('Очищення файлів', 'Метадані DOCX / XLSX / PPTX / PDF перед відправкою: автор, організація, назва, шаблон'),
              'p12': ('Кадастр (XML ДЗК)', 'Обмінний файл ДЗК → DXF у системі координат; ділянка за к.н. на карті'),
              'p13': ('Перевірка ПЗ', 'DOCX перед видачею: шифри норм, залишки чатів, виділення, коментарі, метадані, нумерація'),
              'p7': ('Локація', 'Зйомка DXF/DWG → система координат → місце на Google Maps')}

    def __init__(self):
        dpi_aware()
        super().__init__()
        s = self._s = self.winfo_fpixels('1i') / 96.0
        self.title('URBAN')
        try: self.iconbitmap(default=os.path.join(ASSETS, 'urban.ico'))
        except tk.TclError: pass
        self.geometry('%dx%d' % (1120 * s, 800 * s)); self.minsize(int(940 * s), int(640 * s))
        self.q = queue.Queue(); self.st = ttk.Style(self); self.st.theme_use('clam')
        self.mode = load_settings().get('theme', 'auto'); self._sysdark = sys_dark()
        self._regs = []; self._icon_w = []; self._img = []; self.cur = None
        # верхня панель
        top = tk.Frame(self, height=int(58 * s)); top.pack(fill='x'); top.pack_propagate(False); self._reg(top, 'card')
        self.logo = tk.Label(top); self.logo.pack(side='left', padx=(18, 10)); self._reg(self.logo, 'card')
        t = tk.Label(top, text='URBAN', font=('Segoe UI Semibold', 16)); t.pack(side='left'); self._reg(t, 'card', 'text')
        t = tk.Label(top, text='Archicad  ·  Digitals', font=('Segoe UI', 10))
        t.pack(side='left', padx=(14, 0), pady=(3, 0)); self._reg(t, 'card', 'text2')
        sg = ttk.Frame(top, style='Seg.TFrame', padding=2); sg.pack(side='right', padx=18)
        self.segb = {}
        for k, txt, ic in (('auto', 'Авто', 'auto'), ('light', 'Світла', 'sun'), ('dark', 'Темна', 'moon')):
            # лише значки (вимога користувача 27.11.2026); назва теми — у підказці
            b = ttk.Button(sg, text='', style='Seg.TButton', takefocus=False, compound='image', command=lambda k=k: self.set_mode(k))
            self._tip(b, txt + ' тема' if k != 'auto' else 'Тема як у Windows')
            b.pack(side='left', padx=1); self.segb[k] = b; self._icon_w.append((b, ic, 'seg:' + k, 16))
        line = tk.Frame(self, height=1); line.pack(fill='x'); self._reg(line, 'sep')
        body = tk.Frame(self); body.pack(fill='both', expand=True); self._reg(body, 'bg')
        # рейка
        rail = self.rail = tk.Frame(body, width=int(224 * s)); rail.pack(side='left', fill='y'); rail.pack_propagate(False); self._reg(rail, 'card')
        line = tk.Frame(body, width=1); line.pack(side='left', fill='y'); self._reg(line, 'sep')
        self.items = {}
        for gi, (g, items) in enumerate(self.RAIL):
            if gi:
                sp = tk.Frame(rail, height=1); sp.pack(fill='x', padx=16, pady=(6, 1)); self._reg(sp, 'sep')
            h = tk.Label(rail, text=g, font=('Segoe UI Semibold', 8), anchor='w'); h.pack(fill='x', padx=20, pady=(10 if not gi else 4, 2))
            self._reg(h, 'card', 'text2')
            for key, ic, txt in items: self._rail_item(key, ic, txt)
        ver = self.verlab = tk.Label(rail, text='URBAN ' + VERSION, font=('Segoe UI', 8), anchor='w', cursor='hand2')
        ver.pack(side='bottom', fill='x', padx=20, pady=12); ver.bind('<Button-1>', lambda e: self.show('p5'))
        self._reg(ver, 'card', 'text2')
        # шкала оновлення — під підписом версії, видна лише під час завантаження (загальна шкала — для конвертацій)
        self.upb = ttk.Progressbar(rail, maximum=100)
        self.upd = None  # знайдене оновлення {version, notes, url, sha_url}
        # вміст
        main = tk.Frame(body); main.pack(side='left', fill='both', expand=True); self._reg(main, 'bg')
        hd = tk.Frame(main); hd.pack(fill='x', padx=26, pady=(18, 10)); self._reg(hd, 'bg')
        self.ph = tk.Label(hd, font=('Segoe UI Semibold', 18), anchor='w'); self.ph.pack(anchor='w'); self._reg(self.ph, 'bg', 'text')
        self.phs = tk.Label(hd, font=('Segoe UI', 10), anchor='w'); self.phs.pack(anchor='w'); self._reg(self.phs, 'bg', 'text2')
        box = tk.Frame(main); box.pack(fill='x', padx=26); self._reg(box, 'bg')
        self.pages = {}
        for k in ('p0', 'p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8', 'p9', 'p10', 'p11', 'p12', 'p13'):
            self.pages[k] = tk.Frame(box); self._reg(self.pages[k], 'bg')
        self._tl = threading.local(); self._jobs = {}; self._jn = 0; self._rows = {}
        self._tab0(); self._tab1(); self._tab2(); self._tab3(); self._tab4(); self._tab5(); self._tab6(); self._tab7()
        self._tab8(); self._tab9(); self._tab10(); self._tab11(); self._tab12(); self._tab13()
        self._dnd_setup()
        # шкали процесів відкритої сторінки: рядок «назва · шкала · %» на кожен її процес (вимога користувача 27.11.2026)
        self.pbox = tk.Frame(main); self.pbox.pack(fill='x', padx=26, pady=(4, 8)); self._reg(self.pbox, 'bg')
        lf = self._panel(main, 'Журнал', None, dict(fill='both', expand=True, padx=26, pady=(0, 22)), pad=(4, 0, 4, 4))
        self.log = tk.Text(lf, height=7, wrap='word', state='disabled', font=('Consolas', 10))
        self.log.pack(fill='both', expand=True)
        self.show('p0'); self.apply_theme()
        keys = crs.systems()
        self.say('Системи: ' + (', '.join(keys) if keys else 'немає (crs_keys.json)') + '. МСК-46 ↔ УСК-2000 — точно (одна основа, EPSG). СК-63 — лише з офіційним ключем.')
        if not os.path.exists(self.trp): self.say('УВАГА: файл транслятора не знайдено: %s' % self.trp)
        self.after(100, self._pump); self.after(3000, self._watch); self.after(2500, self._auto_update)

    # ---------- каркас: реєстр кольорів, панелі, рейка ----------
    def _tip(self, w, text):
        """Підказка під віджетом при наведенні."""
        st = {}
        def show(e):
            t = st['t'] = tk.Toplevel(self); t.wm_overrideredirect(True)
            P = getattr(self, 'P', None) or {}
            tk.Label(t, text=text, font=('Segoe UI', 9), bg=P.get('card', '#FFFFFF'), fg=P.get('text', '#000000'),
                     bd=1, relief='solid', padx=6, pady=2).pack()
            t.wm_geometry('+%d+%d' % (w.winfo_rootx(), w.winfo_rooty() + w.winfo_height() + 4))
        def hide(e):
            if st.get('t'): st.pop('t').destroy()
        w.bind('<Enter>', show, add='+'); w.bind('<Leave>', hide, add='+'); w.bind('<ButtonPress>', hide, add='+')

    def _reg(self, w, bg, fg=None):
        self._regs.append((w, bg, fg))
        if getattr(self, 'P', None):  # віджет, створений після теми (рядки процесів)
            try:
                w.configure(bg=self.P[bg])
                if fg: w.configure(fg=self.P[fg])
            except tk.TclError: pass

    def _panel(self, parent, title, icon, pack=None, pad=(16, 0, 16, 14)):
        """Панель-група: рамка 1 px, заголовок КАПІТЕЛЛЮ з іконкою; повертає ttk.Frame для вмісту."""
        o = tk.Frame(parent); o.pack(**(pack or dict(fill='x', pady=(0, 12)))); self._reg(o, 'sep')
        inner = tk.Frame(o); inner.pack(fill='both', expand=True, padx=1, pady=1); self._reg(inner, 'card')
        h = tk.Frame(inner); h.pack(fill='x', padx=pad[0] if pad[0] > 4 else 12, pady=(10, 6)); self._reg(h, 'card')
        if icon:
            il = tk.Label(h); il.pack(side='left', padx=(0, 8)); self._reg(il, 'card'); self._icon_w.append((il, icon, 'accent', 16))
        t = tk.Label(h, text=title.upper(), font=('Segoe UI Semibold', 9)); t.pack(side='left'); self._reg(t, 'card', 'text2')
        c = ttk.Frame(inner, padding=pad); c.pack(fill='both', expand=True)
        return c

    def _btn(self, parent, text, icon, cmd, primary=False, **kw):
        b = ttk.Button(parent, text=' ' + text, style='Accent.TButton' if primary else 'TButton', compound='left', command=cmd, **kw)
        self._icon_w.append((b, icon, 'white' if primary else 'accent', 18)); return b

    def _rail_item(self, key, ic, txt):
        row = tk.Frame(self.rail, height=int(30 * self._s), cursor='hand2'); row.pack(fill='x', padx=10, pady=1); row.pack_propagate(False)
        stripe = tk.Frame(row, width=3); stripe.pack(side='left', fill='y')
        lab = tk.Label(row, text='   ' + txt, compound='left', anchor='w', font=('Segoe UI', 10), padx=10, cursor='hand2')
        lab.pack(side='left', fill='both', expand=True)
        it = self.items[key] = dict(row=row, stripe=stripe, lab=lab, ic=ic, hover=False)
        for w in (row, stripe, lab):
            w.bind('<Button-1>', lambda e, k=key: self.show(k))
            w.bind('<Enter>', lambda e, i=it: (i.update(hover=True), self._paint_rail()))
            w.bind('<Leave>', lambda e, i=it: (i.update(hover=False), self._paint_rail()))

    def show(self, key):
        for k, p in self.pages.items():
            if k == key: p.pack(fill='x')
            else: p.pack_forget()
        self.cur = key; self.ph.configure(text=self.TITLES[key][0]); self.phs.configure(text=self.TITLES[key][1])
        if hasattr(self, 'P'): self._paint_rail()
        if hasattr(self, 'pbox'): self._bars()

    def _icon(self, name, size, color):
        im = ui_icons.photo(name, int(size * self._s), color); self._img.append(im); return im

    def _paint_rail(self):
        P = self.P
        for k, it in self.items.items():
            on = k == self.cur
            bg = P['fill'] if on else P['hover'] if it['hover'] else P['card']
            fg = P['text'] if on else P['text2']
            it['row'].configure(bg=bg); it['stripe'].configure(bg=P['accent'] if on else bg)
            key = (it['ic'], on, P['accent'], P['text2'])
            if it.get('key') != key:
                it['img'] = ui_icons.photo(it['ic'], int(20 * self._s), P['accent'] if on else P['text2']); it['key'] = key
            it['lab'].configure(bg=bg, fg=fg, image=it['img'], font=('Segoe UI Semibold', 10) if on else ('Segoe UI', 10))

    # ---------- тема ----------
    def is_dark(self):
        return self.mode == 'dark' or (self.mode == 'auto' and self._sysdark)

    def set_mode(self, m):
        self.mode = m; d = load_settings(); d['theme'] = m; save_settings(d); self.apply_theme()

    def _watch(self):  # «Авто»: стежити за темою Windows
        d = sys_dark()
        if d != self._sysdark:
            self._sysdark = d
            if self.mode == 'auto': self.apply_theme()
        self.after(3000, self._watch)

    def _titlebar(self, dark):
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()); v = ctypes.c_int(1 if dark else 0)
            for a in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 20H1+ / старіші збірки)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, a, ctypes.byref(v), 4) == 0: break
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x27)  # перемалювати рамку
        except Exception:
            pass

    def apply_theme(self):
        dark = self.is_dark(); P = self.P = PAL['dark' if dark else 'light']; st = self.st
        F, FB = ('Segoe UI', 10), ('Segoe UI Semibold', 10)
        self.configure(bg=P['bg'])
        st.configure('.', background=P['card'], foreground=P['text'], font=F, bordercolor=P['sep'], lightcolor=P['card'],
                     darkcolor=P['card'], troughcolor=P['track'], focuscolor=P['card'], selectbackground=P['accent'],
                     selectforeground='#FFFFFF', fieldbackground=P['field'], insertcolor=P['text'], arrowcolor=P['accent'])
        st.map('.', background=[('disabled', P['card'])], foreground=[('disabled', P['distext'])])
        st.configure('TFrame', background=P['card'])
        st.configure('Seg.TFrame', background=P['card'])
        st.configure('TLabel', background=P['card'], foreground=P['text'])
        st.configure('Hint.TLabel', background=P['card'], foreground=P['text2'])
        # таблиці (Процеси, точки прив'язки): тло поля, як у списків, а не біле
        st.configure('Treeview', background=P['field'], fieldbackground=P['field'], foreground=P['text'],
                     bordercolor=P['sep'], lightcolor=P['field'], darkcolor=P['field'], rowheight=int(24 * self._s))
        st.map('Treeview', background=[('selected', P['accent'])], foreground=[('selected', '#FFFFFF')])
        st.configure('Treeview.Heading', background=P['seg'], foreground=P['text2'], bordercolor=P['sep'], relief='flat')
        st.map('Treeview.Heading', background=[('active', P['seg'])])
        st.configure('Num.TLabel', background=P['fill'], foreground=P['accent'], font=FB)
        st.configure('Link.TButton', background=P['card'], foreground=P['accent'], bordercolor=P['card'], lightcolor=P['card'],
                     darkcolor=P['card'], focuscolor=P['card'], relief='flat', borderwidth=0, padding=(0, 0), font=F)
        lk = [('active', P['card']), ('pressed', P['card'])]
        st.map('Link.TButton', background=lk, bordercolor=lk, lightcolor=lk, darkcolor=lk, foreground=[('active', P['accent_hi'])])

        def btn(name, bg, bgh, fg, font=FB, pad=(14, 6)):
            st.configure(name, background=bg, foreground=fg, bordercolor=bg, lightcolor=bg, darkcolor=bg, focuscolor=bg,
                         relief='flat', borderwidth=0, padding=pad, font=font)
            sm = [('disabled', P['dis']), ('pressed', bgh), ('active', bgh)]
            st.map(name, background=sm, bordercolor=sm, lightcolor=sm, darkcolor=sm, focuscolor=sm,
                   foreground=[('disabled', P['distext'])], relief=[('pressed', 'flat')])
        btn('TButton', P['fill'], P['fill_hi'], P['accent'])
        btn('Accent.TButton', P['accent'], P['accent_hi'], '#FFFFFF', pad=(18, 7))
        # перемикач теми — лише значки без тла (вимога користувача 27.11.2026); активна — значок кольору акценту
        btn('Seg.TButton', P['card'], P['card'], P['text2'], F, (7, 3))
        btn('SegOn.TButton', P['card'], P['card'], P['text'], FB, (7, 3))

        for n in ('TEntry', 'TCombobox'):
            st.configure(n, fieldbackground=P['field'], background=P['field'], foreground=P['text'], bordercolor=P['field'],
                         lightcolor=P['field'], darkcolor=P['field'], insertcolor=P['text'], arrowcolor=P['accent'],
                         padding=(8, 5), arrowsize=14)
            st.map(n, fieldbackground=[('readonly', P['field']), ('disabled', P['card'])],
                   background=[('active', P['field']), ('pressed', P['field']), ('readonly', P['field'])],
                   bordercolor=[('focus', P['accent'])], lightcolor=[('focus', P['field'])], darkcolor=[('focus', P['field'])],
                   selectbackground=[('readonly', P['field']), ('!readonly', P['accent'])],
                   selectforeground=[('readonly', P['text']), ('!readonly', '#FFFFFF')], foreground=[('readonly', P['text'])])
        for n in ('TCheckbutton', 'TRadiobutton'):
            st.configure(n, background=P['card'], foreground=P['text'], indicatorbackground=P['field'],
                         indicatorforeground='#FFFFFF', upperbordercolor=P['sep'], lowerbordercolor=P['sep'],
                         indicatormargin=(0, 0, 8, 0), focuscolor=P['card'])
            st.map(n, background=[('active', P['card'])],
                   indicatorbackground=[('selected', P['accent']), ('pressed', P['fill_hi'])],
                   upperbordercolor=[('selected', P['accent'])], lowerbordercolor=[('selected', P['accent'])])
        st.configure('Horizontal.TProgressbar', troughcolor=P['track'], background=P['accent'], bordercolor=P['track'],
                     lightcolor=P['accent'], darkcolor=P['accent'], thickness=6)
        # tk-віджети каркаса
        for w, b, f in self._regs:
            try:
                w.configure(bg=P[b])
                if f: w.configure(fg=P[f])
            except tk.TclError:
                pass
        for tx in (self.in9, self.out9):
            tx.configure(bg=P['field'], fg=P['text'], insertbackground=P['text'], selectbackground=P['sel'],
                         selectforeground=P['text'], highlightthickness=0, bd=0, relief='flat', padx=8, pady=6)
        self.cv10.configure(bg=P['field'], highlightthickness=0, bd=0)
        for lb in (self.lb1, self.lb6, self.lb11, self.lb13):  # усі списки файлів — однаково з темою
            lb.configure(bg=P['field'], fg=P['text'], selectbackground=P['accent'], selectforeground='#FFFFFF',
                         highlightthickness=0, bd=0, relief='flat', activestyle='none', font=F)
        self.log.configure(bg=P['card'], fg=P['text'], insertbackground=P['text'], selectbackground=P['sel'],
                           selectforeground=P['text'], highlightthickness=0, bd=0, relief='flat', padx=12, pady=6)
        self.notes.configure(bg=P['card'], fg=P['text'], insertbackground=P['text'], selectbackground=P['sel'],
                             selectforeground=P['text'], highlightthickness=0, bd=0, relief='flat', padx=4, pady=2)
        for t, c in (('ok', P['green']), ('err', P['red']), ('warn', P['orange']), ('head', P['accent'])):
            self.log.tag_configure(t, foreground=c, font=('Consolas', 10, 'bold'))
        for o, v in (('background', P['field']), ('foreground', P['text']), ('selectBackground', P['accent']),
                     ('selectForeground', '#FFFFFF'), ('font', 'Segoe\\ UI 10')):
            self.option_add('*TCombobox*Listbox.' + o, v)
        for cb in (self.src1, self.dst1, self.src2, self.dst2, self.kf, self.kt):
            try:
                pd = self.tk.call('ttk::combobox::PopdownWindow', cb)
                self.tk.call('%s.f.l' % pd, 'configure', '-background', P['field'], '-foreground', P['text'],
                             '-selectbackground', P['accent'], '-selectforeground', '#FFFFFF', '-borderwidth', 0)
            except tk.TclError:
                pass
        for k, b in self.segb.items(): b.configure(style='SegOn.TButton' if k == self.mode else 'Seg.TButton')
        # іконки кольором теми
        self._img = []
        for w, ic, role, size in self._icon_w:
            if role.startswith('seg:'): col = P['accent'] if role[4:] == self.mode else P['text2']
            else: col = '#FFFFFF' if role == 'white' else P['accent']
            w.configure(image=self._icon(ic, size, col))
        self._paint_rail()
        self._logo(P['text'])
        self._titlebar(dark)

    def _logo(self, color):
        """Знак URBAN кольором тексту теми (маска з urban_mark.png)."""
        try:
            from PIL import Image, ImageTk
            n = int(34 * self._s); m = Image.open(os.path.join(ASSETS, 'urban_mark.png')).convert('L').resize((n, n), Image.LANCZOS)
            im = Image.new('RGBA', (n, n), color); im.putalpha(m)
            self._logo_img = ImageTk.PhotoImage(im); self.logo.configure(image=self._logo_img)
        except Exception:
            self.logo.pack_forget()

    # ---------- сторінка 1: Archicad DXF → Digitals ----------
    def _tab1(self):
        pg = self.pages['p1']
        f = self._panel(pg, 'Файли з Archicad', 'layers')
        hl = ttk.Frame(f); hl.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        ttk.Label(hl, text='DXF з плану поверху, транслятор «07 Для Digitals (МСК)».', style='Hint.TLabel').pack(side='left')
        lk = ttk.Button(hl, text=' Як підключити транслятор?', style='Link.TButton', takefocus=False, compound='left',
                        command=lambda: self.show('p4'))
        lk.pack(side='left', padx=(10, 0)); self._icon_w.append((lk, 'help', 'accent', 15))
        self.lb1 = tk.Listbox(f, height=4, selectmode='extended'); self.lb1.grid(row=1, column=0, sticky='nsew')
        b = ttk.Frame(f); b.grid(row=1, column=1, sticky='n', padx=(8, 0))
        self._btn(b, 'Додати…', 'plus', self.add1).pack(fill='x')
        self._btn(b, 'Прибрати', 'minus', lambda: [self.lb1.delete(i) for i in reversed(self.lb1.curselection())]).pack(fill='x', pady=(4, 0))
        f.columnconfigure(0, weight=1)
        f = self._panel(pg, 'Топо Digitals', 'folder')
        self.dmf1 = tk.StringVar(value='(знайти автоматично у ВД\\Топо)')
        ttk.Entry(f, textvariable=self.dmf1).grid(row=0, column=0, sticky='ew')
        self._btn(f, 'Вибрати…', 'folder', lambda: self._pick(self.dmf1, [('DMF', '*.dmf')])).grid(row=0, column=1, padx=(8, 0))
        f.columnconfigure(0, weight=1)
        f = self._panel(pg, 'Системи координат', 'target')
        ttk.Label(f, text='Система топо').grid(row=0, column=0, sticky='w')
        ttk.Label(f, text='Вихідна система').grid(row=0, column=1, sticky='w', padx=(16, 0))
        self.src1 = ttk.Combobox(f, values=[AUTO] + sys_choices(), width=30, state='readonly'); self.src1.grid(row=1, column=0, sticky='w')
        self.src1.set(AUTO)
        self.dst1 = ttk.Combobox(f, values=[SAME] + sys_choices(), width=32, state='readonly'); self.dst1.set(SAME)
        self.dst1.grid(row=1, column=1, sticky='w', padx=(16, 0))
        a = tk.Frame(pg); a.pack(fill='x', pady=(0, 6)); self._reg(a, 'bg')
        self._btn(a, 'Перетворити', 'play', self.run1, primary=True).pack(side='left')

    def add1(self):
        new = [p for p in filedialog.askopenfilenames(title='DXF з Archicad', filetypes=[('DXF', '*.dxf')])
               if p not in self.lb1.get(0, 'end')]
        for p in new: self.lb1.insert('end', p)
        if new and not self.dmf1.get().lower().endswith('.dmf'):
            c = find_dmf(new[0])
            if len(c) == 1: self._detect_show(c[0])

    # ---------- сторінка 2: DMF → DXF ----------
    def _tab2(self):
        pg = self.pages['p2']
        f = self._panel(pg, 'Топо Digitals', 'folder')
        self.dmf2 = tk.StringVar(); ttk.Entry(f, textvariable=self.dmf2).grid(row=0, column=0, sticky='ew')
        self._btn(f, 'Вибрати…', 'folder', self.pick2).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(f, style='Hint.TLabel', text='Результат: DXF R12 (cp1251, метри) + семантика CSV + пікети TXT поруч із DMF. '
                  'DWG — відкрити DXF у CAD і зберегти.').grid(row=1, column=0, columnspan=2, sticky='w', pady=(8, 0))
        f.columnconfigure(0, weight=1)
        f = self._panel(pg, 'Системи координат', 'target')
        ttk.Label(f, text='Система DMF').grid(row=0, column=0, sticky='w')
        ttk.Label(f, text='Вихідна система').grid(row=0, column=1, sticky='w', padx=(16, 0))
        self.src2 = ttk.Combobox(f, values=[AUTO] + sys_choices(), width=30, state='readonly'); self.src2.grid(row=1, column=0, sticky='w')
        self.src2.set(AUTO)
        self.dst2 = ttk.Combobox(f, values=[SAME.replace('топо', 'DMF')] + sys_choices(), width=32, state='readonly')
        self.dst2.current(0); self.dst2.grid(row=1, column=1, sticky='w', padx=(16, 0))
        f = self._panel(pg, 'Зсув для Archicad', 'convert')
        self.sh = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text='Зсув до локального нуля:', variable=self.sh).grid(row=0, column=0, sticky='w')
        self.she = tk.StringVar(); self.shn = tk.StringVar()
        ttk.Label(f, text='E').grid(row=0, column=1, padx=(12, 4)); ttk.Entry(f, textvariable=self.she, width=14).grid(row=0, column=2)
        ttk.Label(f, text='N').grid(row=0, column=3, padx=(12, 4)); ttk.Entry(f, textvariable=self.shn, width=14).grid(row=0, column=4)
        a = tk.Frame(pg); a.pack(fill='x', pady=(0, 6)); self._reg(a, 'bg')
        self._btn(a, 'Конвертувати', 'play', self.run2, primary=True).pack(side='left')

    def pick2(self):
        p = filedialog.askopenfilename(title='DMF', filetypes=[('DMF', '*.dmf')])
        if p:
            self.dmf2.set(p); self._detect_show(p)

    def _pick(self, var, ft):
        p = filedialog.askopenfilename(filetypes=ft)
        if p:
            var.set(p)
            if var is self.dmf1: self._detect_show(p)

    def _detect_show(self, dmf):
        """Одразу показати в журналі, яку систему визначено (у фоні — DMF може бути великим)."""
        def job():
            try: s, why = detect_system(dmf)
            except Exception as e: s, why = None, str(e)
            self.q.put('Система топо «%s»: %s — %s' % (os.path.basename(dmf), s or 'НЕ ВИЗНАЧЕНО', why))
        self._bg(job)

    def _src(self, choice, dmf):
        """Вибір зі списку або, для «Автоматично», визначена за DMF система."""
        if choice != AUTO: return choice
        s, why = detect_system(dmf)
        self.q.put('   система топо: %s — %s' % (s or 'НЕ ВИЗНАЧЕНО', why))
        return s or ''

    # ---------- сторінка 4: транслятор Archicad ----------
    def _tab4(self):
        pg = self.pages['p4']; self.trp = translator_path()
        f = self._panel(pg, 'Підключення в Archicad (один раз)', 'plug')
        steps = [
            'Меню «Файл → Взаимодействие → DXF-DWG → Параметры Трансляции DXF-DWG…»\n'
            '(англ. File → Interoperability → DXF-DWG → DXF-DWG Translation Setup…).',
            'Натисніть «Найти…» (Browse…) і виберіть файл транслятора, указаний нижче.',
            'Транслятор з’явиться в списку — «Готово». Файл не переносьте й не видаляйте: Archicad бере його з цієї папки.',
            'Експорт — з ПЛАНУ ПОВЕРХУ (не з макета): «Файл → Сохранить как…» → тип «DXF» → транслятор «07 Для Digitals (МСК)».',
            'Отриманий DXF додайте в «Archicad → Digitals» — програма прив’яже його до топо й запише R12 для Digitals.']
        for i, s in enumerate(steps):
            ttk.Label(f, text='%d' % (i + 1), style='Num.TLabel', width=2, anchor='center').grid(row=i, column=0, sticky='nw', pady=3)
            ttk.Label(f, text=s, justify='left').grid(row=i, column=1, sticky='w', padx=(10, 0), pady=3)
        f = self._panel(pg, 'Файл транслятора', 'folder')
        e = ttk.Entry(f); e.insert(0, self.trp); e.configure(state='readonly'); e.grid(row=0, column=0, sticky='ew')
        self._btn(f, 'Показати в папці', 'folder', self.show_tr, primary=True).grid(row=0, column=1, padx=(8, 0))
        self._btn(f, 'Скопіювати шлях', 'copy', self.copy_tr).grid(row=0, column=2, padx=(8, 0))
        f.columnconfigure(0, weight=1)

    def show_tr(self):
        if os.path.exists(self.trp): subprocess.Popen(['explorer', '/select,', self.trp])
        else: messagebox.showerror('Транслятор', 'Файл не знайдено:\n%s' % self.trp)

    def copy_tr(self):
        self.clipboard_clear(); self.clipboard_append(self.trp); self.say('Шлях до транслятора скопійовано: %s' % self.trp)

    # ---------- сторінка 5: оновлення (GitHub Releases; ТЗ Markdown/urban_autoupdate_spec.md) ----------
    def _tab5(self):
        pg = self.pages['p5']
        f = self._panel(pg, 'Версія', 'refresh')
        ttk.Label(f, text='Встановлено: URBAN %s' % VERSION, font=('Segoe UI Semibold', 11)).grid(row=0, column=0, sticky='w')
        self.upd_st = ttk.Label(f, text='Оновлення ще не перевірялись.', style='Hint.TLabel')
        self.upd_st.grid(row=1, column=0, sticky='w', pady=(2, 0))
        b = ttk.Frame(f); b.grid(row=2, column=0, sticky='w', pady=(10, 0))
        self._btn(b, 'Перевірити оновлення', 'refresh', self.check_update).pack(side='left')
        self.upd_btn = self._btn(b, 'Оновити', 'download', self.install_update, primary=True, state='disabled')
        self.upd_btn.pack(side='left', padx=8)
        self.upd_auto = tk.BooleanVar(value=load_settings().get('update_auto', True))
        ttk.Checkbutton(f, text='Перевіряти оновлення автоматично при запуску (раз на добу)', variable=self.upd_auto,
                        command=self._save_auto).grid(row=3, column=0, sticky='w', pady=(10, 0))
        if not updater.can_install():
            ttk.Label(f, style='Hint.TLabel', text='Робоча версія (Python): нова версія лише показується; '
                      'встановлює оновлення програма, поставлена інсталятором.').grid(row=4, column=0, sticky='w', pady=(6, 0))
        f = self._panel(pg, 'Що нового', 'help')
        self.notes = tk.Text(f, height=9, wrap='word', state='disabled', font=('Segoe UI', 10))
        self.notes.pack(fill='both', expand=True)
        self._set_notes(self._changelog())

    # ---------- сторінка 6: PDF → JPEG / TIFF ----------
    LV = [(k, '%s — %d DPI' % (v[0], v[1])) for k, v in pdf_raster.LEVELS.items()]

    def _tab6(self):
        pg = self.pages['p6']
        f = self._panel(pg, 'Файли PDF', 'image')
        ttk.Label(f, style='Hint.TLabel', text='Додайте PDF кнопкою або перетягніть у вікно.\nРезультат — у папці поруч із PDF: '
                  '«назва (JPEG)» або «назва (TIFF)»; наявні файли не перезаписуються.').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.lb6 = tk.Listbox(f, height=4, selectmode='extended'); self.lb6.grid(row=1, column=0, sticky='nsew')
        b = ttk.Frame(f); b.grid(row=1, column=1, sticky='n', padx=(8, 0))
        self._btn(b, 'Додати…', 'plus', self.add6).pack(fill='x')
        self._btn(b, 'Прибрати', 'minus', lambda: [self.lb6.delete(i) for i in reversed(self.lb6.curselection())]).pack(fill='x', pady=(4, 0))
        f.columnconfigure(0, weight=1)
        f = self._panel(pg, 'Параметри', 'layers')
        ttk.Label(f, text='Формат').grid(row=0, column=0, sticky='w')
        ttk.Label(f, text='Якість').grid(row=0, column=1, sticky='w', padx=(16, 0))
        ttk.Label(f, text='Колір').grid(row=0, column=2, sticky='w', padx=(16, 0))
        ttk.Label(f, text='Сторінки').grid(row=0, column=3, sticky='w', padx=(16, 0))
        self.fmt6 = ttk.Combobox(f, values=['JPEG', 'TIFF'], width=8, state='readonly'); self.fmt6.set('JPEG')
        self.fmt6.grid(row=1, column=0, sticky='w'); self.fmt6.bind('<<ComboboxSelected>>', lambda e: self._colors6())
        self.lvl6 = ttk.Combobox(f, values=[v for _, v in self.LV], width=20, state='readonly'); self.lvl6.current(1)
        self.lvl6.grid(row=1, column=1, sticky='w', padx=(16, 0))
        self.col6 = ttk.Combobox(f, width=18, state='readonly'); self.col6.grid(row=1, column=2, sticky='w', padx=(16, 0))
        self.pg6 = tk.StringVar(value='усі'); ttk.Entry(f, textvariable=self.pg6, width=14).grid(row=1, column=3, sticky='w', padx=(16, 0))
        ttk.Label(f, style='Hint.TLabel', text='Сторінки: «усі» або «1-3,5». Чорно-білий (CCITT G4) — лише для TIFF, найменші файли креслень.'
                  ).grid(row=2, column=0, columnspan=4, sticky='w', pady=(8, 0))
        self._colors6()
        a = tk.Frame(pg); a.pack(fill='x', pady=(0, 6)); self._reg(a, 'bg')
        self._btn(a, 'Перетворити', 'play', self.run6, primary=True).pack(side='left')

    def _colors6(self):
        keys = ['color', 'gray'] + (['bw'] if self.fmt6.get() == 'TIFF' else [])
        vals = [pdf_raster.COLORS[k] for k in keys]; cur = self.col6.get()
        self.col6.configure(values=vals); self.col6.set(cur if cur in vals else vals[0])

    def add6(self, paths=None):
        paths = paths if paths is not None else filedialog.askopenfilenames(title='PDF', filetypes=[('PDF', '*.pdf')])
        for p in paths:
            if p.lower().endswith('.pdf') and p not in self.lb6.get(0, 'end'): self.lb6.insert('end', p)

    def run6(self):
        files = list(self.lb6.get(0, 'end'))
        if not files: messagebox.showinfo('PDF', 'Додайте PDF.'); return
        fmt = self.fmt6.get().lower(); lvl = self.LV[self.lvl6.current()][0]
        col = {v: k for k, v in pdf_raster.COLORS.items()}[self.col6.get()]; rng = self.pg6.get()
        self.say('\n=== PDF → %s, %s, %s' % (fmt.upper(), self.lvl6.get(), self.col6.get())); self.setp(0)
        def job():
            plan = []
            for pdf in files:
                try: plan.append((pdf, pdf_raster.parse_pages(rng, pdf_raster.page_count(pdf))))
                except Exception as e: self.q.put('ПОМИЛКА %s: %s' % (os.path.basename(pdf), e))
            total = sum(len(p) for _, p in plan) or 1; done = [0]; ok = 0
            for pdf, pages in plan:
                self.q.put('%s — сторінок: %d' % (os.path.basename(pdf), len(pages)))
                base = done[0]
                def prog(k, base=base): done[0] = base + k; self.setp(100.0 * done[0] / total)
                try:
                    pdf_raster.convert(pdf, fmt, lvl, col, pages, prog, log=self.q.put); ok += 1
                    self.q.put('   → %s' % pdf_raster.out_dir(pdf, fmt))
                except Exception as e:
                    done[0] = base + len(pages); self.q.put('ПОМИЛКА %s: %s' % (os.path.basename(pdf), e))
            self.setp(100)
            self.q.put('ГОТОВО: %d з %d PDF' % (ok, len(files)) if ok == len(files) else 'УВАГА: перетворено %d з %d PDF' % (ok, len(files)))
        self._bg(job)

    # ---------- сторінка 7: де це на карті ----------
    def _tab7(self):
        pg = self.pages['p7']
        f = self._panel(pg, 'Зйомка', 'folder')
        ttk.Label(f, style='Hint.TLabel', text='DXF або DWG (2004, 2010–2018) — кнопкою або перетягніть файл у вікно.'
                  ).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.mf7 = tk.StringVar(); ttk.Entry(f, textvariable=self.mf7).grid(row=1, column=0, sticky='ew')
        self._btn(f, 'Вибрати…', 'folder', self.pick7).grid(row=1, column=1, padx=(8, 0))
        ttk.Label(f, text='Система координат').grid(row=2, column=0, sticky='w', pady=(10, 2))
        self.sys7 = ttk.Combobox(f, values=[AUTO7] + site_map.systems(), width=40, state='readonly'); self.sys7.set(AUTO7)
        self.sys7.grid(row=3, column=0, sticky='w'); self.sys7.bind('<<ComboboxSelected>>', lambda e: self.locate7())
        f.columnconfigure(0, weight=1)
        f = self._panel(pg, 'Місце', 'pin')
        self.res7 = ttk.Label(f, text='Файл не вибрано.', style='Hint.TLabel', justify='left'); self.res7.grid(row=0, column=0, sticky='w')
        b = ttk.Frame(f); b.grid(row=1, column=0, sticky='w', pady=(10, 0))
        self.go7 = self._btn(b, 'Відкрити в Google Maps', 'globe', self.open7, primary=True, state='disabled'); self.go7.pack(side='left')
        self.cp7 = self._btn(b, 'Копіювати координати', 'copy', self.copy7, state='disabled'); self.cp7.pack(side='left', padx=8)
        ttk.Label(f, style='Hint.TLabel', text='Координати передаються в Google лише після натиснення «Відкрити».\n'
                  'СК-63 — наближено (кілька метрів), для пошуку місця, не для перерахунку.').grid(row=2, column=0, sticky='w', pady=(8, 0))
        self.loc7 = None; self.lay7 = {}
        f = self._panel(pg, 'Межа і ЦЗ', 'target')
        NO = '— немає —'; self.NO7 = NO
        ttk.Label(f, text='Шар межі ДПТ (замкнені контури)').grid(row=0, column=0, sticky='w')
        ttk.Label(f, text='Шар укриттів (точки, блоки, контури)').grid(row=0, column=1, sticky='w', padx=(16, 0))
        self.bl7 = ttk.Combobox(f, values=[NO], width=34, state='readonly'); self.bl7.set(NO); self.bl7.grid(row=1, column=0, sticky='w')
        self.sl7 = ttk.Combobox(f, values=[NO], width=34, state='readonly'); self.sl7.set(NO); self.sl7.grid(row=1, column=1, sticky='w', padx=(16, 0))
        c = ttk.Frame(f); c.grid(row=2, column=0, columnspan=2, sticky='w', pady=(10, 0))
        self.k7 = {k: tk.BooleanVar(value=True) for k in ('shelter_dxf', 'shelter_osm', 'fire', 'hospital')}
        for i, k in enumerate(self.k7):
            ttk.Checkbutton(c, text=cz_routes.KINDS[k][0], variable=self.k7[k]).grid(row=0, column=i, sticky='w', padx=(0, 16))
        b = ttk.Frame(f); b.grid(row=3, column=0, columnspan=2, sticky='w', pady=(10, 0))
        self.kb7 = self._btn(b, 'Межа → KML (Google Earth)', 'globe', self.kml7, state='disabled'); self.kb7.pack(side='left')
        self.cz7 = self._btn(b, 'Відстані ЦЗ', 'play', self.cz7run, primary=True, state='disabled'); self.cz7.pack(side='left', padx=8)
        ttk.Label(f, style='Hint.TLabel', text='Відстані — від центру межі (або зйомки) по дорогах: OSRM, об\'єкти — OpenStreetMap, адреси — Nominatim.\n'
                  'У мережу йдуть лише координати WGS-84. Результат: «… (ЦЗ).txt» і «… (ЦЗ).dxf» у системі зйомки.'
                  ).grid(row=4, column=0, columnspan=2, sticky='w', pady=(8, 0))

    def pick7(self):
        p = filedialog.askopenfilename(title='Зйомка', filetypes=[('DXF / DWG', '*.dxf *.dwg'), ('Усі', '*.*')])
        if p: self.mf7.set(p); self.locate7()

    def locate7(self):
        p = self.mf7.get().strip()
        if not p: return
        if not os.path.exists(p): self.res7.configure(text='Файл не знайдено.'); return
        sysn = self.sys7.get(); sysn = None if sysn == AUTO7 else sysn
        self.loc7 = None; self.go7.configure(state='disabled'); self.cp7.configure(state='disabled')
        self.res7.configure(text='Читаю %s…' % os.path.basename(p))
        def job():
            try: r = site_map.locate(p, sysn); err = None
            except Exception as e: r, err = None, str(e)
            self.q.put(lambda: self._shown7(p, r, err))
        self._bg(job)

    def _shown7(self, p, r, err):
        if err:
            self.res7.configure(text='Не визначено: ' + err); self.say('ПОМИЛКА карта %s: %s' % (os.path.basename(p), err)); return
        self.loc7 = r
        txt = ('%s\nШирота %.6f°, довгота %.6f°   ·   центр E %.2f  N %.2f%s\nОхоплення ≈ %.0f м, вершин %d'
               % (r['system'], r['lat'], r['lon'], r['E'], r['N'], '  (DXF у мм → ×0,001)' if r['k'] != 1 else '', r['span'], r['n']))
        if r['others']: txt += '\nМожливі також: ' + ', '.join(r['others'])
        self.res7.configure(text=txt); self.go7.configure(state='normal'); self.cp7.configure(state='normal')
        def lj():
            try: L = cz_routes.layers(p)
            except Exception as e: L = {}; self.q.put('УВАГА: шари не прочитано: %s' % e)
            self.q.put(lambda: self._layers7(L))
        threading.Thread(target=lj, daemon=True).start()
        self.say('Карта: %s — %s' % (os.path.basename(p), r['system']))

    def _layers7(self, L):
        self.lay7 = L; NO = self.NO7
        closed = sorted(k for k, (c, n) in L.items() if c)
        self.bl7.configure(values=[NO] + closed); self.sl7.configure(values=[NO] + sorted(L))
        guess = [k for k in closed if re.search(r'меж|границ|border|bound', k, re.I)]
        self.bl7.set(guess[0] if guess else NO)
        sg = [k for k in L if re.search(r'укрит|сховищ|shelter|ЦЗ', k, re.I)]
        self.sl7.set(sg[0] if sg else NO)
        self.kb7.configure(state='normal' if closed else 'disabled'); self.cz7.configure(state='normal')

    def _sys7(self):
        return self.loc7['system'] if self.loc7 else None

    def kml7(self):
        p = self.mf7.get().strip(); lay = self.bl7.get()
        if lay == self.NO7: messagebox.showinfo('Межа', 'Виберіть шар межі.'); return
        sysn = self._sys7(); self.say('\n=== Межа → KML: %s, шар «%s»' % (os.path.basename(p), lay))
        def job():
            dst, s, n, a = cz_routes.boundary_kml(p, lay, sysn)
            self.q.put('ГОТОВО: %s — контурів %d, площа %.4f га (%s)' % (dst, n, a / 10000, s))
        self._bg(job, 'Межа → KML')

    def cz7run(self):
        p = self.mf7.get().strip(); kinds = [k for k, v in self.k7.items() if v.get()]
        if not kinds: messagebox.showinfo('ЦЗ', 'Позначте, до чого рахувати відстані.'); return
        sl = self.sl7.get(); bl = self.bl7.get()
        if 'shelter_dxf' in kinds and sl == self.NO7:
            kinds.remove('shelter_dxf'); self.say('УВАГА: шар укриттів не вибрано — укриття зі зйомки пропущено.')
        if not kinds: return
        sysn = self._sys7(); self.say('\n=== Відстані ЦЗ: %s' % os.path.basename(p))
        def job():
            r = cz_routes.compute(p, kinds, sysn, None if bl == self.NO7 else bl, None if sl == self.NO7 else sl,
                                  log=self.q.put, progress=lambda v: self.setp(100 * v))
            for l in r['lines'][5:]: self.q.put('   ' + l)
            self.q.put('ГОТОВО: %s, %s' % (os.path.basename(r['txt']), os.path.basename(r['dxf'])))
        self._bg(job, 'Відстані ЦЗ')

    def open7(self):
        if not self.loc7: return
        import webbrowser
        webbrowser.open(site_map.gmaps_url(self.loc7['lat'], self.loc7['lon'], self.loc7['span']))

    def copy7(self):
        if not self.loc7: return
        self.clipboard_clear(); self.clipboard_append('%.6f, %.6f' % (self.loc7['lat'], self.loc7['lon']))
        self.say('Координати скопійовано в буфер обміну.')

    # ---------- сторінка 8: KML ↔ DXF ----------
    def _tab8(self):
        pg = self.pages['p8']
        f = self._panel(pg, 'Файл', 'folder')
        ttk.Label(f, style='Hint.TLabel', text='KML / KMZ з Google Earth → DXF R12 у вибраній системі.  DXF → KML для Google Earth.\n'
                  'Кнопкою або перетягніть файл у вікно. Результат — поруч із файлом, без перезапису.').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.f8 = tk.StringVar(); ttk.Entry(f, textvariable=self.f8).grid(row=1, column=0, sticky='ew')
        self._btn(f, 'Вибрати…', 'folder', self.pick8).grid(row=1, column=1, padx=(8, 0))
        self.l8 = ttk.Label(f, text='Система координат'); self.l8.grid(row=2, column=0, sticky='w', pady=(10, 2))
        self.s8 = ttk.Combobox(f, width=40, state='readonly'); self.s8.grid(row=3, column=0, sticky='w')
        f.columnconfigure(0, weight=1)
        a = tk.Frame(pg); a.pack(fill='x', pady=(0, 6)); self._reg(a, 'bg')
        self._btn(a, 'Перетворити', 'play', self.run8, primary=True).pack(side='left')
        self._mode8()

    def pick8(self):
        p = filedialog.askopenfilename(title='KML / DXF', filetypes=[('KML, KMZ, DXF', '*.kml *.kmz *.dxf'), ('Усі', '*.*')])
        if p: self.f8.set(p); self._mode8()

    def _mode8(self):
        to_dxf = self.f8.get().lower().endswith(('.kml', '.kmz')) or not self.f8.get()
        vals = geo.systems() if to_dxf else [AUTO7] + geo.systems(); cur = self.s8.get()
        self.s8.configure(values=vals)
        self.s8.set(cur if cur in vals else ('МСК-46 (Львівська обл.)' if to_dxf and 'МСК-46 (Львівська обл.)' in vals else vals[0]))
        self.l8.configure(text='Система координат DXF (куди перерахувати)' if to_dxf else 'Система координат файла')

    def run8(self):
        p = self.f8.get().strip()
        if not os.path.exists(p): messagebox.showinfo('KML ↔ DXF', 'Виберіть файл.'); return
        if not p.lower().endswith(('.kml', '.kmz', '.dxf')):  # DWG → KML не потрібен (рішення користувача 27.11.2026)
            messagebox.showinfo('KML ↔ DXF', 'Підтримуються KML, KMZ і DXF.'); return
        s = self.s8.get(); s = None if s == AUTO7 else s
        self.say('\n=== %s' % os.path.basename(p)); self.setp(10)
        def job():
            if p.lower().endswith(('.kml', '.kmz')):
                d, n = kml_dxf.kml_to_dxf(p, s); self.q.put('   %d об\'єктів → %s' % (n, d))
            else:
                d, sysn, n = kml_dxf.to_kml(p, s); self.q.put('   система: %s; %d об\'єктів → %s' % (sysn, n, d))
                if geo.is_approx(sysn): self.q.put('УВАГА: СК-63 — наближено (кілька метрів)')
            self.setp(100); self.q.put('ГОТОВО')
        self._bg(job)

    # ---------- сторінка 9: калькулятор координат ----------
    def _tab9(self):
        pg = self.pages['p9']
        f = self._panel(pg, 'Системи', 'target')
        vals = [geo.WGS] + geo.systems()
        ttk.Label(f, text='З системи').grid(row=0, column=0, sticky='w')
        ttk.Label(f, text='У систему').grid(row=0, column=1, sticky='w', padx=(16, 0))
        self.a9 = ttk.Combobox(f, values=vals, width=34, state='readonly'); self.a9.grid(row=1, column=0, sticky='w')
        self.b9 = ttk.Combobox(f, values=vals, width=34, state='readonly'); self.b9.grid(row=1, column=1, sticky='w', padx=(16, 0))
        self.a9.set(vals[1] if len(vals) > 1 else vals[0]); self.b9.set(geo.WGS)
        self.o9 = tk.StringVar(value='XY')
        m = ttk.Frame(f); m.grid(row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))
        ttk.Radiobutton(m, text='X (північ), Y (схід) — як у Digitals', value='XY', variable=self.o9).pack(side='left')
        ttk.Radiobutton(m, text='E (схід), N (північ) — як у DXF', value='EN', variable=self.o9).pack(side='left', padx=16)
        f = self._panel(pg, 'Точки', 'calc')
        ttk.Label(f, style='Hint.TLabel', text='Рядок: «назва X Y» або «X Y»; для WGS-84 — широта, довгота в градусах. Роздільник: пробіл, таб, «;».'
                  ).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.in9 = tk.Text(f, height=6, wrap='none', font=('Consolas', 10)); self.in9.grid(row=1, column=0, sticky='nsew')
        self.out9 = tk.Text(f, height=6, wrap='none', font=('Consolas', 10), state='disabled'); self.out9.grid(row=1, column=1, sticky='nsew', padx=(8, 0))
        f.columnconfigure(0, weight=1); f.columnconfigure(1, weight=1)
        a = tk.Frame(pg); a.pack(fill='x', pady=(0, 6)); self._reg(a, 'bg')
        self._btn(a, 'Перерахувати', 'play', self.run9, primary=True).pack(side='left')
        self._btn(a, 'Копіювати', 'copy', self.copy9).pack(side='left', padx=8)
        self._btn(a, 'Зберегти TXT', 'save', self.save9).pack(side='left')

    def run9(self):
        src, dst = self.a9.get(), self.b9.get()
        try: rows, txt = coord_calc.convert(self.in9.get('1.0', 'end'), src, dst, self.o9.get())
        except Exception as e: messagebox.showerror('Калькулятор', str(e)); return
        self.out9.configure(state='normal'); self.out9.delete('1.0', 'end'); self.out9.insert('1.0', txt); self.out9.configure(state='disabled')
        self.say('Калькулятор: %d точок, %s → %s' % (len(rows), src, dst))
        if geo.is_approx(src) or geo.is_approx(dst):
            self.say('УВАГА: СК-63 без ключа — наближено (кілька метрів): для пошуку, не для документів.')

    def copy9(self):
        t = self.out9.get('1.0', 'end').strip()
        if t: self.clipboard_clear(); self.clipboard_append(t); self.say('Результат скопійовано.')

    def save9(self):
        t = self.out9.get('1.0', 'end').strip()
        if not t: return
        p = filedialog.asksaveasfilename(title='Зберегти точки', defaultextension='.txt', filetypes=[('TXT', '*.txt')])
        if p:
            with open(p, 'w', encoding='utf-8-sig') as fh: fh.write('# %s → %s\n%s\n' % (self.a9.get(), self.b9.get(), t))
            self.say('Збережено: %s' % p)

    # ---------- сторінка 10: прив'язка растру ----------
    def _tab10(self):
        pg = self.pages['p10']
        f = self._panel(pg, 'Растр', 'grid')
        top = ttk.Frame(f); top.grid(row=0, column=0, columnspan=2, sticky='ew')
        self._btn(top, 'Відкрити зображення…', 'folder', self.pick10).pack(side='left')
        self.h10 = ttk.Label(top, style='Hint.TLabel', text='  Колесо — масштаб, права кнопка — зсув, клацання — нова точка.')
        self.h10.pack(side='left', padx=8)
        self.cv10 = tk.Canvas(f, height=int(250 * self._s), cursor='crosshair'); self.cv10.grid(row=1, column=0, sticky='nsew', pady=(6, 0))
        side = ttk.Frame(f); side.grid(row=1, column=1, sticky='ns', padx=(8, 0), pady=(6, 0))
        self.tv10 = ttk.Treeview(side, columns=('n', 'x', 'y', 'r'), show='headings', height=6, selectmode='browse')
        for c, w, h in (('n', 34, '№'), ('x', 110, 'X (північ)'), ('y', 110, 'Y (схід)'), ('r', 70, 'Нев., м')):
            self.tv10.heading(c, text=h); self.tv10.column(c, width=int(w * self._s), anchor='e')
        self.tv10.pack(fill='both', expand=True)
        b = ttk.Frame(side); b.pack(fill='x', pady=(6, 0))
        self._btn(b, 'Прибрати точку', 'minus', self.del10).pack(side='left')
        sh = ttk.Frame(side); sh.pack(fill='x', pady=(8, 0))
        self.sh10 = tk.BooleanVar(value=False)
        ttk.Checkbutton(sh, text='Зсув до локального нуля:', variable=self.sh10).grid(row=0, column=0, columnspan=4, sticky='w')
        self.sx10, self.sy10 = tk.StringVar(), tk.StringVar()
        ttk.Label(sh, text='X').grid(row=1, column=0); ttk.Entry(sh, textvariable=self.sx10, width=12).grid(row=1, column=1, padx=(4, 8))
        ttk.Label(sh, text='Y').grid(row=1, column=2); ttk.Entry(sh, textvariable=self.sy10, width=12).grid(row=1, column=3, padx=(4, 0))
        f.columnconfigure(0, weight=1)
        a = tk.Frame(pg); a.pack(fill='x', pady=(0, 6)); self._reg(a, 'bg')
        self._btn(a, 'Прив\'язати', 'play', self.run10, primary=True).pack(side='left')
        self.img10 = None; self.pts10 = []; self.view10 = [1.0, 0.0, 0.0]  # масштаб, зсув x, y
        self.cv10.bind('<Button-1>', self._click10); self.cv10.bind('<MouseWheel>', self._wheel10)
        self.cv10.bind('<ButtonPress-3>', lambda e: setattr(self, '_drag10', (e.x, e.y)))
        self.cv10.bind('<B3-Motion>', self._pan10); self.cv10.bind('<Configure>', lambda e: self._draw10())

    def pick10(self):
        p = filedialog.askopenfilename(title='Зображення', filetypes=[('Зображення', ' '.join('*' + x for x in IMG_EXT)), ('Усі', '*.*')])
        if p: self.load10(p)

    def load10(self, p):
        from PIL import Image
        try:
            with Image.open(p) as im: im.load(); self.img10 = (p, im.convert('RGB'))
        except Exception as e: messagebox.showerror('Растр', str(e)); return
        self.pts10 = []; self._fill10()
        W, H = self.img10[1].size; cw, ch = max(self.cv10.winfo_width(), 100), max(self.cv10.winfo_height(), 100)
        k = min(cw / W, ch / H); self.view10 = [k, (cw - W * k) / 2, (ch - H * k) / 2]
        self.say('Растр: %s (%d×%d)' % (os.path.basename(p), W, H)); self._draw10()

    def _draw10(self):
        from PIL import ImageTk
        cv = self.cv10; cv.delete('all')
        if not self.img10: return
        im = self.img10[1]; k, ox, oy = self.view10; cw, ch = cv.winfo_width(), cv.winfo_height()
        # видима частина зображення
        x0, y0 = max(0, int(-ox / k)), max(0, int(-oy / k))
        x1, y1 = min(im.width, int((cw - ox) / k) + 2), min(im.height, int((ch - oy) / k) + 2)
        if x1 > x0 and y1 > y0:
            crop = im.crop((x0, y0, x1, y1)).resize((max(1, int((x1 - x0) * k)), max(1, int((y1 - y0) * k))))
            self._tk10 = ImageTk.PhotoImage(crop); cv.create_image(ox + x0 * k, oy + y0 * k, anchor='nw', image=self._tk10)
        for i, (px, py, *_rest) in enumerate(self.pts10, 1):
            x, y = ox + px * k, oy + py * k
            cv.create_line(x - 9, y, x + 9, y, fill='#FF3B30', width=2); cv.create_line(x, y - 9, x, y + 9, fill='#FF3B30', width=2)
            cv.create_text(x + 8, y - 8, text=str(i), fill='#FF3B30', anchor='sw', font=('Segoe UI Semibold', 10))

    def _wheel10(self, e):
        if not self.img10: return
        k, ox, oy = self.view10; f = 1.25 if e.delta > 0 else 0.8
        self.view10 = [k * f, e.x - (e.x - ox) * f, e.y - (e.y - oy) * f]; self._draw10()

    def _pan10(self, e):
        x, y = self._drag10; self.view10[1] += e.x - x; self.view10[2] += e.y - y; self._drag10 = (e.x, e.y); self._draw10()

    def _click10(self, e):
        if not self.img10: return
        k, ox, oy = self.view10; px, py = (e.x - ox) / k, (e.y - oy) / k
        W, H = self.img10[1].size
        if not (0 <= px <= W and 0 <= py <= H): return
        v = self._ask_xy(len(self.pts10) + 1)
        if v is None: return
        self.pts10.append((px, py, v[1], v[0]))  # (px, py, E = Y, N = X)
        self._fill10(); self._draw10()

    def _ask_xy(self, n):
        """Діалог «X (північ), Y (схід)» для точки n → (X, Y) або None."""
        d = tk.Toplevel(self); d.title('Точка %d' % n); d.transient(self); d.resizable(False, False)
        fr = ttk.Frame(d, padding=14); fr.pack()
        ttk.Label(fr, text='Координати точки %d' % n, font=('Segoe UI Semibold', 10)).grid(row=0, column=0, columnspan=2, sticky='w')
        xv, yv = tk.StringVar(), tk.StringVar(); res = []
        ttk.Label(fr, text='X (північ)').grid(row=1, column=0, sticky='w', pady=(8, 0))
        ex = ttk.Entry(fr, textvariable=xv, width=18); ex.grid(row=1, column=1, padx=(8, 0), pady=(8, 0))
        ttk.Label(fr, text='Y (схід)').grid(row=2, column=0, sticky='w', pady=(6, 0))
        ttk.Entry(fr, textvariable=yv, width=18).grid(row=2, column=1, padx=(8, 0), pady=(6, 0))
        def ok(*_):
            try: res.append((float(xv.get().replace(',', '.')), float(yv.get().replace(',', '.'))))
            except ValueError: messagebox.showerror('Точка', 'Введіть числа X і Y.', parent=d); return
            d.destroy()
        b = ttk.Frame(fr); b.grid(row=3, column=0, columnspan=2, sticky='e', pady=(12, 0))
        ttk.Button(b, text='Скасувати', command=d.destroy).pack(side='right')
        ttk.Button(b, text='Додати', command=ok, style='Accent.TButton').pack(side='right', padx=(0, 6))
        d.bind('<Return>', ok); d.bind('<Escape>', lambda e: d.destroy())
        ex.focus_set(); d.grab_set(); self.wait_window(d)
        return res[0] if res else None

    def _fill10(self):
        self.tv10.delete(*self.tv10.get_children())
        res = None
        if len(self.pts10) >= 2:
            try: _, res, _ = raster_geo.fit(self.pts10)
            except ValueError: res = None
        for i, (px, py, E, N) in enumerate(self.pts10):
            r = '' if res is None or len(self.pts10) in (2, 3) else '%.3f' % res[i]
            self.tv10.insert('', 'end', iid=str(i), values=(i + 1, '%.3f' % N, '%.3f' % E, r))

    def del10(self):
        s = self.tv10.selection()
        if not s: return
        del self.pts10[int(s[0])]; self._fill10(); self._draw10()

    def run10(self):
        if not self.img10: messagebox.showinfo('Растр', 'Відкрийте зображення.'); return
        if len(self.pts10) < 2: messagebox.showinfo('Растр', 'Поставте щонайменше 2 точки (краще 3–4 — тоді є контроль).'); return
        shift = (0.0, 0.0)
        if self.sh10.get():
            try: shift = (float(self.sy10.get().replace(',', '.')), float(self.sx10.get().replace(',', '.')))  # (E, N)
            except ValueError: messagebox.showerror('Растр', 'Зсув: введіть числа X і Y.'); return
        p, pts = self.img10[0], list(self.pts10)
        self.say('\n=== Прив\'язка %s, точок %d' % (os.path.basename(p), len(pts))); self.setp(5)
        def job():
            r = raster_geo.rectify(p, pts, shift, lambda v: self.setp(100 * v))
            self.q.put('   нев\'язки, м: ' + ', '.join('%.3f' % x for x in r['res']) +
                       ('   СКП %.3f м' % r['rms'] if r['rms'] == r['rms'] else '   (контролю немає — додайте ще точку)'))
            self.q.put('   Archicad: %.3f × %.3f м, лівий нижній кут X(схід) %.3f, Y(північ) %.3f' % (r['size_m'] + r['corner_ll']))
            self.q.put('   → %s\n   → %s\n   → %s' % (r['png'], r['txt'], r['world']))
            self.q.put('ГОТОВО')
        self._bg(job)

    # ---------- сторінка 11: очищення файлів ----------
    def _tab11(self):
        pg = self.pages['p11']
        f = self._panel(pg, 'Файли', 'eraser')
        ttk.Label(f, style='Hint.TLabel', text='DOCX, XLSX, PPTX, PDF — кнопкою або перетягніть у вікно. Змінюються лише метадані;\n'
                  'текст, коментарі й виділення — без змін. Результат — копія «… (чисто)» поруч, оригінал не змінюється.'
                  ).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.lb11 = tk.Listbox(f, height=4, selectmode='extended'); self.lb11.grid(row=1, column=0, sticky='nsew')
        b = ttk.Frame(f); b.grid(row=1, column=1, sticky='n', padx=(8, 0))
        self._btn(b, 'Додати…', 'plus', self.add11).pack(fill='x')
        self._btn(b, 'Прибрати', 'minus', lambda: [self.lb11.delete(i) for i in reversed(self.lb11.curselection())]).pack(fill='x', pady=(4, 0))
        f.columnconfigure(0, weight=1)
        f = self._panel(pg, 'Що вписати', 'save')
        st = load_settings()
        self.au11 = tk.StringVar(value=st.get('clean_author', '')); self.or11 = tk.StringVar(value=st.get('clean_org', ''))
        ttk.Label(f, text='Автор').grid(row=0, column=0, sticky='w')
        ttk.Entry(f, textvariable=self.au11, width=36).grid(row=1, column=0, sticky='w')
        ttk.Label(f, text='Організація').grid(row=0, column=1, sticky='w', padx=(16, 0))
        ttk.Entry(f, textvariable=self.or11, width=36).grid(row=1, column=1, sticky='w', padx=(16, 0))
        ttk.Label(f, style='Hint.TLabel', text='Порожнє поле — стерти. Назва, тема, ключові слова, шаблон, власні властивості, надбудови — стираються завжди.'
                  ).grid(row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))
        a = tk.Frame(pg); a.pack(fill='x', pady=(0, 6)); self._reg(a, 'bg')
        self._btn(a, 'Очистити', 'play', self.run11, primary=True).pack(side='left')

    def add11(self, paths=None):
        ext = file_clean.OOXML + ('.pdf',)
        paths = paths if paths is not None else filedialog.askopenfilenames(
            title='Файли', filetypes=[('Документи', ' '.join('*' + e for e in ext)), ('Усі', '*.*')])
        for p in paths:
            if p.lower().endswith(ext) and p not in self.lb11.get(0, 'end'): self.lb11.insert('end', p)

    def run11(self):
        files = list(self.lb11.get(0, 'end'))
        if not files: messagebox.showinfo('Очищення', 'Додайте файли.'); return
        au, org = self.au11.get().strip(), self.or11.get().strip()
        d = load_settings(); d['clean_author'] = au; d['clean_org'] = org; save_settings(d)
        self.say('\n=== Очищення метаданих: %d файл(ів)' % len(files)); self.setp(0)
        def job():
            ok = 0
            for i, p in enumerate(files, 1):
                try:
                    dst, ch = file_clean.clean(p, au, org); ok += 1
                    self.q.put('%s → %s' % (os.path.basename(p), os.path.basename(dst)))
                    for c in ch: self.q.put('   ' + c)
                except Exception as e:
                    self.q.put('ПОМИЛКА %s: %s' % (os.path.basename(p), e))
                self.setp(100.0 * i / len(files))
            self.q.put('ГОТОВО: %d з %d' % (ok, len(files)) if ok == len(files) else 'УВАГА: очищено %d з %d' % (ok, len(files)))
        self._bg(job)

    # ---------- сторінка 12: кадастр — обмінний файл XML ДЗК ----------
    def _tab12(self):
        pg = self.pages['p12']
        f = self._panel(pg, 'Обмінний файл ДЗК', 'parcel')
        ttk.Label(f, style='Hint.TLabel', text='XML ДЗК (від землевпорядника / з кадастрової справи) → DXF R12: межа, угіддя, обмеження,\n'
                  'оренда, точки з номерами + TXT із площею, ЦП і к.н. Офлайн — у мережу нічого не надсилається.'
                  ).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.f12 = tk.StringVar(); ttk.Entry(f, textvariable=self.f12).grid(row=1, column=0, sticky='ew')
        self._btn(f, 'Вибрати…', 'folder', lambda: self._pick(self.f12, [('XML ДЗК', '*.xml'), ('Усі', '*.*')])).grid(row=1, column=1, padx=(8, 0))
        ttk.Label(f, text='Система координат DXF').grid(row=2, column=0, sticky='w', pady=(10, 2))
        self.s12 = ttk.Combobox(f, values=['Як у файлі (без перерахунку)'] + geo.systems(), width=40, state='readonly')
        self.s12.set('Як у файлі (без перерахунку)'); self.s12.grid(row=3, column=0, sticky='w')
        f.columnconfigure(0, weight=1)
        a = tk.Frame(pg); a.pack(fill='x', pady=(0, 12)); self._reg(a, 'bg')
        self._btn(a, 'Перетворити в DXF', 'play', self.run12, primary=True).pack(side='left')
        f = self._panel(pg, 'Ділянка на карті', 'globe')
        ttk.Label(f, text='Кадастровий номер').grid(row=0, column=0, sticky='w')
        r = ttk.Frame(f); r.grid(row=1, column=0, columnspan=2, sticky='w')
        self.kn12 = tk.StringVar(); ttk.Entry(r, textvariable=self.kn12, width=30).pack(side='left')
        self._btn(r, 'Відкрити на kadastr.com.ua', 'globe', self.open12).pack(side='left', padx=(8, 0))
        ttk.Label(f, style='Hint.TLabel', text='Номер передається на сайт лише після натиснення кнопки. Номер із XML підставляється сам.'
                  ).grid(row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))

    def run12(self):
        p = self.f12.get().strip()
        if not p or not os.path.exists(p): messagebox.showinfo('Кадастр', 'Виберіть XML-файл ДЗК.'); return
        s = self.s12.get(); s = None if s.startswith('Як у') else s
        self.say('\n=== XML ДЗК %s' % os.path.basename(p))
        def job():
            r = dzk_xml.to_dxf(p, s)
            for l in r['lines']: self.q.put('   ' + l)
            if r['kn']: self.q.put(lambda: self.kn12.set(r['kn']))
            self.q.put('ГОТОВО: %s' % r['dxf'])
        self._bg(job)

    def open12(self):
        try: url = dzk_xml.kn_url(self.kn12.get())
        except ValueError as e: messagebox.showinfo('Кадастр', str(e)); return
        import webbrowser; webbrowser.open(url)

    # ---------- сторінка 13: перевірка ПЗ ----------
    def _tab13(self):
        pg = self.pages['p13']
        f = self._panel(pg, 'Пояснювальна записка', 'check')
        ttk.Label(f, style='Hint.TLabel', text='DOCX — кнопкою або перетягніть у вікно. Звіт «… (перевірка).txt» поруч; оригінал не змінюється.\n'
                  'Перевіряє: латиницю в шифрах норм, змішані слова, залишки чатів/ШІ, заглушки, виділення, червоний текст,\n'
                  'коментарі й рецензування, метадані, нумерацію таблиць і рисунків, подвійні пробіли.'
                  ).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.lb13 = tk.Listbox(f, height=4, selectmode='extended'); self.lb13.grid(row=1, column=0, sticky='nsew')
        b = ttk.Frame(f); b.grid(row=1, column=1, sticky='n', padx=(8, 0))
        self._btn(b, 'Додати…', 'plus', self.add13).pack(fill='x')
        self._btn(b, 'Прибрати', 'minus', lambda: [self.lb13.delete(i) for i in reversed(self.lb13.curselection())]).pack(fill='x', pady=(4, 0))
        f.columnconfigure(0, weight=1)
        self.fx13 = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text='Створити виправлену копію «… (виправлено).docx» (латиниця в шифрах і словах, жовте виділення)',
                        variable=self.fx13).grid(row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))
        a = tk.Frame(pg); a.pack(fill='x', pady=(0, 6)); self._reg(a, 'bg')
        self._btn(a, 'Перевірити', 'play', self.run13, primary=True).pack(side='left')

    def add13(self, paths=None):
        paths = paths if paths is not None else filedialog.askopenfilenames(title='ПЗ', filetypes=[('Word', '*.docx'), ('Усі', '*.*')])
        for p in paths:
            if p.lower().endswith('.docx') and p not in self.lb13.get(0, 'end'): self.lb13.insert('end', p)

    def run13(self):
        files = list(self.lb13.get(0, 'end')); fix = self.fx13.get()
        if not files: messagebox.showinfo('Перевірка ПЗ', 'Додайте DOCX.'); return
        self.say('\n=== Перевірка ПЗ: %d файл(ів)' % len(files))
        def job():
            for i, p in enumerate(files, 1):
                try:
                    txt, out, n = pz_check.report(p, fix)
                    self.q.put('%s: зауважень %d → %s%s' % (os.path.basename(p), n, os.path.basename(txt),
                                                           ', ' + os.path.basename(out) if out else ''))
                except Exception as e:
                    self.q.put('ПОМИЛКА %s: %s' % (os.path.basename(p), e))
                self.setp(100.0 * i / len(files))
            self.q.put('ГОТОВО')
        self._bg(job)

    # ---------- перетягування файлів у вікно (tkinterdnd2; без нього — лише кнопки) ----------
    def _dnd_setup(self):
        """Файли, перетягнуті на вікно, ідуть на відкриту сторінку: PDF → p6, DXF/DWG → p7, DXF → p1."""
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES
            TkinterDnD._require(self)
            self.drop_target_register(DND_FILES)
        except Exception:
            return
        def on_drop(e):
            ps = list(self.tk.splitlist(e.data))
            if self.cur == 'p6': self.add6(ps)
            elif self.cur == 'p7':
                ps = [p for p in ps if p.lower().endswith(('.dxf', '.dwg'))]
                if ps: self.mf7.set(ps[0]); self.locate7()
            elif self.cur == 'p8':
                ps = [p for p in ps if p.lower().endswith(('.kml', '.kmz', '.dxf'))]
                if ps: self.f8.set(ps[0]); self._mode8()
            elif self.cur == 'p10':
                ps = [p for p in ps if p.lower().endswith(IMG_EXT)]
                if ps: self.load10(ps[0])
            elif self.cur == 'p11': self.add11(ps)
            elif self.cur == 'p13': self.add13(ps)
            elif self.cur == 'p12':
                ps = [p for p in ps if p.lower().endswith('.xml')]
                if ps: self.f12.set(ps[0])
            elif self.cur == 'p1':
                for p in ps:
                    if p.lower().endswith('.dxf') and p not in self.lb1.get(0, 'end'): self.lb1.insert('end', p)
            else:
                self.say('На цій сторінці файли не перетягуються — відкрийте потрібний розділ меню.')
            return e.action
        self.dnd_bind('<<Drop>>', on_drop)

    def _changelog(self):
        try:
            with open(os.path.join(HERE, 'CHANGELOG.md'), encoding='utf-8') as fh:
                t = fh.read(); i = t.find('\n## ')  # лише розділи версій, без шапки й опису формату
                return t[i + 1:].strip() if i >= 0 else ''
        except OSError:
            return ''

    def _set_notes(self, text):
        self.notes.configure(state='normal'); self.notes.delete('1.0', 'end')
        self.notes.insert('1.0', text.replace('## ', '')); self.notes.configure(state='disabled')

    def _save_auto(self):
        d = load_settings(); d['update_auto'] = bool(self.upd_auto.get()); save_settings(d)

    def _auto_update(self):
        if updater.due(load_settings()): self.check_update(manual=False)

    def check_update(self, manual=True):
        """Перевірка в фоні. Автоматична — мовчки при помилці мережі; ручна — пише, що сталося."""
        if manual: self.upd_st.configure(text='Перевіряю…')
        def job():
            try: info = updater.check()
            except Exception as e:
                msg = 'Не вдалося перевірити оновлення: %s' % e
                if manual: self.q.put(lambda: self.upd_st.configure(text=msg)); self.q.put('УВАГА: ' + msg)
                return
            save_settings(updater.mark_checked(load_settings()))
            self.q.put(lambda: self._found(info, manual))
        threading.Thread(target=job, daemon=True).start()

    def _found(self, info, manual):
        self.upd = info
        if not info:
            self.upd_st.configure(text='У вас остання версія (%s).' % VERSION); self.upd_btn.configure(state='disabled')
            if manual: self.say('Оновлення: у вас остання версія %s.' % VERSION)
            return
        v = info['version']; can = updater.can_install()
        self.upd_st.configure(text='Доступна версія %s.' % v)
        self.upd_btn.configure(text=' Оновити до %s' % v, state='normal' if can else 'disabled')
        self.verlab.configure(text='URBAN %s  ·  є %s' % (VERSION, v))
        self._set_notes('%s — нова версія\n%s\n\n%s' % (v, info['notes'], self._changelog()))
        self.say('УВАГА: є нова версія URBAN %s (у вас %s) — розділ «Оновлення».' % (v, VERSION))
        notes = info['notes'] if len(info['notes']) < 1200 else info['notes'][:1200] + '…'
        if can:
            if messagebox.askyesno('Оновлення URBAN', 'Доступна версія %s (у вас %s).\n\nЩо нового:\n%s\n\n'
                                   'Оновити зараз? Програма закриється й відкриється вже новою версією.' % (v, VERSION, notes)):
                self.install_update()
        elif manual:
            messagebox.showinfo('Оновлення URBAN', 'На GitHub є версія %s (у вас %s).\nЦе робоча версія з Python — '
                                'оновлюйте код, а встановлену програму оновить інсталятор.' % (v, VERSION))

    def install_update(self):
        info = self.upd
        if not info or not updater.can_install(): return
        self.upd_btn.configure(state='disabled'); self.upd_st.configure(text='Завантажую версію %s…' % info['version'])
        self.say('\n=== Оновлення до %s' % info['version']); self._upbar(info['version'], 0)
        def job():
            try: path = updater.download(info, lambda fr: self.q.put(lambda: self._upbar(info['version'], 100 * fr)))
            except Exception as e:
                msg = str(e); self.q.put('ПОМИЛКА оновлення: %s' % msg)
                self.q.put(lambda: (self._upbar(None), self.upd_st.configure(text='Не вдалося: ' + msg),
                                    self.upd_btn.configure(state='normal')))
                return
            self.q.put('ГОТОВО: завантажено й перевірено (SHA-256). Запускаю встановлення — програма закриється.')
            def go():
                try: updater.run_installer(path)
                except Exception as e:
                    self._upbar(None)
                    self.say('ПОМИЛКА: не вдалося запустити інсталятор: %s' % e); self.upd_btn.configure(state='normal'); return
                self.after(800, self.destroy)
            self.q.put(go)
        threading.Thread(target=job, daemon=True).start()

    def _upbar(self, version, v=0.0):
        """Шкала оновлення в рейці: version=None — сховати й повернути підпис версії."""
        if version is None:
            self.upb.pack_forget(); self.verlab.pack_configure(pady=12)
            self.verlab.configure(text='URBAN %s  ·  є %s' % (VERSION, self.upd['version']) if self.upd else 'URBAN ' + VERSION)
            return
        if not self.upb.winfo_ismapped():
            self.verlab.pack_configure(pady=(12, 4))
            self.upb.pack(side='bottom', fill='x', padx=20, pady=(0, 14), before=self.verlab)
        v = max(0.0, min(100.0, v)); self.upb['value'] = v
        self.verlab.configure(text='Оновлення до %s  ·  %d %%' % (version, round(v)))

    # ---------- сторінка 3: ключ за спільними пунктами ----------
    def _tab3(self):
        pg = self.pages['p3']
        f = self._panel(pg, 'Файл пунктів', 'folder')
        ttk.Label(f, style='Hint.TLabel', text='TXT/CSV: назва; X1; Y1; X2; Y2 — координати того самого пункту в системі 1 і системі 2.'
                  ).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.ptf = tk.StringVar(); ttk.Entry(f, textvariable=self.ptf).grid(row=1, column=0, sticky='ew')
        self._btn(f, 'Вибрати…', 'folder', lambda: self._pick(self.ptf, [('Пункти', '*.txt *.csv'), ('Усі', '*.*')])).grid(row=1, column=1, padx=(8, 0))
        self.geo = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text='X — північ, Y — схід (геодезичний порядок, як у каталогах)', variable=self.geo).grid(row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))
        f.columnconfigure(0, weight=1)
        f = self._panel(pg, 'Системи й метод', 'target')
        ttk.Label(f, text='Система 1').grid(row=0, column=0, sticky='w')
        ttk.Label(f, text='Система 2').grid(row=0, column=1, sticky='w', padx=(16, 0))
        self.kf = ttk.Combobox(f, values=['СК-63'] + crs.systems(), width=30); self.kf.set('СК-63'); self.kf.grid(row=1, column=0, sticky='w')
        self.kt = ttk.Combobox(f, values=crs.systems(), width=32, state='readonly'); self.kt.grid(row=1, column=1, sticky='w', padx=(16, 0))
        if crs.systems(): self.kt.current(0)
        self.meth = tk.StringVar(value='helmert2d')
        m = ttk.Frame(f); m.grid(row=2, column=0, columnspan=2, sticky='w', pady=(10, 0))
        ttk.Radiobutton(m, text='Гельмерт (зсув, поворот, масштаб; ≥ 2 пункти)', value='helmert2d', variable=self.meth).pack(side='left')
        ttk.Radiobutton(m, text='Афінне (≥ 3 пункти)', value='affine2d', variable=self.meth).pack(side='left', padx=16)
        ttk.Label(f, text='Джерело пунктів (для запису)').grid(row=3, column=0, sticky='w', pady=(10, 2))
        self.ksrc = tk.StringVar(); ttk.Entry(f, textvariable=self.ksrc).grid(row=4, column=0, columnspan=2, sticky='ew')
        f.columnconfigure(1, weight=1)
        a = tk.Frame(pg); a.pack(fill='x', pady=(0, 6)); self._reg(a, 'bg')
        self._btn(a, 'Обчислити', 'calc', self.calc3, primary=True).pack(side='left')
        self.sv3 = self._btn(a, 'Зберегти ключ', 'save', self.save3, state='disabled'); self.sv3.pack(side='left', padx=8)
        self.key3 = None

    def calc3(self):
        p = self.ptf.get().strip()
        if not os.path.exists(p): messagebox.showinfo('Ключ', 'Виберіть файл пунктів.'); return
        try:
            P = crs.read_points(p, self.geo.get())
            key, res, rms = crs.fit(P, self.meth.get())
        except Exception as e:
            messagebox.showerror('Ключ', str(e)); return
        self.say('\n=== Ключ %s → %s, %s, пунктів: %d' % (self.kf.get(), self.kt.get(), self.meth.get(), len(P)))
        for nm, de, dn, d in res: self.say('   %-12s  dE %+8.3f  dN %+8.3f  |d| %7.3f м' % (nm, de, dn, d))
        self.say('   СКП: %s м' % ('%.3f' % rms if rms == rms else 'не визначається (мало пунктів)'))
        if '_масштаб' in key: self.say('   масштаб %.8f, поворот %.2f″' % (key['_масштаб'], key['_поворот_сек']))
        mx = max(r[3] for r in res)
        if mx > 0.10: self.say('   УВАГА: нев’язка до %.2f м — перевірте пункти (помилка в координатах чи інша зона).' % mx)
        self.say('   Ключ діє лише в районі пунктів; за межами їхнього охоплення точність падає.')
        self.key3 = (self.kf.get().strip(), self.kt.get(), key, rms, len(P), p); self.sv3.configure(state='normal')

    def save3(self):
        if not self.key3: return
        frm, to, key, rms, n, p = self.key3
        if not frm or frm == to: messagebox.showerror('Ключ', 'Вкажіть різні системи.'); return
        import datetime
        src = (self.ksrc.get().strip() or 'не вказано') + '; пункти: %s; n=%d; СКП=%.3f м; %s' % (os.path.basename(p), n, rms if rms == rms else -1, datetime.date.today())
        crs.save_key(frm, to, key, src, 'район пунктів')
        ch = sys_choices()
        for cb in (self.src1, self.src2): cb.configure(values=[AUTO] + ch)
        self.dst1.configure(values=[SAME] + ch); self.dst2.configure(values=[SAME.replace('топо', 'DMF')] + ch)
        self.kf.configure(values=['СК-63'] + crs.systems()); self.kt.configure(values=crs.systems())
        self.say('Ключ %s → %s збережено (%s). Тепер «%s» доступна у вкладках перетворення.' % (frm, to, crs.KEYS, frm))

    # ---------- службове ----------
    def say(self, s):
        t = s.strip()
        tag = ('ok' if t.startswith('ГОТОВО') else 'err' if t.startswith('ПОМИЛКА') or 'НЕ ВИЙШЛО' in t
               else 'warn' if t.startswith(('УВАГА', 'Увага')) else 'head' if t.startswith('===') else '')
        self.log.configure(state='normal'); self.log.insert('end', s + '\n', tag or ()); self.log.see('end'); self.log.configure(state='disabled')

    def _pump(self):
        try:
            while True:
                m = self.q.get_nowait()
                if callable(m): m()
                else: self.say(m)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _bg(self, fn, name=None):
        """Фоновий процес відкритої сторінки з власною шкалою; name — підпис (типово — назва сторінки)."""
        jid = self._job_start(name)
        def w():
            self._tl.job = jid; ok = True
            try: fn()
            except Exception as e:
                ok = False; self.q.put('ПОМИЛКА: %s' % e); self.q.put(traceback.format_exc().splitlines()[-1])
            self.q.put(lambda: self._job_end(jid, ok))
        threading.Thread(target=w, daemon=True).start()

    # ---------- процеси: шкали лише на своїй сторінці + загальний список на «Процеси» ----------
    def _job_start(self, name=None):
        page = self.cur or 'p0'; name = name or self.TITLES.get(page, ('Процес',))[0]
        same = sum(1 for j in self._jobs.values() if j['state'] == 'run' and j['page'] == page)
        if same: name = '%s (%d)' % (name, same + 1)
        self._jn += 1; jid = self._jn
        self._jobs[jid] = dict(page=page, name=name, v=0.0, state='run', t0=time.time(), t1=None)
        self._bars(); self._jobs_view()
        return jid

    def _job_end(self, jid, ok=True):
        j = self._jobs.get(jid)
        if not j: return
        j['state'] = 'ok' if ok else 'err'; j['t1'] = time.time()
        if ok: j['v'] = 100.0
        self._bars(); self._jobs_view()
        self.after(4000, self._bars)  # зайві завершені рядки сторінки прибрати

    def _page_jobs(self, page):
        """Що показати на сторінці: її активні процеси й щойно (< 4 с) завершені; інакше — останній завершений."""
        js = [(k, j) for k, j in self._jobs.items() if j['page'] == page]
        show = [(k, j) for k, j in js if j['state'] == 'run' or time.time() - j['t1'] < 3.9]
        return show or js[-1:]

    def _bars(self):
        """Перебудувати шкали відкритої сторінки (на «Процеси» шкал немає — там таблиця)."""
        ids = [] if self.cur == 'p0' else ([k for k, _ in self._page_jobs(self.cur)] or [0])
        for k in list(self._rows):
            if k not in ids: self._rows.pop(k)['row'].destroy()
        for k in ids:
            if k not in self._rows:
                r = tk.Frame(self.pbox); r.pack(fill='x', pady=1); self._reg(r, 'bg')
                lab = tk.Label(r, width=30, anchor='w', font=('Segoe UI', 10)); lab.pack(side='left', padx=(0, 8))
                self._reg(lab, 'bg', 'text2')
                pb = ttk.Progressbar(r, maximum=100); pb.pack(side='left', fill='x', expand=True)
                pct = tk.Label(r, width=8, anchor='e', font=('Segoe UI', 10)); pct.pack(side='left', padx=(8, 0))
                self._reg(pct, 'bg', 'text2')
                self._rows[k] = dict(row=r, lab=lab, pb=pb, pct=pct)
            self._paint_row(k)

    def _paint_row(self, k):
        w = self._rows.get(k)
        if not w: return
        j = self._jobs.get(k)
        if not j:
            w['lab'].configure(text='Немає активних процесів'); w['pb']['value'] = 0; w['pct'].configure(text='0 %'); return
        w['lab'].configure(text=j['name'] + {'run': '', 'ok': ' — готово', 'err': ' — помилка'}[j['state']])
        w['pb']['value'] = j['v']; w['pct'].configure(text='помилка' if j['state'] == 'err' else '%d %%' % round(j['v']))

    def setp(self, v, job=None):
        v = max(0.0, min(100.0, v)); jid = job or getattr(self._tl, 'job', None)
        def u():
            if jid in self._jobs: k = jid
            else:  # виклик поза процесом — до активного процесу відкритої сторінки, якщо він один
                live = [k for k, j in self._jobs.items() if j['state'] == 'run' and j['page'] == self.cur]
                if len(live) != 1: return
                k = live[0]
            self._jobs[k]['v'] = v; self._paint_row(k); self._jobs_view(k)
        self.q.put(u)

    # ---------- сторінка 0: процеси (стартова) ----------
    def _tab0(self):
        pg = self.pages['p0']
        f = self._panel(pg, 'Процеси сеансу', 'activity')
        ttk.Label(f, style='Hint.TLabel', text='Шкала процесу — на його сторінці; тут — усі процеси разом. '
                  'Подвійне клацання — перейти до сторінки процесу.').grid(row=0, column=0, sticky='w', pady=(0, 6))
        self.tv0 = ttk.Treeview(f, columns=('n', 's', 'p', 'st', 't'), show='headings', height=9, selectmode='browse')
        for c, t, w, a in (('n', 'Процес', 260, 'w'), ('s', 'Розділ', 170, 'w'), ('p', '%', 60, 'e'), ('st', 'Стан', 100, 'w'),
                           ('t', 'Початок · тривалість', 150, 'w')):
            self.tv0.heading(c, text=t, anchor=a); self.tv0.column(c, width=w, anchor=a, stretch=c == 'n')
        self.tv0.grid(row=1, column=0, sticky='ew'); f.columnconfigure(0, weight=1)
        self.tv0.bind('<Double-1>', self._go0)
        self.st0 = ttk.Label(f, style='Hint.TLabel', text='Процесів ще не було.'); self.st0.grid(row=2, column=0, sticky='w', pady=(8, 0))
        f = self._panel(pg, 'Програма', 'refresh')
        self.ver0 = ttk.Label(f, style='Hint.TLabel', text='URBAN %s' % VERSION, justify='left'); self.ver0.grid(row=0, column=0, sticky='w')
        self._btn(f, 'Оновлення…', 'refresh', lambda: self.show('p5')).grid(row=1, column=0, sticky='w', pady=(8, 0))
        self._tick0()

    def _jobs_view(self, only=None):
        if not hasattr(self, 'tv0'): return
        now = time.time()
        for k, j in self._jobs.items():
            if only and k != only: continue
            dt = int((j['t1'] or now) - j['t0'])
            vals = (j['name'], self.TITLES.get(j['page'], ('',))[0], '%d %%' % round(j['v']),
                    {'run': 'працює', 'ok': 'готово', 'err': 'помилка'}[j['state']],
                    '%s · %d:%02d' % (time.strftime('%H:%M:%S', time.localtime(j['t0'])), dt // 60, dt % 60))
            iid = 'j%d' % k
            if self.tv0.exists(iid): self.tv0.item(iid, values=vals)
            else: self.tv0.insert('', 0, iid=iid, values=vals)
        run = sum(j['state'] == 'run' for j in self._jobs.values()); err = sum(j['state'] == 'err' for j in self._jobs.values())
        self.st0.configure(text='Активних: %d · завершено: %d · з помилкою: %d' % (run, len(self._jobs) - run - err, err)
                           if self._jobs else 'Процесів ще не було.')

    def _tick0(self):  # хвилинник активних процесів і стан оновлення
        if any(j['state'] == 'run' for j in self._jobs.values()): self._jobs_view()
        up = getattr(self, 'upd', None)
        self.ver0.configure(text='URBAN %s · %s' % (VERSION, 'доступне оновлення %s' % up['version'] if up
                                                     else 'нових версій не знайдено або ще не перевірено'))
        self.after(1000, self._tick0)

    def _go0(self, e):
        sel = self.tv0.selection()
        j = self._jobs.get(int(sel[0][1:])) if sel else None
        if j: self.show(j['page'])

    def _run(self, args, lo=0.0, hi=100.0, marks=None):
        """Запуск скрипта з прогресом: marks {підрядок у виводі: частка 0..1}; між мітками шкала повільно росте."""
        marks = marks or {}
        p = subprocess.Popen(py_cmd(args[0]) + args[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        state = {'f': 0.0, 'cap': min(marks.values()) if marks else 0.9}
        jid = getattr(self._tl, 'job', None)
        def creep():
            self._tl.job = jid
            while p.poll() is None:
                if state['f'] < state['cap'] - 0.01:
                    state['f'] += (state['cap'] - state['f']) * 0.04; self.setp(lo + (hi - lo) * state['f'])
                threading.Event().wait(0.25)
        threading.Thread(target=creep, daemon=True).start()
        for l in p.stdout:
            l = l.rstrip()
            if l: self.q.put('   ' + l)
            for k, v in marks.items():
                if k in l and v > state['f']:
                    state['f'] = v; self.setp(lo + (hi - lo) * v)
                    nxt = [x for x in marks.values() if x > v]; state['cap'] = min(nxt) if nxt else 0.98
        ok = p.wait() == 0
        if ok: self.setp(hi)
        return ok

    def _tf(self, src, dst):
        if dst.startswith('Як у') or not dst: return None, ''
        if src == SK63 or dst == SK63:
            raise ValueError('Для СК-63 відкритих ключів немає: перерахунок можливий лише за офіційним ключем або спільними пунктами.')
        if not src: raise ValueError('Вкажіть систему вихідного файла (топо/DMF), щоб перерахувати в %s' % dst)
        return crs.transformer(src, dst), dst

    # ---------- дії ----------
    def run1(self):
        files = list(self.lb1.get(0, 'end')); src, dst = self.src1.get().strip(), self.dst1.get()
        dmf_manual = self.dmf1.get().strip()
        if not files: messagebox.showinfo('Конвертер', 'Додайте DXF.'); return
        if src != AUTO:
            try: self._tf(src, dst)
            except Exception as e: messagebox.showerror('Перерахунок', str(e)); return
        def job():
            n = len(files); self.setp(0)
            for i, f in enumerate(files):
                lo, span = 100.0 * i / n, 100.0 / n
                self.q.put('\n=== %s' % f)
                dmf = dmf_manual if dmf_manual.lower().endswith('.dmf') and os.path.exists(dmf_manual) else None
                if not dmf:
                    c = find_dmf(f)
                    if len(c) != 1:
                        self.q.put('Топо DMF: знайдено %d — виберіть файл кнопкою «Вибрати…».' % len(c)); continue
                    dmf = c[0]
                self.q.put('Топо: %s' % dmf)
                try:
                    s = self._src(src, dmf); fn, tag = self._tf(s, dst)
                except Exception as e:
                    self.q.put('НЕ ВИЙШЛО — %s' % e); continue
                out = suffix_name(f, 'МСК, Digitals')
                if fn:  # проміжний файл — у тимчасовій папці, щоб не чіпати наявний «(МСК, Digitals)»
                    import tempfile
                    out = os.path.join(tempfile.gettempdir(), 'dpt_conv_%d.dxf' % os.getpid())
                cut = lo + span * (0.8 if fn else 1.0)
                if not self._run([os.path.join(HERE, 'dxf_digitals.py'), f, dmf, out], lo, cut,
                                 {'прочитано': 0.1, 'одиниці': 0.85, 'записано': 0.97}):
                    self.q.put('НЕ ВИЙШЛО — файл не записано'); continue
                if fn:
                    out2 = suffix_name(f, '%s, Digitals' % tag)
                    crs.transform_dxf_r12(out, out2, fn, lambda fr, a=cut, b=lo + span: self.setp(a + (b - a) * fr)); os.remove(out); out = out2
                    self.q.put('   перераховано %s → %s' % (s, tag))
                self.setp(lo + span)
                self.q.put('ГОТОВО: %s' % out)
            self.setp(100)
        self._bg(job)

    def run2(self):
        p = self.dmf2.get().strip(); src, dst = self.src2.get().strip(), self.dst2.get()
        if not os.path.exists(p): messagebox.showinfo('Конвертер', 'Виберіть DMF.'); return
        if src == AUTO and not dst.startswith('Як у'):
            s, why = detect_system(p)
            self.say('Система DMF: %s — %s' % (s or 'НЕ ВИЗНАЧЕНО', why))
            if not s: messagebox.showerror('Перерахунок', 'Систему DMF не визначено — виберіть її в списку.'); return
            src = s
        try: fn, tag = self._tf(src, dst)
        except Exception as e: messagebox.showerror('Перерахунок', str(e)); return
        shift = None
        if self.sh.get():
            try: shift = (float(self.she.get().replace(',', '.')), float(self.shn.get().replace(',', '.')))
            except ValueError: messagebox.showerror('Зсув', 'Введіть E і N числами.'); return
        def job():
            self.q.put('\n=== %s' % p)
            out = suffix_name(p, 'з DMF' + (', зсув 0' if shift else ''))
            args = [os.path.join(HERE, 'dmf2dxf.py'), p, out] + (['--shift', str(shift[0]), str(shift[1])] if shift else [])
            self.setp(0); cut = 80.0 if fn and not shift else 100.0
            if not self._run(args, 0, cut): self.q.put('НЕ ВИЙШЛО'); return
            if fn:
                if shift: self.q.put('Увага: перерахунок систем зі зсувом до нуля не поєднується — перерахунок пропущено.')
                else:
                    out2 = suffix_name(p, 'з DMF, %s' % tag)
                    crs.transform_dxf_r12(out, out2, fn, lambda fr: self.setp(80 + 20 * fr)); out = out2
                    self.q.put('   перераховано %s → %s' % (src, tag))
            self.setp(100); self.q.put('ГОТОВО: %s' % out)
        self._bg(job)


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--script':  # exe: виконати службовий скрипт (dxf_digitals / dmf2dxf)
        import runpy
        sc = sys.argv[2]; sys.argv = sys.argv[2:]; sys.path.insert(0, os.path.dirname(sc))
        if sys.stdout: sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        runpy.run_path(sc, run_name='__main__')
    else:
        app = App()
        for p in sys.argv[1:]:  # DXF, перетягнуті на ярлик/exe
            if p.lower().endswith('.dxf') and 'Digitals' not in os.path.basename(p): app.lb1.insert('end', os.path.abspath(p))
        app.mainloop()
