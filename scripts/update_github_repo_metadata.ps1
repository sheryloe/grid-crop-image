$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $root "config\pages-seo.json"
$config = Get-Content $configPath -Encoding UTF8 | ConvertFrom-Json

if (-not $env:GITHUB_TOKEN) {
    throw "GITHUB_TOKEN environment variable is required."
}

$headers = @{
    Authorization = "Bearer $($env:GITHUB_TOKEN)"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent" = "grid-crop-image-seo-script"
}

$repoApi = "https://api.github.com/repos/$($config.owner)/$($config.repo)"
$repoBody = @{
    description = $config.repo_description
    homepage = $config.homepage
} | ConvertTo-Json

Invoke-RestMethod -Method Patch -Uri $repoApi -Headers $headers -Body $repoBody -ContentType "application/json" | Out-Null

$topicsApi = "https://api.github.com/repos/$($config.owner)/$($config.repo)/topics"
$topicsBody = @{
    names = @($config.repo_topics)
} | ConvertTo-Json

Invoke-RestMethod -Method Put -Uri $topicsApi -Headers $headers -Body $topicsBody -ContentType "application/json" | Out-Null

$pagesApi = "https://api.github.com/repos/$($config.owner)/$($config.repo)/pages"
$pagesBody = @{
    source = @{
        branch = "main"
        path = "/"
    }
} | ConvertTo-Json -Depth 4

try {
    Invoke-RestMethod -Method Put -Uri $pagesApi -Headers $headers -Body $pagesBody -ContentType "application/json" | Out-Null
} catch {
    Write-Warning "Pages source update did not succeed. If Pages is already configured, this can be skipped."
}

Write-Output "GitHub repository description, homepage, topics, and Pages source update request completed."
