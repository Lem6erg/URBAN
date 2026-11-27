"""URBAN (раніше «Конвертер ДПТ»): Archicad DXF → Digitals (МСК/СК-63/УСК-2000) і DMF → DXF R12.
Запуск: G:\\URBAN\\Документація\\URBAN.bat (pythonw). Створено 27.11.2026 (CLAUDE); код — G:\\URBAN\\URBAN [app].
Перерахунок між системами — лише за ключами з crs_keys.json (див. crs.py); без ключів доступно «як у топо»."""
import os, sys, threading, subprocess, queue, re, traceback, json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crs
import ui_icons
import updater
from version import VERSION
from dxf_digitals_drop import find_dmf

SAME = 'Як у топо (без перерахунку)'
SK63 = 'СК-63 (немає ключа)'


def sys_choices():
    return crs.systems() + ([SK63] if not any('СК-63' in n for n in crs.systems()) else [])


AUTO = 'Автоматично (за DMF)'


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
    RAIL = [('КОНВЕРТАЦІЯ', [('p1', 'layers', 'Archicad → Digitals'), ('p2', 'convert', 'DMF → DXF')]),
            ('КООРДИНАТИ', [('p3', 'target', 'Ключ за пунктами')]),
            ('ARCHICAD', [('p4', 'plug', 'Транслятор')]),
            ('ПРОГРАМА', [('p5', 'refresh', 'Оновлення')])]
    TITLES = {'p1': ('Archicad DXF → Digitals', 'DXF з Archicad → система топо, кольори шарів, DXF R12 для Digitals'),
              'p2': ('DMF → DXF', 'Топо Digitals → DXF R12 для Archicad чи CAD'),
              'p3': ('Ключ за пунктами', 'Перехід між системами координат за спільними пунктами (СК-63 тощо)'),
              'p4': ('Транслятор Archicad', 'Підключення «07 Для Digitals (МСК)» в Archicad і експорт DXF'),
              'p5': ('Оновлення', 'Версія програми, що нового, оновлення з GitHub')}

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
        t = tk.Label(top, text='Archicad  ·  Digitals  ·  системи координат', font=('Segoe UI', 10))
        t.pack(side='left', padx=(14, 0), pady=(3, 0)); self._reg(t, 'card', 'text2')
        sg = ttk.Frame(top, style='Seg.TFrame', padding=2); sg.pack(side='right', padx=18)
        self.segb = {}
        for k, txt, ic in (('auto', 'Авто', 'auto'), ('light', 'Світла', 'sun'), ('dark', 'Темна', 'moon')):
            b = ttk.Button(sg, text=' ' + txt, style='Seg.TButton', takefocus=False, compound='left', command=lambda k=k: self.set_mode(k))
            b.pack(side='left', padx=1); self.segb[k] = b; self._icon_w.append((b, ic, 'seg:' + k, 16))
        line = tk.Frame(self, height=1); line.pack(fill='x'); self._reg(line, 'sep')
        body = tk.Frame(self); body.pack(fill='both', expand=True); self._reg(body, 'bg')
        # рейка
        rail = self.rail = tk.Frame(body, width=int(224 * s)); rail.pack(side='left', fill='y'); rail.pack_propagate(False); self._reg(rail, 'card')
        line = tk.Frame(body, width=1); line.pack(side='left', fill='y'); self._reg(line, 'sep')
        self.items = {}
        for gi, (g, items) in enumerate(self.RAIL):
            if gi:
                sp = tk.Frame(rail, height=1); sp.pack(fill='x', padx=16, pady=(10, 2)); self._reg(sp, 'sep')
            h = tk.Label(rail, text=g, font=('Segoe UI Semibold', 8), anchor='w'); h.pack(fill='x', padx=20, pady=(14 if not gi else 8, 4))
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
        for k in ('p1', 'p2', 'p3', 'p4', 'p5'):
            self.pages[k] = tk.Frame(box); self._reg(self.pages[k], 'bg')
        self._tab1(); self._tab2(); self._tab3(); self._tab4(); self._tab5()
        pf = tk.Frame(main); pf.pack(fill='x', padx=26, pady=(4, 8)); self._reg(pf, 'bg')
        self.pb = ttk.Progressbar(pf, maximum=100); self.pb.pack(side='left', fill='x', expand=True)
        self.pct = tk.Label(pf, text='0 %', width=6, anchor='e', font=('Segoe UI', 10)); self.pct.pack(side='left', padx=(8, 0))
        self._reg(self.pct, 'bg', 'text2')
        lf = self._panel(main, 'Журнал', None, dict(fill='both', expand=True, padx=26, pady=(0, 22)), pad=(4, 0, 4, 4))
        self.log = tk.Text(lf, height=7, wrap='word', state='disabled', font=('Consolas', 10))
        self.log.pack(fill='both', expand=True)
        self.show('p1'); self.apply_theme()
        keys = crs.systems()
        self.say('Системи: ' + (', '.join(keys) if keys else 'немає (crs_keys.json)') + '. МСК-46 ↔ УСК-2000 — точно (одна основа, EPSG). СК-63 — лише з офіційним ключем.')
        if not os.path.exists(self.trp): self.say('УВАГА: файл транслятора не знайдено: %s' % self.trp)
        self.after(100, self._pump); self.after(3000, self._watch); self.after(2500, self._auto_update)

    # ---------- каркас: реєстр кольорів, панелі, рейка ----------
    def _reg(self, w, bg, fg=None):
        self._regs.append((w, bg, fg))

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
        row = tk.Frame(self.rail, height=int(40 * self._s), cursor='hand2'); row.pack(fill='x', padx=10, pady=1); row.pack_propagate(False)
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
        st.configure('Seg.TFrame', background=P['seg'])
        st.configure('TLabel', background=P['card'], foreground=P['text'])
        st.configure('Hint.TLabel', background=P['card'], foreground=P['text2'])
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
        btn('Seg.TButton', P['seg'], P['seg'], P['text2'], F, (12, 3))
        btn('SegOn.TButton', P['segon'], P['segon'], P['text'], FB, (12, 3))

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
        self.lb1.configure(bg=P['field'], fg=P['text'], selectbackground=P['accent'], selectforeground='#FFFFFF',
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
            if role.startswith('seg:'): col = P['text'] if role[4:] == self.mode else P['text2']
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

    def _bg(self, fn):
        def w():
            try: fn()
            except Exception as e:
                self.q.put('ПОМИЛКА: %s' % e); self.q.put(traceback.format_exc().splitlines()[-1])
        threading.Thread(target=w, daemon=True).start()

    # ---------- прогрес ----------
    def setp(self, v):
        v = max(0.0, min(100.0, v))
        def u(): self.pb['value'] = v; self.pct['text'] = '%d %%' % round(v)
        self.q.put(u)

    def _run(self, args, lo=0.0, hi=100.0, marks=None):
        """Запуск скрипта з прогресом: marks {підрядок у виводі: частка 0..1}; між мітками шкала повільно росте."""
        marks = marks or {}
        p = subprocess.Popen(py_cmd(args[0]) + args[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        state = {'f': 0.0, 'cap': min(marks.values()) if marks else 0.9}
        def creep():
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
