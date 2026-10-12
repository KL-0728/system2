param(
    [string]$MySqlExe = 'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe'
)

$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$taskData = Join-Path $taskRoot 'instance\d-mysql-data'
if (-not (Test-Path -LiteralPath (Join-Path $taskData 'auto.cnf'))) {
    throw 'D MySQL data not found. This script never initializes or resets a database.'
}
$taskData = (Resolve-Path -LiteralPath $taskData).Path
if (-not $taskData.StartsWith($taskRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Refusing a data directory outside this checkout.'
}
if (-not (Test-Path -LiteralPath $MySqlExe)) {
    throw 'MySQL executable not found. Supply -MySqlExe with the installed executable.'
}

function Test-TaskPort {
    $taskClient = [Net.Sockets.TcpClient]::new()
    try {
        $taskConnect = $taskClient.ConnectAsync('127.0.0.1', 3308)
        return ($taskConnect.Wait(500) -and $taskClient.Connected)
    } catch {
        return $false
    } finally {
        $taskClient.Dispose()
    }
}

if (Test-TaskPort) {
    Write-Output 'Port 3308 already responds; run check_environment.py to verify the D databases.'
    exit 0
}

$taskBase = Split-Path -Parent (Split-Path -Parent $MySqlExe)
$taskLog = Join-Path $taskRoot 'instance\d-mysql.log'
$taskArguments = @('--no-defaults', "--basedir=`"$taskBase`"", "--datadir=`"$taskData`"",
    '--port=3308', '--bind-address=127.0.0.1', '--mysqlx=OFF', "--log-error=`"$taskLog`"")
$taskProcess = Start-Process -FilePath $MySqlExe -ArgumentList $taskArguments -WindowStyle Hidden -PassThru
for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
    if (Test-TaskPort) {
        $taskProcess.Id | Set-Content -LiteralPath (Join-Path $taskRoot 'instance\d-mysql.pid')
        Write-Output 'D MySQL is ready on 127.0.0.1:3308. Existing data was preserved.'
        exit 0
    }
    if ($taskProcess.HasExited) {
        throw "MySQL exited. Inspect $taskLog locally."
    }
    Start-Sleep -Milliseconds 500
}
throw "MySQL did not become ready. Inspect $taskLog locally."
