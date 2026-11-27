# URBAN — карта проєкту

Перевірено: 2026-11-27. Обсяг: існування наведених шляхів і призначення за кодом; не аудит усіх функцій.
Початок — [README](README.md), контракти — [джерела](sources.md), дії — [маршрути](task_routes.md).

## Області та відповідальність

| Область | Код | Перевірки / джерела |
|---|---|---|
| GUI: вкладки, тема, прогрес, меню | [dpt_converter](../../dpt_converter.py), [ui_icons](../../ui_icons.py), [assets](../../assets) | запуск GUI; [передача §1](../urban_handoff_2026-11-27.md) |
| Archicad DXF → Digitals (прив'язка ICP, R12, кольори шарів) | [dxf_digitals](../../dxf_digitals.py), [обгортка перетягування](../../dxf_digitals_drop.py) | тестове топо: ≥95 % вершин ≤ 1 мм; [передача §3](../urban_handoff_2026-11-27.md) |
| DMF → DXF (читання DMF v1.15, R12, CSV, пікети, зсув) | [dmf2dxf](../../dmf2dxf.py) | конвертація копії DMF у scratchpad; спільний із Кресляром ДПТ (`G:\URBAN\CLAUDE\07_DMF_to_Archicad.md`) |
| Системи координат (TM, Гельмерт 7 пар., підгонка 2D, автовизначення) | [crs](../../crs.py), [crs_keys.json](../../crs_keys.json), [приклад ключа](../../crs_keys.example.json) | МСК-46 → УСК-2000 на копії; [передача §3](../urban_handoff_2026-11-27.md) |
| Інсталятор (PyInstaller + Inno Setup) | [build.ps1](../../installer/build.ps1), [URBAN.iss](../../installer/URBAN.iss), [make_assets](../../installer/make_assets.py), [інструкція транслятора](<../../installer/Як підключити транслятор.txt>), [транслятор і шаблон пунктів](../../installer/files) | збирання → `G:\URBAN\Документація\URBAN_Setup.exe` + `.sha256` |
| Версії, оновлення, випуск | [version](../../version.py), [updater](../../updater.py), сторінка «Оновлення» в [dpt_converter](../../dpt_converter.py) (`_tab5`), [CHANGELOG](../../CHANGELOG.md), [release.ps1](../../installer/release.ps1) | [тести updater](../../tests/test_updater.py); [ТЗ оновлення](../urban_autoupdate_spec.md) |
| PDF → JPEG / TIFF (PDFium, 3 рівні якості, TIFF LZW / Ч/Б G4) | [pdf_raster](../../pdf_raster.py), сторінка `_tab6` у [dpt_converter](../../dpt_converter.py) | [тести](../../tests/test_pdf_raster.py); [ТЗ](../urban_pdf_raster_spec.md) |
| Локація (DXF/DWG → система → Google Maps; СК-63 наближено) | [site_map](../../site_map.py), [dwgread](../../dwgread/__init__.py), сторінка `_tab7`, перетягування `_dnd_setup` у [dpt_converter](../../dpt_converter.py) | [тести](../../tests/test_site_map.py); [ТЗ](../urban_site_map_spec.md) |
| Система ↔ WGS-84 (спільне), KML ↔ DXF, калькулятор координат | [geo](../../geo.py), [kml_dxf](../../kml_dxf.py), [coord_calc](../../coord_calc.py), сторінки `_tab8`, `_tab9` | [тести](../../tests/test_geo_tools.py); [ТЗ](../urban_geo_tools_spec.md) |
| Прив'язка растру, очищення метаданих | [raster_geo](../../raster_geo.py), [file_clean](../../file_clean.py), сторінки `_tab10`, `_tab11` | [тести](../../tests/test_geo_tools.py); [ТЗ](../urban_geo_tools_spec.md) |
| Перевірка ПЗ (DOCX), XML ДЗК → DXF, межа → KML і відстані ЦЗ (OSM/OSRM) | [pz_check](../../pz_check.py), [dzk_xml](../../dzk_xml.py), [cz_routes](../../cz_routes.py), сторінки `_tab13`, `_tab12`, панель «Межа і ЦЗ» у `_tab7` | [тести](../../tests/test_pz_cadastre_cz.py); [ТЗ](../urban_pz_cadastre_cz_spec.md) |
| Процеси: стартова сторінка, шкала кожного процесу на своїй сторінці | `_tab0`, `_bg`, `_job_start`/`_job_end`, `_bars`, `setp` у [dpt_converter](../../dpt_converter.py) | ручна перевірка GUI; [ТЗ](../urban_pz_cadastre_cz_spec.md) Р9 |

## Дані та межі доступу

| Що | Де | Доступ |
|---|---|---|
| Налаштування користувача (тема, ключі) | `%APPDATA%\URBAN\settings.json`, `%APPDATA%\URBAN\crs_keys.json` | читати; не скидати без дозволу |
| Встановлена програма | `%LOCALAPPDATA%\Programs\URBAN` | лише читати |
| Ярлики й транслятор | `G:\URBAN\Документація\` (`URBAN.bat`, `URBAN.lnk`, `DXF для Digitals.bat`, `07 Для Digitals (МСК).Xml`, `Пункти — шаблон.txt`) | міняти лише в задачі, що їх стосується |
| Дані об'єктів (DMF, DXF, PLN) | `G:\URBAN\<фірма>\<об'єкт>\` | лише читати; тест — на копії; у git — ніколи |
| Експеримент запису DMF | `dxf2dmf_exp\` (локально, поза git) | не працює в Digitals; не використовувати |
