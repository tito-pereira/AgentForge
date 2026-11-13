# SPDX-License-Identifier: MPL-2.0
#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Desktop
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
. (Join-Path $repo 'platform\windows\common.ps1')
. (Join-Path $repo 'platform\windows\distribution.ps1')

function Assert-Spike([bool] $Condition, [string] $Message) {
    if (!$Condition) { throw $Message }
}

$parent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$root = Join-Path $parent ('corinthos-desktop-' + [Guid]::NewGuid().ToString('N'))
$originalLocal = $env:LOCALAPPDATA
$originalPath = $env:PATH
$originalOverride = $env:CORINTHOS_SIDECAR_PYTHON
$originalProject = $env:CORINTHOS_SIDECAR_TEST_PROJECT
$originalSmokeProject = $env:CORINTHOS_DESKTOP_SMOKE_PROJECT
$originalSmokeReceipt = $env:CORINTHOS_DESKTOP_SMOKE_RECEIPT
$desktopProcess = $null
try {
    $desktopPath = (Resolve-Path -LiteralPath $Desktop).Path
    $env:LOCALAPPDATA = Join-Path $root 'local'
    $paths = Get-CorinthosPaths
    $work = Join-Path $root 'staging'
    foreach ($directory in @($work, $paths.Cache, $paths.Programs)) {
        [void] [IO.Directory]::CreateDirectory($directory)
    }
    $script:InstallPercent = 0
    $candidate = New-InstallCandidate $repo $paths $work (Get-LauncherCompiler)
    $null = Test-InstallCandidate $candidate
    [IO.Directory]::Move($candidate, $paths.Install)
    $python = Join-Path $paths.Install 'runtime\python.exe'
    Invoke-PrivatePython $paths.Install @('-m', 'corinthos.user_state')

    $project = Join-Path $root 'project'
    $null = Invoke-PrivatePython $paths.Install @('-m', 'corinthos', 'init', $project)
    $profile = Join-Path $project '.corinthos\bootstrap.json'
    $profileHash = (Get-FileHash -LiteralPath $profile).Hash
    $recent = Join-Path $paths.State 'recent-projects.json'
    $missing = Join-Path $root 'missing-project'
    $legacyRegistry = @{
        version = 1
        projects = @(
            @{ path = $project; last_opened_at = '2026-01-02T00:00:00Z' }
            @{ path = $missing; last_opened_at = '2026-01-01T00:00:00Z' }
        )
    } | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($recent, $legacyRegistry)
    $recentHash = (Get-FileHash -LiteralPath $recent).Hash

    $baseline = '377bbcb9f842a6472e393465119e3467dd9cb65f'
    $archive = Join-Path $work 'phase-one.zip'
    $legacy = Join-Path $work 'phase-one'
    git -C $repo archive --format=zip "--output=$archive" $baseline -- src/corinthos
    if ($LASTEXITCODE -ne 0) { throw 'The exact Phase 1 source is required for the desktop v6 fixture.' }
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $legacy)
    $legacySource = Join-Path $legacy 'src'
    $makeV6Path = Join-Path $work 'make_v6.py'
    $makeV6 = @'
import sqlite3, sys
from contextlib import closing
sys.path.insert(0, sys.argv[1])
from corinthos.contracts import ContractStore
from corinthos.contracts import store
assert store._SCHEMA_VERSION == 6 and store.__file__.startswith(sys.argv[1])
database = ContractStore(sys.argv[2]).database_path
with closing(sqlite3.connect(database)) as connection:
    assert connection.execute("PRAGMA user_version").fetchone() == (6,)
    assert not connection.execute(
        "SELECT name FROM sqlite_schema WHERE name = 'work_items'"
    ).fetchall()
