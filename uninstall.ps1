# SPDX-License-Identifier: MPL-2.0
#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'platform\windows\common.ps1')

$paths = Get-CorinthosPaths
$mutex = Enter-CorinthosSetup
$key = $null
$location = Get-Location
$workingDirectory = [Environment]::CurrentDirectory
try {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
    if ($null -eq $key) { throw 'The current user Environment registry key is unavailable.' }
    [void] (Get-UserPath $key)
    Restore-PreviousInstall $paths $key
    $originalPath = Get-UserPath $key
    $retired = $null
    if ([IO.Directory]::Exists($paths.Install)) {
        Set-Location -LiteralPath $paths.Programs
        if ($workingDirectory -eq $paths.Install -or
            $workingDirectory.StartsWith("$($paths.Install)\", [StringComparison]::OrdinalIgnoreCase)) {
            [Environment]::CurrentDirectory = $paths.Programs
        }
        $retired = Move-ToRetiredSetup $paths.Install $paths.Programs
    }
    try { Set-OwnedUserPath $key $originalPath $paths.Bin -Remove }
    catch {
        if ($retired) { [IO.Directory]::Move($retired, $paths.Install) }
        throw
    }
    Send-UserPathChange
    if ($retired) { Clear-RetiredSetup $retired $paths.Programs }
    Write-Host 'Corinthos application removed. User settings and projects were preserved.'
} finally {
    if ([IO.Directory]::Exists($workingDirectory)) { [Environment]::CurrentDirectory = $workingDirectory }
    if ($location.Provider.Name -ne 'FileSystem' -or [IO.Directory]::Exists($location.Path)) {
        Set-Location -LiteralPath $location.Path
    }
    if ($key) { $key.Dispose() }
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
