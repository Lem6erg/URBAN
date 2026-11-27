# Збирання інсталятора URBAN: PyInstaller (exe без Python) → Inno Setup → URBAN_Setup.exe + URBAN_Setup.exe.sha256
# Потрібні: python з numpy, Pillow, pyinstaller; Inno Setup 6 (ISCC.exe). Створено 27.11.2026 (CLAUDE).
# Код — G:\URBAN\URBAN [app]; шляхи відносні до цієї папки. Версія — з version.py.
param([string]$OutDir = 'G:\URBAN\Документація')
$ErrorActionPreference = 'Stop'
$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$tools = Split-Path -Parent $here
$work  = Join-Path $env:TEMP 'URBAN_build'
$ver = (python -I -c "import sys; sys.path.insert(0, sys.argv[1]); import version; print(version.VERSION)" $tools).Trim()
if ($ver -notmatch '^\d+\.\d+\.\d+$') { throw "version.py: некоректна версія '$ver'" }
Write-Host "URBAN $ver"
python -I (Join-Path $here 'make_assets.py')
python -m PyInstaller --noconfirm --clean --windowed --name URBAN `
  --icon (Join-Path $tools 'assets\urban.ico') `
  --distpath (Join-Path $work 'dist') --workpath (Join-Path $work 'build') --specpath $work `
  --add-data "$(Join-Path $tools 'dxf_digitals.py');." `
  --add-data "$(Join-Path $tools 'dmf2dxf.py');." `
  --add-data "$(Join-Path $tools 'crs_keys.json');." `
  --add-data "$(Join-Path $tools 'CHANGELOG.md');." `
  --add-data "$(Join-Path $tools 'assets');assets" `
  --hidden-import numpy --hidden-import PIL.ImageTk `
  --exclude-module matplotlib --exclude-module scipy --exclude-module pandas `
  (Join-Path $tools 'dpt_converter.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller: помилка' }
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
& $iscc "/DDist=$(Join-Path $work 'dist\URBAN')" "/DAppVer=$ver" "/DOutDir=$OutDir" (Join-Path $here 'URBAN.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup: помилка' }
$setup = Join-Path $OutDir 'URBAN_Setup.exe'
$hash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$setup.sha256", "$hash  URBAN_Setup.exe`n", (New-Object Text.UTF8Encoding $false))
Get-Item -LiteralPath $setup, "$setup.sha256" | Select-Object Name, Length, LastWriteTime
