# Випуск нової версії URBAN на GitHub (ТЗ Markdown/urban_autoupdate_spec.md, п. 3.6).
# Порядок: перевірки → тести → збирання → тег vX.Y.Z → push main і тегу → GitHub Release з інсталятором і SHA-256.
# Перед запуском: підняти VERSION у version.py, дописати розділ «## X.Y.Z — дата» у CHANGELOG.md, закомітити.
# Запуск: powershell -ExecutionPolicy Bypass -File installer\release.ps1   (-DryRun — лише перевірки й збирання)
param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
Set-Location -LiteralPath $root
$gh = @((Get-Command gh -ErrorAction SilentlyContinue).Source, "$env:ProgramFiles\GitHub CLI\gh.exe") | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $gh) { throw 'GitHub CLI (gh) не знайдено' }

$ver = (python -I -c "import sys; sys.path.insert(0, sys.argv[1]); import version; print(version.VERSION)" $root).Trim()
$tag = "v$ver"
Write-Host "Випуск URBAN $ver ($tag)"

# 1. Перевірки
if (git status --porcelain) { throw 'Є незакомічені зміни — спершу коміт' }
if ((git rev-parse --abbrev-ref HEAD).Trim() -ne 'main') { throw 'Випуск лише з гілки main' }
if (git tag --list $tag) { throw "Тег $tag уже існує — підніміть VERSION у version.py" }
if (git ls-remote --tags origin $tag) { throw "Тег $tag уже є на GitHub" }
$cl = [IO.File]::ReadAllText((Join-Path $root 'CHANGELOG.md'), [Text.Encoding]::UTF8) -replace "`r", ''
$m = [regex]::Match($cl, "(?ms)^## $([regex]::Escape($ver))\b[^\n]*\n(.*?)(?=^## |\z)")
if (-not $m.Success -or -not $m.Groups[1].Value.Trim()) { throw "У CHANGELOG.md немає розділу «## $ver»" }
$notes = $m.Groups[1].Value.Trim()
& $gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'gh не увійшов у GitHub: gh auth login --web' }

# 2. Тести
python -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw 'Тести не пройшли — випуск зупинено' }

# 3. Збирання (інсталятор і .sha256 — у G:\URBAN\Документація, як і для локального користувача)
$out = 'G:\URBAN\Документація'
& powershell -ExecutionPolicy Bypass -File (Join-Path $here 'build.ps1') -OutDir $out
if ($LASTEXITCODE -ne 0) { throw 'Збирання не вдалося' }
$setup = Join-Path $out 'URBAN_Setup.exe'
if ($DryRun) { Write-Host "DryRun: зібрано $setup; тег і випуск не створено"; exit 0 }

# 4. Тег і push
git tag -a $tag -m "URBAN $ver"
git push origin main
git push origin $tag

# 5. GitHub Release
$nf = Join-Path $env:TEMP "URBAN_notes_$ver.md"
[IO.File]::WriteAllText($nf, $notes, (New-Object Text.UTF8Encoding $false))
& $gh release create $tag $setup "$setup.sha256" --repo Lem6erg/URBAN --title "URBAN $ver" --notes-file $nf
if ($LASTEXITCODE -ne 0) { throw 'gh release create: помилка' }
Remove-Item -LiteralPath $nf
Write-Host "ГОТОВО: https://github.com/Lem6erg/URBAN/releases/tag/$tag"
