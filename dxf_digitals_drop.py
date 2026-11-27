"""Обгортка для ярлика «DXF для Digitals.bat»: перетягнути на ярлик один чи кілька DXF з Archicad.
Топо DMF шукає сама: від папки DXF угору (до 5 рівнів) — спершу ВД\\Топо\\*.dmf, потім ВД\\**\\*.dmf.
Кілька DMF — питає номер. Далі викликає dxf_digitals.py. Створено 27.11.2026."""
import sys, os, glob, subprocess
if sys.stdout: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))

def find_dmf(dxf):
    d = os.path.dirname(os.path.abspath(dxf))
    for _ in range(6):
        for pat in (('ВД', 'Топо', '*.dmf'), ('ВД', '**', '*.dmf')):
            found = sorted(set(glob.glob(os.path.join(d, *pat), recursive=True)))
            if found: return found
        nd = os.path.dirname(d)
        if nd == d: break
        d = nd
    return []

def choose(dxf):
    found = find_dmf(dxf)
    if len(found) == 1: return found[0]
    if not found:
        print('Топо DMF не знайдено поруч з об\'єктом (шукав ВД\\Топо\\*.dmf).')
        p = input('Вставте повний шлях до топо DMF (або Enter — пропустити): ').strip().strip('"')
        return p or None
    print('Знайдено кілька топо DMF:')
    for i, f in enumerate(found, 1): print('  %d. %s' % (i, f))
    while True:
        a = input('Номер потрібного (Enter — пропустити): ').strip()
        if not a: return None
        if a.isdigit() and 1 <= int(a) <= len(found): return found[int(a) - 1]

if __name__ == '__main__':
    files = [f for f in sys.argv[1:] if f.lower().endswith('.dxf') and 'Digitals' not in os.path.basename(f)]
    if not files:
        print('Перетягніть на ярлик DXF, експортований з Archicad (транслятор «07 Для Digitals (МСК)»).')
    for f in files:
        print('\n=== %s' % f)
        dmf = choose(f)
        if not dmf: print('Пропущено.'); continue
        print('Топо: %s' % dmf)
        r = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'dxf_digitals.py'), f, dmf])
        print('ГОТОВО' if r.returncode == 0 else 'НЕ ВИЙШЛО — файл не записано (див. повідомлення вище)')
    input('\nНатисніть Enter, щоб закрити…')
