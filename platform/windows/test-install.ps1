# SPDX-License-Identifier: MPL-2.0
#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if ($env:GITHUB_ACTIONS -ne 'true' -or !$env:RUNNER_TEMP -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'Run this real HKCU PATH smoke on a disposable GitHub-hosted Windows runner.'
}
. (Join-Path $PSScriptRoot 'common.ps1')

function Assert-Smoke([bool] $Condition, [string] $Message) {
    if (!$Condition) { throw $Message }
}

function Invoke-TestInstall([string] $Script, [string] $ExpectedError = '') {
    $lines = [Collections.Generic.List[string]]::new()
    $failure = ''
    try { & $Script 6>&1 | ForEach-Object { $lines.Add($_.ToString()) } }
    catch { $failure = $_.Exception.Message }
    $percentages = @(
        foreach ($line in $lines) {
            Write-Host $line
            if ($line -match '^\[.*\] ([0-9]{1,3})% ') { [int] $Matches[1] }
        }
    )
    Assert-Smoke ($percentages.Count -gt 0 -and $percentages[0] -eq 0) 'Installer did not start progress at 0%.'
    for ($index = 1; $index -lt $percentages.Count; $index++) {
        Assert-Smoke ($percentages[$index] -ge $percentages[$index - 1]) 'Installer progress decreased.'
    }
    if ($ExpectedError) {
        Assert-Smoke ($failure -like "*$ExpectedError*") "Expected installer error '$ExpectedError', got '$failure'."
        Assert-Smoke (100 -notin $percentages) 'A failed install printed 100%.'
    } else {
        Assert-Smoke (!$failure) "Unexpected installer failure: $failure"
        Assert-Smoke (
            $percentages[-1] -eq 100 -and
            @($percentages | Where-Object { $_ -eq 100 }).Count -eq 1 -and
            95 -in $percentages
        ) 'Completion must follow verification and be printed exactly once.'
    }
    return $lines
}

function Assert-UninstallRefused([string] $Script, [string] $ExpectedError) {
    $failure = ''
    try { & $Script } catch { $failure = $_.Exception.Message }
    Assert-Smoke ($failure -like "*$ExpectedError*") "Unsafe uninstall was not refused: $failure"
}

