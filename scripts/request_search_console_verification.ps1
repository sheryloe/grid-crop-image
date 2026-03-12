$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $root "config\pages-seo.json"
$config = Get-Content $configPath -Encoding UTF8 | ConvertFrom-Json

$tokenValue = $env:GOOGLE_SITEVERIFICATION_TOKEN
if (-not $tokenValue) {
    $tokenValue = $env:GOOGLE_OAUTH_TOKEN
}

if (-not $tokenValue) {
    throw "GOOGLE_SITEVERIFICATION_TOKEN or GOOGLE_OAUTH_TOKEN environment variable is required."
}

$headers = @{
    Authorization = "Bearer $tokenValue"
    Accept = "application/json"
}

$body = @{
    site = @{
        type = "SITE"
        identifier = [string]$config.site_url
    }
    verificationMethod = "FILE"
} | ConvertTo-Json -Depth 4

$response = Invoke-RestMethod -Method Post -Uri "https://www.googleapis.com/siteVerification/v1/token" -Headers $headers -Body $body -ContentType "application/json"

$tokenFile = [string]$response.token
$targetPath = Join-Path $root $tokenFile
$fileContent = "google-site-verification: $tokenFile"
[System.IO.File]::WriteAllText($targetPath, $fileContent, [System.Text.UTF8Encoding]::new($false))

Write-Output "Created verification file: $targetPath"
Write-Output "Commit and push the new file, then run scripts/submit_search_console.ps1 or verify in Search Console UI."
