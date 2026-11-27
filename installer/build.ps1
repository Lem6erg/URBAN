# Збирання інсталятора URBAN: PyInstaller (exe без Python) → Inno Setup → G:\URBAN\Документація\URBAN_Setup.exe
# Потрібні: python з numpy, Pillow, pyinstaller; Inno Setup 6 (ISCC.exe). Створено 27.11.2026 (CLAUDE).
# Код — G:\URBAN\URBAN [app] (перенесено з CLAUDE\tools 27.11.2026); шляхи відносні до цієї папки.
$ErrorActionPreference = 'Stop'
$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$tools = Split-Path -Parent $here
$work  = Join-Path $env:TEMP 'URBAN_build'
python -I (Join-Path $here 'make_assets.py')
python -m PyInstaller --noconfirm --clean --windowed --name URBAN `
  --icon (Join-Path $tools 'assets\urban.ico') `
  --distpath (Join-Path $work 'dist') --workpath (Join-Path $work 'build') --specpath $work `
  --add-data "$(Join-Path $tools 'dxf_digitals.py');." `
  --add-data "$(Join-Path $tools 'dmf2dxf.py');." `
  --add-data "$(Join-Path $tools 'crs_keys.json');." `
  --add-data "$(Join-Path $tools 'assets');assets" `
  --hidden-import numpy --hidden-import PIL.ImageTk `
  --exclude-module matplotlib --exclude-module scipy --exclude-module pandas `
  (Join-Path $tools 'dpt_converter.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller: помилка' }
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
& $iscc "/DDist=$(Join-Path $work 'dist\URBAN')" (Join-Path $here 'URBAN.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup: помилка' }
Get-Item 'G:\URBAN\Документація\URBAN_Setup.exe' | Select-Object Name, Length, LastWriteTime
