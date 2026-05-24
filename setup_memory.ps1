# setup_memory.ps1
# Installs Kardit memory files into Claude Code's project memory system.
# Run once after cloning: .\setup_memory.ps1

$repoRoot = $PSScriptRoot
$encodedPath = $repoRoot -replace ':\\', '-' -replace '\\', '-' -replace ':', ''
$target = "$env:USERPROFILE\.claude\projects\$encodedPath\memory"

New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item "$repoRoot\.claude\memory\*" $target -Recurse -Force

Write-Host "Memory installed to: $target"
Write-Host "Open Claude Code in this directory and it will have full Kardit context."
