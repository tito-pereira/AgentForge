# SPDX-License-Identifier: MPL-2.0

function Show-InstallProgress([int] $Percent, [string] $Message) {
    $Percent = [Math]::Max($script:InstallPercent, $Percent)
    $script:InstallPercent = $Percent
    $filled = [int] [Math]::Floor($Percent / 5)
    $bar = ([string] [char] 0x2588) * $filled + ([string] [char] 0x2591) * (20 - $filled)
    Write-Progress -Activity 'Installing Corinthos' -Status $Message -PercentComplete $Percent
    Write-Host ('[{0}] {1}%  {2}' -f $bar, $Percent, $Message)
}

function Receive-Artifact($Uri, [long] $Bytes, [string] $Destination, [int] $Start, [int] $End) {
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $cancel = [Threading.CancellationTokenSource]::new([TimeSpan]::FromMinutes(3))
    try {
        $response = $client.GetAsync($Uri, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $cancel.Token).GetAwaiter().GetResult()
        try {
            if ([int] $response.StatusCode -ne 200) {
                throw "Download returned HTTP $([int] $response.StatusCode) for $($Uri.AbsolutePath)."
            }
            $length = $response.Content.Headers.ContentLength
            if ($null -ne $length -and $length -ne $Bytes) {
                throw 'Download length differs from the pinned artifact.'
            }
            $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $output = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew)
            try {
                $buffer = [byte[]]::new(65536)
                $total = 0L
                while ($count = $stream.ReadAsync($buffer, 0, $buffer.Length, $cancel.Token).GetAwaiter().GetResult()) {
                    $total += $count
                    if ($total -gt $Bytes) { throw 'Download exceeded the pinned artifact size.' }
                    $output.Write($buffer, 0, $count)
                    if ($null -ne $length) {
                        $percent = $Start + [int] [Math]::Floor(($End - $Start) * $total / $length)
                        if ($percent -gt $script:InstallPercent) {
                            Show-InstallProgress $percent "Downloading $([IO.Path]::GetFileName($Destination))"
                        }
                    }
                }
                if ($total -ne $Bytes) { throw 'Download ended before the pinned artifact size.' }
            } finally { $output.Dispose() }
        } finally { $response.Dispose() }
    } finally {
        $cancel.Dispose()
        $client.Dispose()
    }
}

function Get-PinnedArtifact($Pin, [string] $ExpectedHost, [string] $Cache, [string] $Work, [int] $Start, [int] $End) {
    $uri = [Uri] $Pin.url
    if ($Pin.filename -cnotmatch '^[a-zA-Z0-9_.-]+\.(zip|whl)$' -or
        $Pin.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $Pin.bytes -lt 1 -or $Pin.bytes -gt 64MB -or
        $uri.Scheme -cne 'https' -or $uri.Host -cne $ExpectedHost -or
        !$uri.IsDefaultPort -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or
        [IO.Path]::GetFileName($uri.AbsolutePath) -cne $Pin.filename) {
        throw 'The distribution manifest contains an invalid artifact pin.'
    }
    $cached = Join-Path $Cache $Pin.filename
    $artifact = Join-Path $Work $Pin.filename
    Assert-PlainPath $cached
    $usingCache = [IO.File]::Exists($cached)
    if ($usingCache) {
        if ([IO.FileInfo]::new($cached).Length -ne $Pin.bytes) {
            throw "Cached artifact size verification failed. Remove $cached and retry."
        }
        [IO.File]::Copy($cached, $artifact)
    } else {
        Show-InstallProgress $Start "Downloading $($Pin.filename)"
        Receive-Artifact $uri $Pin.bytes $artifact $Start $End
    }
    Show-InstallProgress $End "Verifying $($Pin.filename)"
    $hash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -cne $Pin.sha256) {
        if ($usingCache) { throw "Cached artifact SHA-256 verification failed. Remove $cached and retry." }
        throw "SHA-256 verification failed for $($Pin.filename). Retry from a trusted checkout."
    }
    if (!$usingCache) { [IO.File]::Copy($artifact, $cached) }
    return $artifact
}

function Copy-ApplicationFiles([string] $Source, [string] $Destination) {
    Assert-PlainPath $Source
    [void] [IO.Directory]::CreateDirectory($Destination)
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        if ($item.Name -eq '__pycache__') { continue }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "The source checkout contains a redirected application entry: $($item.FullName)."
        }
        $target = Join-Path $Destination $item.Name
        if ($item.PSIsContainer) { Copy-ApplicationFiles $item.FullName $target }
        elseif ($item.Extension -in @('.py', '.json', '.yaml')) { [IO.File]::Copy($item.FullName, $target) }
    }
}

function Get-LauncherCompiler {
    $windows = [IO.Path]::GetDirectoryName([Environment]::SystemDirectory)
    $compiler = Join-Path $windows 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    Assert-PlainPath $compiler
    if (![IO.File]::Exists($compiler)) { throw 'The Windows .NET Framework x64 compiler is unavailable.' }
    return $compiler
}