'@
    [IO.File]::WriteAllText($makeV6Path, $makeV6)
    Invoke-PrivatePython $paths.Install @($makeV6Path, $legacySource, $project)
    $database = Join-Path $project '.corinthos\state.db'
    $databaseHash = (Get-FileHash -LiteralPath $database).Hash

    $providers = Join-Path $root 'providers'
    $configured = Join-Path $root 'configured'
    foreach ($directory in @($providers, $configured)) {
        [void] [IO.Directory]::CreateDirectory($directory)
    }
    $sentinelSource = Join-Path $root 'provider.cs'
    [IO.File]::WriteAllText($sentinelSource, @'
using System;
using System.IO;
internal static class Provider {
    private static int Main(string[] args) {
        File.AppendAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "probe.log"),
            String.Join(" ", args) + Environment.NewLine);
        if (args.Length == 1 && args[0] == "--version") Console.WriteLine("codex-cli 9.8.7");
        else Console.WriteLine("--sandbox read-only --json stdin SESSION_ID");
        return 0;
    }
}
'@)
    $autoExe = Join-Path $providers 'codex.exe'
    $explicitExe = Join-Path $configured 'codex.exe'
    & (Get-LauncherCompiler) /nologo /target:exe /platform:x64 "/out:$autoExe" $sentinelSource
    if ($LASTEXITCODE -ne 0) { throw 'Could not compile the synthetic provider.' }
    [IO.File]::Copy($autoExe, $explicitExe)
    $autoLog = Join-Path $providers 'probe.log'
    $configuredLog = Join-Path $configured 'probe.log'
    $env:PATH = "$providers;$originalPath"
    $registry = Join-Path $paths.State 'providers.json'
    $manifest = Join-Path $repo 'apps\desktop\src-tauri\Cargo.toml'
    $env:CORINTHOS_SIDECAR_PYTHON = $null
    $env:CORINTHOS_SIDECAR_TEST_PROJECT = $project
    cargo test --manifest-path $manifest --locked --no-default-features private_runtime_repeated_cycles -- --ignored --nocapture
    if ($LASTEXITCODE -ne 0) { throw 'Private runtime lifecycle integration failed.' }
    Assert-Spike (![IO.File]::Exists($registry) -and ![IO.File]::Exists($autoLog)) 'Passive bridge started a PATH provider or wrote its registry.'
    Assert-Spike ((Get-FileHash -LiteralPath $database).Hash -eq $databaseHash) 'Passive bridge migrated the v6 project.'
    Assert-Spike ((Get-FileHash -LiteralPath $recent).Hash -eq $recentHash) 'Passive bridge changed the v1 registry.'

    $fixture = @{
        version = 1
        providers = @{ codex = @{ executable = $explicitExe; observed = $null } }
    } | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($registry, $fixture)
    $registryHash = (Get-FileHash -LiteralPath $registry).Hash
    $env:CORINTHOS_SIDECAR_PYTHON = $null
    $receipt = Join-Path $root 'desktop-receipt.txt'
    $env:CORINTHOS_DESKTOP_SMOKE_PROJECT = $project
    $env:CORINTHOS_DESKTOP_SMOKE_RECEIPT = $receipt
    $desktopProcess = Start-Process -FilePath $desktopPath -WorkingDirectory $root -PassThru -WindowStyle Normal
    $deadline = [DateTime]::UtcNow.AddSeconds(100)
    while (![IO.File]::Exists($receipt) -and [DateTime]::UtcNow -lt $deadline) {
        if ($desktopProcess.HasExited) { throw 'The desktop exited before producing its WebView receipt.' }
        Start-Sleep -Milliseconds 250
    }
    Assert-Spike ([IO.File]::Exists($receipt)) 'The actual WebView did not produce a receipt.'
    $observation = [IO.File]::ReadAllText($receipt).Trim()
    Assert-Spike ($observation -ceq 'pass') "The actual WebView failed its DOM checks: $observation"
    Write-Host 'Desktop WebView displayed the RPC v2 handshake, the real registry, a migrated v7 project and real Work Item creation and status changes.'
    Assert-Spike ($desktopProcess.CloseMainWindow()) 'Could not request desktop shutdown.'
    Assert-Spike ($desktopProcess.WaitForExit(15000) -and $desktopProcess.ExitCode -eq 0) 'Desktop shutdown did not complete.'
    $remaining = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.ExecutablePath -eq $python }
    Assert-Spike (!$remaining) 'Closing the desktop left a private Python sidecar running.'
    Assert-Spike (![IO.File]::Exists($autoLog) -and ![IO.File]::Exists($configuredLog)) 'Passive desktop startup launched a provider.'
    Assert-Spike ((Get-FileHash -LiteralPath $registry).Hash -eq $registryHash) 'Passive desktop startup rewrote provider state.'
    Assert-Spike ((Get-FileHash -LiteralPath $profile).Hash -eq $profileHash) 'Desktop changed the project bootstrap.'
    $savedRegistry = Get-Content -Raw -LiteralPath $recent | ConvertFrom-Json
    Assert-Spike ($savedRegistry.version -eq 2 -and $savedRegistry.projects.Count -eq 2 -and $savedRegistry.projects[0].root -eq $project) 'Explicit project open lost legacy registry entries.'
    $backups = @(Get-ChildItem -File -LiteralPath (Split-Path $database) -Filter 'state.pre-v7-*.db')
    Assert-Spike ($backups.Count -eq 1) 'Explicit project open did not preserve exactly one v6 backup.'
    $checkMigrationPath = Join-Path $work 'check_migration.py'
    $checkMigration = @'
import sqlite3, sys
from contextlib import closing
from pathlib import Path
for expected, database in zip((7, 6), sys.argv[1:], strict=True):
    with closing(sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (expected,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        if expected == 7:
            assert connection.execute("SELECT objective, status FROM work_items").fetchall() == [
                ("Confirm desktop persistence", "ACTIVE")
            ]
'@
    [IO.File]::WriteAllText($checkMigrationPath, $checkMigration)
    Invoke-PrivatePython $paths.Install @($checkMigrationPath, $database, $backups[0].FullName)

    $null = Invoke-PrivatePython $paths.Install @('-m','corinthos','adapters','refresh')
    Assert-Spike ([IO.File]::Exists($configuredLog) -and ![IO.File]::Exists($autoLog)) 'Explicit refresh did not select the configured provider.'
    $probeList = [IO.File]::ReadAllLines($configuredLog) -join '|'
    Assert-Spike ($probeList -ceq '--version|--help|exec --help|exec resume --help') 'Unexpected native probe sequence.'
    Write-Host 'Private CPython 3.14.10 lifecycle, passive provider sentinels and explicit refresh passed.'
} finally {
    if ($desktopProcess) {
        if (!$desktopProcess.HasExited) {
            [void] $desktopProcess.CloseMainWindow()
            if (!$desktopProcess.WaitForExit(5000)) { Stop-Process -Id $desktopProcess.Id -ErrorAction SilentlyContinue }
        }
        $desktopProcess.Dispose()
    }
    $env:LOCALAPPDATA = $originalLocal
    $env:PATH = $originalPath
    $env:CORINTHOS_SIDECAR_PYTHON = $originalOverride
    $env:CORINTHOS_SIDECAR_TEST_PROJECT = $originalProject
    $env:CORINTHOS_DESKTOP_SMOKE_PROJECT = $originalSmokeProject
    $env:CORINTHOS_DESKTOP_SMOKE_RECEIPT = $originalSmokeReceipt
    if ([IO.Directory]::Exists($root)) { Remove-SetupTree $root $parent }
}
