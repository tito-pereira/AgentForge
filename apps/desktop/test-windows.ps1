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
    $recentHash = (Get-FileHash -LiteralPath $recent).Hash

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

    $fixture = @{
        version = 1
        providers = @{ codex = @{ executable = $explicitExe; observed = $null } }
    } | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($registry, $fixture)
    $registryHash = (Get-FileHash -LiteralPath $registry).Hash
    $env:CORINTHOS_SIDECAR_PYTHON = $null
    Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
    $desktopProcess = Start-Process -FilePath $desktopPath -WorkingDirectory $root -PassThru -WindowStyle Normal
    $automation = [Windows.Automation.AutomationElement]
    $subtree = [Windows.Automation.TreeScope]::Descendants
    $connected = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    do {
        Start-Sleep -Milliseconds 500
        $desktopProcess.Refresh()
        if ($desktopProcess.HasExited) { throw 'The desktop exited before reporting real backend state.' }
        if (!$desktopProcess.MainWindowHandle) { continue }
        $window = $automation::FromHandle($desktopProcess.MainWindowHandle)
        if (!$window) { continue }
        $nodes = $window.FindAll($subtree, [Windows.Automation.Condition]::TrueCondition)
        $names = @($nodes | ForEach-Object { $_.Current.Name })
        if ($names -match '0\.1\.0' -and $names -match '^v1$' -and
            $names -match '^Connected$' -and $names -match '^codex$' -and
            $names -match '^Not yet observed$') {
            $connected = $true
            break
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    Assert-Spike $connected 'Could not observe the real backend values in the desktop accessibility tree.'
    $edit = $nodes | Where-Object { $_.Current.Name -eq 'Project root' -and $_.Current.ControlType -eq [Windows.Automation.ControlType]::Edit } | Select-Object -First 1
    $button = $nodes | Where-Object { $_.Current.Name -eq 'Check status' -and $_.Current.ControlType -eq [Windows.Automation.ControlType]::Button } | Select-Object -First 1
    Assert-Spike ($null -ne $edit -and $null -ne $button) 'Project controls were not accessible.'
    $edit.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern).SetValue($project)
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while (!$button.Current.IsEnabled -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 100
    }
    Assert-Spike $button.Current.IsEnabled 'The project action stayed disabled after entering the path.'
    $button.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    $shown = $false
    do {
        Start-Sleep -Milliseconds 250
        $names = @($window.FindAll($subtree, [Windows.Automation.Condition]::TrueCondition) | ForEach-Object { $_.Current.Name })
        if ($names -contains $project -and $names -contains 'No database' -and $names -contains 'Yes') { $shown = $true; break }
    } while ([DateTime]::UtcNow -lt $deadline)
    Assert-Spike $shown 'The desktop did not display the initialized project status.'
    Write-Host 'Desktop WebView displayed real backend version, protocol, provider and project status.'
    Assert-Spike ($desktopProcess.CloseMainWindow()) 'Could not request desktop shutdown.'
    Assert-Spike ($desktopProcess.WaitForExit(15000) -and $desktopProcess.ExitCode -eq 0) 'Desktop shutdown did not complete.'
    $remaining = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.ExecutablePath -eq $python }
    Assert-Spike (!$remaining) 'Closing the desktop left a private Python sidecar running.'
    Assert-Spike (![IO.File]::Exists($autoLog) -and ![IO.File]::Exists($configuredLog)) 'Passive desktop startup launched a provider.'
    Assert-Spike ((Get-FileHash -LiteralPath $registry).Hash -eq $registryHash) 'Passive desktop startup rewrote provider state.'
    Assert-Spike ((Get-FileHash -LiteralPath $profile).Hash -eq $profileHash -and (Get-FileHash -LiteralPath $recent).Hash -eq $recentHash) 'Passive bridge changed project or recent state.'
    Assert-Spike (![IO.File]::Exists((Join-Path $project '.corinthos\state.db'))) 'Passive bridge created a project DB.'

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
    if ([IO.Directory]::Exists($root)) { Remove-SetupTree $root $parent }
}
