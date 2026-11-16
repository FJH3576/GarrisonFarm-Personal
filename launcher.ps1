[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

function Write-FilteredSdkOutput($Reader) {
    $buffer = ''
    $passLine = $false
    $dropLine = $false
    while (($value = $Reader.Read()) -ne -1) {
        $char = [char]$value
        if ($dropLine) {
            if ($char -eq "`n") { $dropLine = $false; $buffer = ''; $passLine = $false }
            continue
        }
        if ($passLine) {
            [Console]::Write($char)
            if ($char -eq "`n") { $passLine = $false }
            continue
        }
        $buffer += $char
        if (($buffer -match '^x: -?\d') -or ($buffer -eq 'after convert, x_point:')) {
            $dropLine = $true
            $buffer = ''
            continue
        }
        $possible = 'x: '.StartsWith($buffer) -or 'x: -'.StartsWith($buffer) -or 'after convert, x_point:'.StartsWith($buffer)
        if (-not $possible) {
            [Console]::Write($buffer)
            $passLine = ($char -ne "`n")
            $buffer = ''
        }
    }
    if (-not $dropLine -and $buffer) { [Console]::Write($buffer) }
}

if ($env:GF_FILTER_TEST) {
    Write-FilteredSdkOutput ([System.IO.StringReader]::new("normal`nx: 790, y: 920, width: 1920`nafter convert, x_point: 160, y_point: 790`nERROR stays`nPrompt: "))
    exit 0
}

$info = New-Object System.Diagnostics.ProcessStartInfo
$info.FileName = $env:ComSpec
$info.WorkingDirectory = (Get-Location).Path
$info.Arguments = '--runs 20 --menu --show-doc 开始刷角标.bat'
if ($env:GF_LAUNCH_MODE -eq 'help') { $info.Arguments = '--help' }
if ($env:GF_LAUNCH_MODE -eq 'check') { $info.Arguments = '--mumu-check' }
# Merge native stderr into the same filtered stream, preserving all non-coordinate lines.
$info.Arguments = '/d /s /c ' + [char]34 + 'GarrisonFarm.exe ' + $info.Arguments + ' 2>&1' + [char]34
$info.UseShellExecute = $false
$info.RedirectStandardOutput = $true
$info.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
# stdin and stderr remain attached to the console; prompts are streamed without waiting for newline.
$process = [System.Diagnostics.Process]::Start($info)
try {
    Write-FilteredSdkOutput $process.StandardOutput
    $process.WaitForExit()
    $result = $process.ExitCode
} finally {
    $process.Dispose()
}
exit $result
