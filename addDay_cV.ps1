# Creates a new subdirectory representing today's date,
# nested inside the current month's directory (Meal Receipts\Year\Month\Day)
# Precondition: Error Logs directory already exists; addMonth_cV.ps1 sits alongside this script
# Postcondition: Folder representing today's date is created within the current month's folder
# Made by: Claude (cV)

param(
    [string]$Reason = "",
    [switch]$Silent
)

$mealReceiptsPath = "C:\Users\echoj\The Prescripts\Meal Receipts"
$jstNow = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Tokyo Standard Time")
$todayDate = $jstNow.ToString('dd-MM-yyyy')
$errorLogPath = Join-Path $mealReceiptsPath "Error Logs\Error Log on $todayDate.txt"

$monthFolder = & "$PSScriptRoot\addMonth_cV.ps1" -Reason $Reason -Silent
$dailyFolder = Join-Path $monthFolder $todayDate

try {
    New-Item -Path $dailyFolder -ItemType Directory -ErrorAction Stop | Out-Null
}
catch {
    $timestamp = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Tokyo Standard Time").ToString('dd-MM-yyyy_HH:mm:ss')
    $detail = if ($Reason) { " $Reason" } else { "" }
    if (-not $Silent) {
        Add-Content -Path $errorLogPath -Encoding UTF8 -Value "[$timestamp] $($_.Exception.GetType().Name): $($_.Exception.Message). Caused by: addDay_cV.ps1.$detail"
    }
}

Write-Output $dailyFolder
