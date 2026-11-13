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

function Invoke-DesktopFixture([string] $Stage) {
    $receipt = Join-Path $root "desktop-$Stage.txt"
    $env:CORINTHOS_DESKTOP_SMOKE_PROJECT = $project
    $env:CORINTHOS_DESKTOP_SMOKE_RECEIPT = $receipt
    $env:CORINTHOS_DESKTOP_SMOKE_START = if ($Stage -eq 'sessions') { '1' } else { '0' }
    $script:desktopProcess = Start-Process -FilePath $desktopPath -WorkingDirectory $root -PassThru -WindowStyle Normal
    $deadline = [DateTime]::UtcNow.AddSeconds(150)
    while (![IO.File]::Exists($receipt) -and [DateTime]::UtcNow -lt $deadline) {
        if ($desktopProcess.HasExited) { throw 'The desktop exited before producing its WebView receipt.' }
        Start-Sleep -Milliseconds 250
    }
    Assert-Spike ([IO.File]::Exists($receipt)) 'The actual WebView did not produce a receipt.'
    $observation = [IO.File]::ReadAllText($receipt).Trim()
    Assert-Spike ($observation -ceq 'pass') "The actual WebView failed its $Stage DOM checks: $observation"

    if ($Stage -eq 'sessions') {
        $providerTree = @(Get-CimInstance Win32_Process -Filter "Name = 'codex.exe'" |
            Where-Object { $_.ExecutablePath -eq $explicitExe })
        Assert-Spike ($providerTree.Count -eq 2) 'Cancel and timeout should reap the two previous trees and leave one live provider with one child.'
    }
    Assert-Spike ($desktopProcess.CloseMainWindow()) 'Could not request desktop shutdown.'
    Assert-Spike ($desktopProcess.WaitForExit(22000) -and $desktopProcess.ExitCode -eq 0) 'Desktop shutdown did not complete.'
    $remaining = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'codex.exe'" |
        Where-Object { $_.ExecutablePath -eq $python -or $_.ExecutablePath -eq $explicitExe -or $_.ExecutablePath -eq $autoExe }
    Assert-Spike (!$remaining) 'Closing the desktop left an owned sidecar or fixture provider process running.'
    $desktopProcess.Dispose()
    $script:desktopProcess = $null
}


$parent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$root = Join-Path $parent ('corinthos-desktop-' + [Guid]::NewGuid().ToString('N'))
$originalLocal = $env:LOCALAPPDATA
$originalPath = $env:PATH
$originalOverride = $env:CORINTHOS_SIDECAR_PYTHON
$originalProject = $env:CORINTHOS_SIDECAR_TEST_PROJECT
$originalSmokeProject = $env:CORINTHOS_DESKTOP_SMOKE_PROJECT
$originalSmokeReceipt = $env:CORINTHOS_DESKTOP_SMOKE_RECEIPT
$originalSmokeStart = $env:CORINTHOS_DESKTOP_SMOKE_START
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

    $baseline = '5d913b7b18ef720f963e7614046a4062a4b2367f'
    $archive = Join-Path $work 'phase-two.zip'
    $legacy = Join-Path $work 'phase-two'
    git -C $repo archive --format=zip "--output=$archive" $baseline -- src/corinthos
    if ($LASTEXITCODE -ne 0) { throw 'The exact Phase 2 source is required for the desktop v7 fixture.' }
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $legacy)
    $legacySource = Join-Path $legacy 'src'
    $makeV7Path = Join-Path $work 'make_v7.py'
    $makeV7 = @'
import sqlite3, sys
from contextlib import closing
sys.path.insert(0, sys.argv[1])
from corinthos.contracts import ContractStore
from corinthos.contracts import store
from corinthos.work import WorkService
assert store._SCHEMA_VERSION == 7 and store.__file__.startswith(sys.argv[1])
work = WorkService(sys.argv[2])
item = work.create(
    scope_level="TASK",
    objective="Preserve this Work Item",
    acceptance_criteria=["Keep the existing Work Item state unchanged."],
)
work.transition(item.work_item_id, "ACTIVE")
database = ContractStore(sys.argv[2]).database_path
with closing(sqlite3.connect(database)) as connection:
    assert connection.execute("PRAGMA user_version").fetchone() == (7,)
    assert connection.execute("SELECT name FROM sqlite_schema WHERE name = 'agent_sessions'").fetchall() == []
'@
    [IO.File]::WriteAllText($makeV7Path, $makeV7)
    Invoke-PrivatePython $paths.Install @($makeV7Path, $legacySource, $project)
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
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;

