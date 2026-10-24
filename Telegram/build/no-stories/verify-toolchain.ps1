$ErrorActionPreference = 'Stop'

if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'Toolchain verification is restricted to the Windows Actions runner.'
}
if ($env:VisualStudioVersion -notmatch '^17\.' -or $env:VCToolsVersion -notmatch '^14\.44\.' -or $env:Platform -ne 'x64') {
    throw 'Expected Visual Studio 2022 with MSVC 14.44 targeting x64.'
}
if ([string]::IsNullOrWhiteSpace($env:VCToolsInstallDir)) {
    throw 'MSVC developer environment did not provide VCToolsInstallDir.'
}
$atl = Join-Path $env:VCToolsInstallDir 'atlmfc\include'
foreach ($header in @('atlbase.h', 'atlcomcli.h')) {
    if (-not (Test-Path -LiteralPath (Join-Path $atl $header) -PathType Leaf)) {
        throw "The selected MSVC 14.44 toolset is missing ATL header $header."
    }
}
$probe = Join-Path $env:USERPROFILE 'TBuild\toolchain-probe'
New-Item -ItemType Directory -Force -Path $probe | Out-Null
$source = Join-Path $probe 'atl-probe.cpp'
$object = Join-Path $probe 'atl-probe.obj'
$binary = Join-Path $probe 'atl-probe.exe'
@(
    '#include <atlbase.h>',
    '#include <atlcomcli.h>',
    'int main() {',
    '    ATL::CComPtr<IUnknown> value;',
    '    return value ? 1 : 0;',
    '}'
) | Set-Content -LiteralPath $source -Encoding utf8NoBOM
$compiler = (Get-Command cl.exe -CommandType Application).Source
& $compiler /nologo /EHsc /MT /W4 /WX "/Fo$object" "/Fe$binary" $source
if ($LASTEXITCODE -ne 0) {
    throw 'The selected MSVC environment could not compile and link the ATL probe.'
}
& $binary
if ($LASTEXITCODE -ne 0) {
    throw 'The ATL probe returned an unexpected result.'
}
Write-Output "Verified MSVC $env:VCToolsVersion with matching ATL: $atl"
