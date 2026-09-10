# Creates a new subdirectory in the Meal Receipts directory 
# representing a day
# Precondition: Error Logs directory already exists (to make things cleaner)
# Postcondition: Folder representing today's date is created within Meal Receipts directory
# Total time taken to make this: 1 hour

param(
    [string]$Reason = "Duplicate folder attempt."
)
$tokyoDate = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId(
        (Get-Date), "Tokyo Standard Time").ToString('dd-MM-yyyy')
$dailyFolder = "C:\Users\echoj\The Prescripts\Meal Receipts\$tokyoDate"

if (-not (Test-Path -PathType Container $dailyFolder)) {
    ni -Path $dailyFolder -ItemType directory 
}
else {
    $errorTime = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId(
        (Get-Date), "Tokyo Standard Time").ToString('dd-MM-yyyy_HH-mm-ss')
    Add-Content -Path "C:\Users\echoj\The Prescripts\Meal Receipts\Error Logs\Error on $tokyoDate.txt" -Value "Error on $errorTime. $Reason"
}

