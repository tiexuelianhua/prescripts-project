# Creates a new subdirectory representing the current month,
# nested inside the current year's directory (Meal Receipts\Year\Month)
# Precondition: Error Logs directory already exists; addYear_cV.ps1 sits alongside this script
# Postcondition: Folder representing the current month is created within the current year's folder,
#                ready to hold day directories
# Made by: Claude (cV)

param(
    [string]$Reason = "",
    [switch]$Silent
)

$mealReceiptsPath = "C:\Users\echoj\The Prescripts\Meal Receipts"
$jstNow = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Tokyo Standard Time")
$errorLogPath = Join-Path $mealReceiptsPath "Error Logs\Error Log on $($jstNow.ToString('dd-MM-yyyy')).txt"

$yearFolder = & "$PSScriptRoot\addYear_cV.ps1" -Reason $Reason -Silent

$japaneseMonths = @(
    "1月", "2月", "3月", "4月", "5月", "6月",
    "7月", "8月", "9月", "10月", "11月", "12月"
)
$monthName = "$($japaneseMonths[$jstNow.Month - 1])-$($jstNow.Year)"
$monthFolder = Join-Path $yearFolder $monthName

try {
    New-Item -Path $monthFolder -ItemType Directory -ErrorAction Stop | Out-Null
}
catch {
    $timestamp = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Tokyo Standard Time").ToString('dd-MM-yyyy_HH:mm:ss')
    $detail = if ($Reason) { " $Reason" } else { "" }
    if (-not $Silent) {
        Add-Content -Path $errorLogPath -Encoding UTF8 -Value "[$timestamp] $($_.Exception.GetType().Name): $($_.Exception.Message). Caused by: addMonth_cV.ps1.$detail"
    }
}

Write-Output $monthFolder