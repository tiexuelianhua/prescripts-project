# Creates a new subdirectory in the Meal Receipts directory
# representing a year
# Precondition: Error Logs directory already exists (to make things cleaner)
# Postcondition: Folder representing the current year is created within the Meal Receipts directory
# Made by: Claude (cV)

param(
    [string]$Reason = "",
    [switch]$Silent
)

# Beside this repo's folder, wherever that's been put.
$mealReceiptsPath = Join-Path (Split-Path $PSScriptRoot -Parent) "Meal Receipts"
$jstNow = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Tokyo Standard Time")
$yearFolder = Join-Path $mealReceiptsPath $jstNow.ToString('yyyy')
$errorLogPath = Join-Path $mealReceiptsPath "Error Logs\Error Log on $($jstNow.ToString('dd-MM-yyyy')).txt"

try {
    New-Item -Path $yearFolder -ItemType Directory -ErrorAction Stop | Out-Null
}
catch {
    $timestamp = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Tokyo Standard Time").ToString('dd-MM-yyyy_HH:mm:ss')
    $detail = if ($Reason) { " $Reason" } else { "" }
    if (-not $Silent) {
        Add-Content -Path $errorLogPath -Encoding UTF8 -Value "[$timestamp] $($_.Exception.GetType().Name): $($_.Exception.Message). Caused by: addYear_cV.ps1.$detail"
    }
}

Write-Output $yearFolder
