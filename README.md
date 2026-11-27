# URBAN

Настільна програма для Windows (Python + tkinter), яка готує файли між Archicad і Digitals.

| Розділ | Що робить |
|---|---|
| Archicad DXF → Digitals | DXF з плану поверху Archicad автоматично прив'язує до топо DMF і пише DXF R12 з шарами й кольорами для Digitals |
| DMF → DXF | конвертує DMF Digitals у DXF R12 (+ CSV семантики, пікети, опційний зсув до локального нуля) |
| Ключ за пунктами | перехід між системами координат за спільними пунктами (Гельмерт 2D / афінне), нев'язки, СКП |
| Транслятор Archicad | інструкція підключення транслятора «07 Для Digitals (МСК)» |

## Запуск

```powershell
pythonw dpt_converter.py
```

Потрібні Python 3.12, `numpy`, `Pillow`.

Окремі скрипти:

```powershell
python dmf2dxf.py topo.dmf topo.dxf [--shift X Y]
python dxf_digitals.py export.dxf topo.dmf [out.dxf]
```

## Інсталятор

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

Потрібні PyInstaller і Inno Setup 6. Інсталятор ставить програму в `%LOCALAPPDATA%\Programs\URBAN` без прав адміністратора.

## Файли

- `dpt_converter.py` — GUI; `ui_icons.py` — іконки
- `dxf_digitals.py`, `dxf_digitals_drop.py` — прив'язка DXF до топо, запис R12
- `dmf2dxf.py` — DMF → DXF
- `crs.py`, `crs_keys.json` — системи координат (TM, Гельмерт, підгонка за пунктами)
- `assets/` — лого, `installer/` — збирання

Правила роботи — `CLAUDE.md` (= `AGENTS.md`), стан задач — `TODO.md`, навігація — `Markdown/agentic_context/`, передача — `Markdown/urban_handoff_2026-11-27.md`.