$runnerTemp = [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\')
$sandbox = Join-Path $runnerTemp ('corinthos-install-' + [guid]::NewGuid().ToString('N'))
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$source = Join-Path $sandbox 'source checkout'
$other = Join-Path $sandbox 'unrelated workspace'
$originalLocal = $env:LOCALAPPDATA
$originalProcessPath = $env:PATH
$originalLocation = Get-Location
$key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
$originalUserPath = Get-UserPath $key
$env:LOCALAPPDATA = Join-Path $sandbox 'local'
$systemPath = "$env:SystemRoot\System32"
$env:PATH = $systemPath
$pathFixture = '%SystemRoot%\System32;C:\corinthos-smoke-unrelated'
try {
    $paths = Get-CorinthosPaths
    foreach ($directory in @($source, $other)) {
        [void] [IO.Directory]::CreateDirectory($directory)
    }
    foreach ($name in @('install.ps1', 'uninstall.ps1', 'platform', 'src', 'LICENSE')) {
        Copy-Item -LiteralPath (Join-Path $repo $name) -Destination $source -Recurse
    }
    $key.SetValue('Path', $pathFixture, [Microsoft.Win32.RegistryValueKind]::ExpandString)
    Assert-Smoke (!$(
        Get-Command -Name @('python.exe', 'py.exe', 'pip.exe', 'codex.exe', 'claude.exe') -ErrorAction SilentlyContinue
    )) 'Smoke PATH must exclude system Python and providers.'
    Set-Location -LiteralPath $other
    $null = Invoke-TestInstall (Join-Path $source 'install.ps1')
    $expectedPath = "$($paths.Bin);$pathFixture"
    Assert-Smoke ((Get-UserPath $key).Text -ceq $expectedPath) 'Install did not add only the owned user PATH entry.'
    Assert-Smoke ((Get-UserPath $key).Kind -eq [Microsoft.Win32.RegistryValueKind]::ExpandString) 'Install changed PATH registry type.'
    Assert-Smoke ((Read-InstallManifest $paths.Install).state -ceq 'installed') 'Expected a verified installed manifest.'
    $providers = Get-Content -LiteralPath (Join-Path $paths.State 'providers.json') -Raw | ConvertFrom-Json
    Assert-Smoke (!$providers.providers.codex.observed.available -and !$providers.providers.claude.observed.available) 'Absent providers should be recorded as unavailable.'

    $movedSource = Join-Path $sandbox 'moved source'
    [IO.Directory]::Move($source, $movedSource)
    $env:PATH = [Environment]::ExpandEnvironmentVariables((Get-UserPath $key).Text) + ";$systemPath"
    Assert-Smoke ((Get-Command corinthos).Source -eq (Join-Path $paths.Bin 'corinthos.exe')) 'Command did not resolve through the persisted user PATH.'
    $version = & corinthos --version
    Assert-Smoke ($LASTEXITCODE -eq 0 -and $version -like 'corinthos *') 'Installed command failed after the checkout moved.'
    $homeOutput = '0' | & corinthos
    Assert-Smoke ($LASTEXITCODE -eq 0 -and 'CORINTHOS' -in $homeOutput) 'The command did not forward stdin and stdout to Home.'
    $errorOutput = & {
        $ErrorActionPreference = 'Continue'
        & corinthos --installer-smoke-invalid-option 2>&1
    }
    Assert-Smoke ($LASTEXITCODE -eq 2 -and ($errorOutput -join [Environment]::NewLine) -match 'unrecognized arguments') 'The command did not forward stderr and the CLI exit code.'

    $projects = @('Project A & notes', 'Project B')
    foreach ($name in $projects) {
        $root = Join-Path $other $name
        [void] [IO.Directory]::CreateDirectory($root)
        $null = & corinthos init $root
        Assert-Smoke ($LASTEXITCODE -eq 0 -and [IO.File]::Exists((Join-Path $root '.corinthos\bootstrap.json'))) 'One installed command failed to initialize an independent project.'
        Assert-Smoke (![IO.Directory]::Exists((Join-Path $root '.venv'))) 'Project initialization created a private project venv.'
        Set-Location -LiteralPath $root
        $null = @('0', '0') | & corinthos .
        Assert-Smoke ($LASTEXITCODE -eq 0) 'Installed command failed to open an existing project.'
    }
    Set-Location -LiteralPath $other
    $recent = Join-Path $paths.State 'recent-projects.json'
    Assert-Smoke ((Get-Content -LiteralPath $recent -Raw | ConvertFrom-Json).projects.Count -eq 2) 'Installed Home did not record both projects.'
    $config = Join-Path $paths.State 'config.json'
    $configHash = (Get-FileHash -LiteralPath $config).Hash
    $recentHash = (Get-FileHash -LiteralPath $recent).Hash

    $installer = Join-Path $movedSource 'install.ps1'
    $key.SetValue('Path', "$expectedPath;$($paths.Bin)\", [Microsoft.Win32.RegistryValueKind]::ExpandString)
    $reinstall = Invoke-TestInstall $installer
    Assert-Smoke (!($reinstall -match 'Downloading ')) 'Reinstall did not reuse the verified cache.'
    Assert-Smoke ((Get-UserPath $key).Text -ceq $expectedPath) 'Reinstall did not deduplicate the owned PATH.'
    Assert-Smoke ((Get-FileHash -LiteralPath $config).Hash -ceq $configHash -and (Get-FileHash -LiteralPath $recent).Hash -ceq $recentHash) 'Reinstall changed compatible user settings or recent projects.'

    $manifest = Get-Content -LiteralPath (Join-Path $movedSource 'platform\windows\artifacts.json') -Raw | ConvertFrom-Json
    foreach ($pin in @($manifest.python, $manifest.wheels[0])) {
        $artifact = Join-Path $paths.Cache $pin.filename
        $goodBytes = [IO.File]::ReadAllBytes($artifact)
        $badBytes = [byte[]] $goodBytes.Clone()
        $badBytes[0] = $badBytes[0] -bxor 1
        try {
            [IO.File]::WriteAllBytes($artifact, $badBytes)
            $null = Invoke-TestInstall $installer 'Cached artifact SHA-256 verification failed'
            Assert-Smoke ((Read-InstallManifest $paths.Install).state -ceq 'installed') 'A corrupt artifact displaced the previous installation.'
        } finally { [IO.File]::WriteAllBytes($artifact, $goodBytes) }
    }
    $entrypoint = Join-Path $movedSource 'src\corinthos\__main__.py'
    [IO.File]::WriteAllText($entrypoint, @'
import sys
from corinthos.cli import main
if sys.argv[1:] == ['adapters', 'refresh']:
    raise SystemExit(77)
raise SystemExit(main())
'@)
    $installedEntrypoint = Join-Path $paths.Install 'app\corinthos\__main__.py'
    $healthyHash = (Get-FileHash -LiteralPath $installedEntrypoint).Hash
    $null = Invoke-TestInstall $installer 'Private Python check failed (exit 77)'
    Assert-Smoke ((Get-FileHash -LiteralPath $installedEntrypoint).Hash -ceq $healthyHash) 'Post-swap health failure did not restore the previous installation.'
    Assert-Smoke ((Get-UserPath $key).Text -ceq $expectedPath) 'Post-swap health failure modified PATH.'
    Assert-Smoke ((& corinthos --version) -ceq $version -and $LASTEXITCODE -eq 0) 'Rollback did not restore a working command.'

    $uninstaller = Join-Path $paths.Install 'uninstall.ps1'
    $unrelatedFile = Join-Path $paths.Install 'owner-notes.txt'
    [IO.File]::WriteAllText($unrelatedFile, 'preserve')
    Assert-UninstallRefused $uninstaller 'entries outside their Corinthos inventory'
    Assert-Smoke ([IO.File]::ReadAllText($unrelatedFile) -ceq 'preserve') 'Uninstall changed an unrelated file.'
    [IO.File]::Delete($unrelatedFile)
    $embeddedProject = Join-Path $paths.Install 'project\.corinthos'
    [void] [IO.Directory]::CreateDirectory($embeddedProject)
    $projectFile = Join-Path $embeddedProject 'state.db'
    [IO.File]::WriteAllText($projectFile, 'project state')
    $null = Invoke-TestInstall $installer 'project exists inside the installation'
    Assert-UninstallRefused $uninstaller 'project exists inside the installation'
    Assert-Smoke ([IO.File]::ReadAllText($projectFile) -ceq 'project state') 'Uninstall changed nested project state.'
    Assert-Smoke ((Get-UserPath $key).Text -ceq $expectedPath) 'Refused uninstall changed PATH.'
    [IO.Directory]::Move((Join-Path $paths.Install 'project'), (Join-Path $other 'preserved project'))

    & $uninstaller
    Assert-Smoke (![IO.Directory]::Exists($paths.Install)) 'Uninstall left the installed application.'
    Assert-Smoke ((Get-UserPath $key).Text -ceq $pathFixture) 'Uninstall changed unrelated PATH entries.'
    foreach ($name in $projects) {
        Assert-Smoke ([IO.File]::Exists((Join-Path (Join-Path $other $name) '.corinthos\bootstrap.json'))) 'Uninstall removed project state.'
    }
    Assert-Smoke ((Get-FileHash -LiteralPath $config).Hash -ceq $configHash -and (Get-FileHash -LiteralPath $recent).Hash -ceq $recentHash) 'Uninstall removed or changed global user state.'
    Write-Host 'Fresh install, PATH, no-system-Python command, project isolation, cache, rollback and uninstall smoke passed.'
} finally {
    try { Restore-UserPath $key $originalUserPath; Send-UserPathChange }
    finally {
        $key.Dispose()
        $env:LOCALAPPDATA = $originalLocal
        $env:PATH = $originalProcessPath
        Set-Location -LiteralPath $originalLocation.Path
        Remove-SetupTree $sandbox $runnerTemp
    }
}
