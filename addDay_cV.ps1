# Creates a new subdirectory in the Meal Receipts directory
# representing a day
# Precondition: Error Logs directory already exists (to make things cleaner)
# Postcondition: Folder representing today's date is created within Meal Receipts directory
# Total time: 10 mins

param(
    [string]$Reason = ""
)

$mealReceiptsPath = "C:\Users\echoj\The Prescripts\Meal Receipts"
$jstNow = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Tokyo Standard Time")
$todayDate = $jstNow.ToString('dd-MM-yyyy')
$dailyFolder = Join-Path $mealReceiptsPath $todayDate
$errorLogPath = Join-Path $mealReceiptsPath "Error Logs\Error on $todayDate.txt"

try {
    New-Item -Path $dailyFolder -ItemType Directory -ErrorAction Stop | Out-Null
}
catch {
    $timestamp = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Tokyo Standard Time").ToString('dd-MM-yyyy_HH-mm-ss')
    $detail = if ($Reason) { " $Reason" } else { "" }
    Add-Content -Path $errorLogPath -Value "[$timestamp] $($_.Exception.GetType().Name): $($_.Exception.Message).$detail"
}

Write-Output $dailyFolder
