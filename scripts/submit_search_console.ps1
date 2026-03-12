$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $root "config\pages-seo.json"
$config = Get-Content $configPath -Encoding UTF8 | ConvertFrom-Json

if (-not $env:GOOGLE_OAUTH_TOKEN) {
    throw "GOOGLE_OAUTH_TOKEN environment variable is required."
}

$siteUrl = [string]$config.site_url
$sitemapUrl = "$siteUrl" + "sitemap.xml"
$encodedSiteUrl = [System.Uri]::EscapeDataString($siteUrl)
$encodedSitemapUrl = [System.Uri]::EscapeDataString($sitemapUrl)

$headers = @{
    Authorization = "Bearer $($env:GOOGLE_OAUTH_TOKEN)"
}

$verificationUrl = "$siteUrl$($config.verification_file)"
try {
    Invoke-WebRequest -UseBasicParsing -Uri $verificationUrl | Out-Null
} catch {
    throw "Verification file is not reachable at $verificationUrl"
}

$addSiteUrl = "https://www.googleapis.com/webmasters/v3/sites/$encodedSiteUrl"
$submitSitemapUrl = "https://www.googleapis.com/webmasters/v3/sites/$encodedSiteUrl/sitemaps/$encodedSitemapUrl"

Invoke-RestMethod -Method Put -Uri $addSiteUrl -Headers $headers | Out-Null
Invoke-RestMethod -Method Put -Uri $submitSitemapUrl -Headers $headers | Out-Null

Write-Output "Search Console site add request and sitemap submit request completed."
