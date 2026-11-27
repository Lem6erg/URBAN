"""Картинки майстра встановлення з лого URBAN + BOM для .iss/.txt (Inno Setup читає UTF-8 лише з BOM)."""
import os
from PIL import Image
H = os.path.dirname(os.path.abspath(__file__)); A = os.path.join(H, '..', 'assets')
mark = Image.open(os.path.join(A, 'urban_mark.png')).convert('L')
def card(w, h, k):
    im = Image.new('RGB', (w, h), (0, 0, 0)); n = int(min(w, h) * k); m = mark.resize((n, n), Image.LANCZOS)
    im.paste((255, 255, 255), ((w - n) // 2, (h - n) // 2), m); return im
card(328, 628, 0.62).save(os.path.join(H, 'wizard_big.bmp'))    # 200 % від 164×314
card(110, 110, 0.80).save(os.path.join(H, 'wizard_small.bmp'))  # 200 % від 55×55
for f in ('URBAN.iss', 'Як підключити транслятор.txt', 'build.ps1'):
    p = os.path.join(H, f); b = open(p, 'rb').read()
    if not b.startswith(b'\xef\xbb\xbf'): open(p, 'wb').write(b'\xef\xbb\xbf' + b)
print('ok')
