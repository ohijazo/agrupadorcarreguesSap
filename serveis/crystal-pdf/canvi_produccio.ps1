# =====================================================================
# crystal-pdf: canvi a SAP de produccio (DB_FARIN_TEST -> DB_FARINERA)
# Pas 7 de docs/canvi_a_produccio.md, automatitzat.
#
#   .\canvi_produccio.ps1              # nomes diu que faria
#   .\canvi_produccio.ps1 -Executar    # fa el canvi i reinicia el servei
#   .\canvi_produccio.ps1 -Programar   # tasca programada: 23/11/2026 00:05, com a SYSTEM
#
# El crystal-pdf.exe.config va xifrat amb DPAPI de maquina: es desxifra,
# es canvia SqlDatabase i es torna a xifrar. Abans en guarda una copia
# (xifrada). Si ja apunta a DB_FARINERA, no fa res.
# =====================================================================
param([switch]$Executar, [switch]$Programar)

$ErrorActionPreference = 'Stop'
$Dir  = 'C:\Serveis\CrystalPdf'
$Exe  = Join-Path $Dir 'crystal-pdf.exe'
$Cfg  = Join-Path $Dir 'crystal-pdf.exe.config'
$Log  = Join-Path $Dir 'logs\canvi_produccio.log'
$Test = 'DB_FARIN_TEST'
$Prod = 'DB_FARINERA'
$Quan = Get-Date '2026-11-23T00:05:00'
$Tasca = 'CrystalPdf - canvi a DB_FARINERA'

function Log($m) {
    $l = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"
    Write-Output $l
    Add-Content -Path $Log -Value $l -Encoding UTF8
}

if ($Programar) {
    $script = $MyInvocation.MyCommand.Path
    $accio = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Executar"
    $quan = New-ScheduledTaskTrigger -Once -At $Quan
    $qui  = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $opc  = New-ScheduledTaskSettingsSet -StartWhenAvailable
    Register-ScheduledTask -TaskName $Tasca -Action $accio -Trigger $quan -Principal $qui `
        -Settings $opc -Force | Out-Null
    Get-ScheduledTask -TaskName $Tasca | Get-ScheduledTaskInfo | Format-List TaskName, NextRunTime
    exit 0
}

$patroTest = 'key="SqlDatabase"\s+value="' + $Test + '"'
$patroProd = 'key="SqlDatabase"\s+value="' + $Prod + '"'

Copy-Item $Cfg "$Cfg.abans-produccio-$(Get-Date -Format 'yyyyMMdd-HHmmss')"   # copia xifrada
& $Exe --desprotegeix | Out-Null
try {
    $text = [IO.File]::ReadAllText($Cfg)
    if ($text -match $patroProd) { Log "Ja apunta a $Prod`: res a fer."; return }
    if ($text -notmatch $patroTest) { throw "No trobo SqlDatabase=$Test al config" }
    if (-not $Executar) { Log "Comprovat: es canviaria SqlDatabase $Test -> $Prod (falta -Executar)"; return }
    [IO.File]::WriteAllText($Cfg, ($text -replace $patroTest, ('key="SqlDatabase" value="' + $Prod + '"')))
    Log "SqlDatabase -> $Prod"
}
finally {
    & $Exe --protegeix | Out-Null      # sempre torna a xifrar, passi el que passi
}

Restart-Service CrystalPdf
Start-Sleep -Seconds 5
$s = Get-Service CrystalPdf
if ($s.Status -ne 'Running') { Log "ERROR: CrystalPdf no ha arrencat ($($s.Status))"; exit 1 }
Log "CrystalPdf reiniciat i en marxa amb $Prod"