internal static class Provider {
    private static int Main(string[] args) {
        if (args.Length == 1 && args[0] == "fixture-child") {
            Thread.Sleep(120000);
            return 0;
        }
        string log = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "probe.log");
        if (args.Length == 1 && args[0] == "--version") {
            File.AppendAllText(log, "--version" + Environment.NewLine);
            Console.WriteLine("codex-cli 9.8.7");
        } else if (Array.IndexOf(args, "--help") >= 0) {
            File.AppendAllText(log, String.Join(" ", args) + Environment.NewLine);
            Console.WriteLine("--sandbox read-only --json stdin SESSION_ID");
        } else {
            if (args.Length == 0 || args[0] != "exec" || Array.IndexOf(args, "--json") < 0) return 2;
            Console.In.ReadToEnd();
            File.AppendAllText(log, "launch" + Environment.NewLine);
            using (var child = Process.Start(new ProcessStartInfo {
                FileName = Assembly.GetExecutingAssembly().Location,
                Arguments = "fixture-child",
                UseShellExecute = false,
                CreateNoWindow = true,
            })) {
                Console.WriteLine("{\"type\":\"thread.started\",\"thread_id\":\"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa\"}");
                Console.WriteLine("{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"Deterministic session output\"}}");
                Console.Out.Flush();
                Thread.Sleep(120000);
            }
        }
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
    Assert-Spike ((Get-FileHash -LiteralPath $database).Hash -eq $databaseHash) 'Passive bridge migrated the v7 project.'
    Assert-Spike ((Get-FileHash -LiteralPath $recent).Hash -eq $recentHash) 'Passive bridge changed the v1 registry.'

    $fixture = @{
        version = 1
        providers = @{ codex = @{ executable = $explicitExe; observed = $null } }
    } | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($registry, $fixture)
    $registryHash = (Get-FileHash -LiteralPath $registry).Hash
    $env:CORINTHOS_SIDECAR_PYTHON = $null
    Invoke-DesktopFixture 'passive'
    Assert-Spike (![IO.File]::Exists($autoLog) -and ![IO.File]::Exists($configuredLog)) 'Passive Agents rendering launched a provider.'
    Assert-Spike ((Get-FileHash -LiteralPath $registry).Hash -eq $registryHash) 'Passive Agents rendering rewrote provider state.'
    Write-Host 'Desktop WebView displayed the RPC v2 handshake, registry, migrated v8 project and passive Agents view without native probes.'

    Invoke-DesktopFixture 'sessions'
    Assert-Spike (![IO.File]::Exists($autoLog) -and [IO.File]::Exists($configuredLog)) 'Explicit sessions did not select only the configured provider.'
    Assert-Spike (@([IO.File]::ReadAllLines($configuredLog) | Where-Object { $_ -eq 'launch' }).Count -eq 3) 'Expected exactly three supervised native invocations.'
    Assert-Spike ((Get-FileHash -LiteralPath $registry).Hash -eq $registryHash) 'Starting sessions rewrote the configured provider registry.'
    Assert-Spike ((Get-FileHash -LiteralPath $profile).Hash -eq $profileHash) 'Desktop changed the project bootstrap.'
    Write-Host 'Actual WebView started three deterministic sessions, verified output, cancelled one and let one time out, then closed with an active provider. Sidecar and all fixture provider trees were reaped.'


    $savedRegistry = Get-Content -Raw -LiteralPath $recent | ConvertFrom-Json
    Assert-Spike ($savedRegistry.version -eq 2 -and $savedRegistry.projects.Count -eq 2 -and $savedRegistry.projects[0].root -eq $project) 'Explicit project open lost legacy registry entries.'
    $backups = @(Get-ChildItem -File -LiteralPath (Split-Path $database) -Filter 'state.pre-v8-*.db')
    Assert-Spike ($backups.Count -eq 1) 'Explicit project open did not preserve exactly one v7 backup.'
    $checkMigrationPath = Join-Path $work 'check_migration.py'
    $checkMigration = @'
import sqlite3, sys
from contextlib import closing
from pathlib import Path

def inspect(database):
    with closing(sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True)) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        work = db.execute("SELECT * FROM work_items").fetchall()
        assert db.execute("SELECT objective, status FROM work_items").fetchall() == [
            ("Preserve this Work Item", "ACTIVE")
        ]
        if version == 8:
            states = db.execute(
                "SELECT session_id, state FROM agent_sessions ORDER BY created_at, session_id"
            ).fetchall()
            assert [state for _, state in states] == ["CANCELLED", "TIMED_OUT", "INTERRUPTED"], states
            for session_id, state in states:
                kinds = db.execute(
                    "SELECT kind FROM agent_session_events WHERE session_id = ?", (session_id,)
                ).fetchall()
                assert ("OUTPUT",) in kinds and (state,) in kinds, (state, kinds)
        return version, work

current, backup = map(inspect, sys.argv[1:])
assert current[0] == 8 and backup[0] == 7
assert current[1] == backup[1]
'@
    [IO.File]::WriteAllText($checkMigrationPath, $checkMigration)
    Invoke-PrivatePython $paths.Install @($checkMigrationPath, $database, $backups[0].FullName)

    $prior = [IO.File]::ReadAllLines($configuredLog).Length
    $null = Invoke-PrivatePython $paths.Install @('-m','corinthos','adapters','refresh')
    Assert-Spike ([IO.File]::Exists($configuredLog) -and ![IO.File]::Exists($autoLog)) 'Explicit refresh did not select the configured provider.'
    $probeList = ([IO.File]::ReadAllLines($configuredLog) | Select-Object -Skip $prior) -join '|'
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
    $env:CORINTHOS_DESKTOP_SMOKE_START = $originalSmokeStart
    if ([IO.Directory]::Exists($root)) { Remove-SetupTree $root $parent }
}
