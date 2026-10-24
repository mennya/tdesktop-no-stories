$ErrorActionPreference = 'Stop'

function Test-DisposableDependencyFile {
    param([string] $RelativePath)
    if ($RelativePath -match '(^|[\\/])objects-[^\\/]+[\\/]') {
        return $false
    }
    $extension = [IO.Path]::GetExtension($RelativePath).ToLowerInvariant()
    return $extension -in @('.obj', '.o', '.pdb', '.pch', '.ilk', '.idb', '.ipdb', '.iobj')
}

if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'Dependency cleanup is restricted to the ephemeral Windows Actions runner.'
}
$expected = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'TBuild\Libraries\win64'))
$root = (Get-Item -LiteralPath $expected).FullName
if ($root -ne $expected -or (Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Unexpected dependency root.'
}
$prefix = $root.TrimEnd('\') + '\'
$count = 0
$bytes = [int64] 0
Get-ChildItem -LiteralPath $root -Recurse -File -Force | ForEach-Object {
    $path = [IO.Path]::GetFullPath($_.FullName)
    if (-not $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Dependency file escaped the expected root.'
    }
    $relative = $path.Substring($prefix.Length)
    if (-not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -and (Test-DisposableDependencyFile $relative)) {
        $bytes += $_.Length
        Remove-Item -LiteralPath $path -Force
        $count += 1
    }
}
Write-Output ('Removed {0} disposable files; reclaimed {1:N2} GiB.' -f $count, ($bytes / 1GB))
Get-PSDrive -PSProvider FileSystem | Select-Object Name, Used, Free
