# Native bootstrap; install.py owns product policy and setup.
$ErrorActionPreference = 'Stop'
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') {
    throw 'installer_language_mode: PowerShell is constrained. Install uv with winget install --id astral-sh.uv -e, download https://api.upyoke.com/dist/install.py with Invoke-WebRequest -OutFile install.py, then run uv run --isolated --no-project --python 3.12 python install.py. If application control blocks Python, ask your administrator to allow it.'
}
$installerArgs = @($args)
# Keep in step with the uv version CI pins in pyproject.toml.
$uvVersion = '0.12.1'
# Resolve the exact patch, as install.py does, so no step runs through uv's
# minor-version link: a junction that a profile reset can leave dangling.
$pythonRequest = '3.12'
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
        Invoke-WebRequest -UseBasicParsing "https://astral.sh/uv/$uvVersion/install.ps1" -OutFile $uvInstaller -TimeoutSec 120
        & $uvInstaller
        $env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'User') + ';' + $env:PATH
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            throw 'uv_bootstrap_failed: install uv with winget install --id astral-sh.uv -e, open a new terminal, and rerun the installer.'
        }
    }
    $helper = Join-Path $temporary 'install.py'
    Invoke-WebRequest -UseBasicParsing "$origin/dist/install.py" -OutFile $helper -TimeoutSec 120
    # Prepare the interpreter non-interactively so uv's output can be read;
    # the install below keeps the terminal for its prompts.
    $ErrorActionPreference = 'Continue'
    function Invoke-PreparationUv([string[]]$uvArgs) {
        $script:uvOutput = @(& uv @uvArgs 2>&1 | ForEach-Object { $line = "$_"; Write-Host $line; $line })
        $script:uvExit = $LASTEXITCODE
    }
    function Assert-PreparationUv([string]$step) {
        if ($script:uvExit -eq 0) { return }
        if (($script:uvOutput -join "`n") -match 'os error 448') {
            throw 'windows_untrusted_mount_point: uv could not follow the Python link directory it just created (os error 448, untrusted mount point). Windows Redirection Guard blocks this process from following directory junctions; OpenSSH sessions run under it. See https://github.com/astral-sh/uv/issues/19616. Run the installer from a local PowerShell window on this computer, not over SSH.'
        }
        throw "python_bootstrap_failed: uv exited $($script:uvExit) while $step; follow its message above, then retry."
    }
    $find = @('python', 'find', '--no-project', '--show-version', $pythonRequest)
    $found = @(& uv @find 2>$null | ForEach-Object { "$_".Trim() })
    if ($LASTEXITCODE -ne 0) {
        Invoke-PreparationUv @('python', 'install', $pythonRequest)
        Assert-PreparationUv "installing Python $pythonRequest"
        $found = @(& uv @find 2>$null | ForEach-Object { "$_".Trim() })
    }
    $pythonVersion = "$($found | Select-Object -Last 1)"
    if ($LASTEXITCODE -ne 0 -or $pythonVersion -notmatch '^\d+\.\d+\.\d+$') {
        throw "python_bootstrap_failed: uv could not name the exact Python $pythonRequest to install Yoke with. Run uv python find --show-version $pythonRequest to see why, then retry."
    }
    $pythonArgs = @('run', '--isolated', '--no-project', '--python', $pythonVersion, 'python')
    Invoke-PreparationUv ($pythonArgs + @('-c', 'pass'))
    Assert-PreparationUv "preparing Python $pythonVersion"
    # Judge install.py by its exit code: under 'Stop', Windows PowerShell 5.1
    # turns its first redirected stderr line (a warning) into a terminating error.
    & uv @pythonArgs $helper @installerArgs
    if ($LASTEXITCODE -ne 0) { throw "yoke_install_failed: Python installer exited $LASTEXITCODE; follow its recovery above, then retry." }
    $ErrorActionPreference = 'Stop'
    $env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'User') + ';' + $env:PATH
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
