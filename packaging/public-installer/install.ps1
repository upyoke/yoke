# Native bootstrap; install.py owns product policy and setup.
$ErrorActionPreference = 'Stop'
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    throw 'installer_language_mode: PowerShell is constrained. Install uv with winget install --id astral-sh.uv -e, download https://api.upyoke.com/dist/install.py with Invoke-WebRequest -OutFile install.py, then run uv run --isolated --no-project --python 3.12 python install.py. If application control blocks Python, ask your administrator to allow it.'
}
$installerArgs = @($args)
$origin = 'https://api.upyoke.com'
if ($env:YOKE_INSTALL_BASE_URL) { $origin = $env:YOKE_INSTALL_BASE_URL.TrimEnd('/') }
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('yoke-install-' + [guid]::NewGuid())
try {
    New-Item -ItemType Directory -Path $temporary | Out-Null
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        if ($installerArgs -contains '--dry-run') {
            throw 'uv_missing_for_dry_run: install uv with winget install --id astral-sh.uv -e, open a new terminal, and retry --dry-run.'
        }
        $uvInstaller = Join-Path $temporary 'uv.ps1'
        Invoke-WebRequest -UseBasicParsing 'https://astral.sh/uv/install.ps1' -OutFile $uvInstaller -TimeoutSec 120
        & $uvInstaller
        $env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'User') + ';' + $env:PATH
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            throw 'uv_bootstrap_failed: install uv with winget install --id astral-sh.uv -e, open a new terminal, and rerun the installer.'
        }
    }
    $helper = Join-Path $temporary 'install.py'
    Invoke-WebRequest -UseBasicParsing "$origin/dist/install.py" -OutFile $helper -TimeoutSec 120
    & uv run --isolated --no-project --python 3.12 python $helper @installerArgs
    if ($LASTEXITCODE -ne 0) { throw "yoke_install_failed: Python installer exited $LASTEXITCODE; follow its recovery above, then retry." }
    $env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'User') + ';' + $env:PATH
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