function New-InstallCandidate([string] $Source, $Paths, [string] $Work, [string] $Compiler) {
    if (!('System.IO.Compression.ZipFile' -as [type])) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
    }
    if (!('System.Net.Http.HttpClient' -as [type])) { Add-Type -AssemblyName System.Net.Http }
    $manifestPath = Join-Path $Source 'platform\windows\artifacts.json'
    Assert-PlainPath $manifestPath
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.python.version -cne '3.14.10' -or
        $manifest.python.filename -cne 'python-3.14.10-embed-amd64.zip' -or
        $manifest.wheels.Count -ne 6) {
        throw 'The distribution manifest does not describe the supported private runtime and dependencies.'
    }
    $candidate = Join-Path $Work 'candidate'
    foreach ($name in @('bin', 'runtime', 'app', 'resources', 'platform\windows')) {
        [void] [IO.Directory]::CreateDirectory((Join-Path $candidate $name))
    }
    $runtime = Get-PinnedArtifact $manifest.python 'www.python.org' $Paths.Cache $Work 12 38
    [IO.Compression.ZipFile]::ExtractToDirectory($runtime, (Join-Path $candidate 'runtime'))
    Show-InstallProgress 40 'Private Python runtime verified and staged'
    $start = 44
    foreach ($pin in $manifest.wheels) {
        $wheel = Get-PinnedArtifact $pin 'files.pythonhosted.org' $Paths.Cache $Work $start ($start + 4)
        [IO.Compression.ZipFile]::ExtractToDirectory($wheel, (Join-Path $candidate 'app'))
        $start += 4
    }
    Show-InstallProgress 68 'Pinned dependencies staged'
    Copy-ApplicationFiles (Join-Path $Source 'src\corinthos') (Join-Path $candidate 'app\corinthos')
    [IO.File]::WriteAllLines((Join-Path $candidate 'runtime\python314._pth'), @('python314.zip', '.', '..\app'))
    $launcherSource = Join-Path $Source 'platform\windows\launcher.cs'
    $launcher = Join-Path $candidate 'bin\corinthos.exe'
    Assert-PlainPath $launcherSource
    & $Compiler /nologo /target:exe /platform:x64 "/out:$launcher" $launcherSource | Out-Host
    if ($LASTEXITCODE -ne 0 -or ![IO.File]::Exists($launcher)) { throw 'Could not compile the local launcher.' }
    [IO.File]::Copy($manifestPath, (Join-Path $candidate 'resources\artifacts.json'))
    [IO.File]::Copy((Join-Path $Source 'LICENSE'), (Join-Path $candidate 'resources\LICENSE'))
    [IO.File]::Copy((Join-Path $Source 'uninstall.ps1'), (Join-Path $candidate 'uninstall.ps1'))
    [IO.File]::Copy((Join-Path $Source 'platform\windows\common.ps1'), (Join-Path $candidate 'platform\windows\common.ps1'))
    Show-InstallProgress 75 'Corinthos application and launcher staged'
    return $candidate
}

function Invoke-PrivatePython([string] $Install, [string[]] $Arguments) {
    $python = Join-Path $Install 'runtime\python.exe'
    & $python -I -B -X utf8 @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Private Python check failed (exit $LASTEXITCODE): $($Arguments[0])." }
}

function Test-InstallCandidate([string] $Install) {
    $probe = @'
import platform, sys, yaml
from importlib.resources import files
from pathlib import Path
from jsonschema import Draft202012Validator
from rpds import HashTrieMap
import corinthos
import corinthos.bootstrap
assert platform.python_version() == '3.14.10' and sys.flags.isolated and sys.flags.no_site
runtime = Path(sys.executable).resolve().parent
app = runtime.parent / 'app'
assert all(Path(item).resolve().is_relative_to(runtime) or Path(item).resolve() == app for item in sys.path)
assert Path(corinthos.__file__).resolve().is_relative_to(app)
assert yaml.__with_libyaml__ and HashTrieMap({'ready': True})['ready']
assert files('corinthos.resources').joinpath('standard.schema.json').is_file()
Draft202012Validator.check_schema({'type': 'object'})
print(corinthos.__version__)
'@
    return Invoke-PrivatePython $Install @('-c', $probe)
}

function Write-InstallManifest([string] $Install, [string] $State, [string] $Version, [string] $Work) {
    $path = Join-Path $Install 'installation.json'
    $temporary = Join-Path $Work 'installation-next.json'
    $entries = if ($State -eq 'staged') {
        @(Get-SetupInventory $Install -ProtectProjects) + @('file:installation.json')
    } else { (Read-InstallManifest $Install).entries }
    $value = [ordered] @{
        schema = 1
        owner = 'corinthos-core'
        state = $State
        version = $Version
        python = '3.14.10'
        artifact_manifest_sha256 = (Get-FileHash -LiteralPath (Join-Path $Install 'resources\artifacts.json')).Hash.ToLowerInvariant()
        entries = @($entries | Sort-Object)
    }
    [IO.File]::WriteAllText($temporary, ($value | ConvertTo-Json))
    if ([IO.File]::Exists($path)) { [IO.File]::Replace($temporary, $path, [NullString]::Value) }
    else { [IO.File]::Move($temporary, $path) }
}
