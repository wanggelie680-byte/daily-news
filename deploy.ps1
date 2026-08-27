param(
    [Parameter(Mandatory = $true)]
    [string]$RepoUrl
)

# 用法：.\deploy.ps1 https://github.com/你的用户名/daily-news.git
$ErrorActionPreference = "Stop"

if (-not (git remote | Select-String -Quiet "origin")) {
    git remote add origin $RepoUrl
} else {
    git remote set-url origin $RepoUrl
}

git push -u origin main

Write-Host ""
Write-Host "推送完成。接下来请到仓库 Settings -> Pages 选择："
Write-Host "  Source: Deploy from a branch"
Write-Host "  Branch: main"
Write-Host "  Folder: /docs"
