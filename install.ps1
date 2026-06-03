# One-liner bootstrap installer for the godot-grounding MCP.
#
#   iwr -useb https://raw.githubusercontent.com/kidsmeal/godot-mcp/main/install.ps1 | iex
#
# Onboard a project in the same step (set this first):
#   $env:GODOT_MCP_PROJECT="C:\path\to\your\game"
#
# Optional: $env:GODOT_MCP_DIR to choose the install location (default %USERPROFILE%\godot-mcp).
$ErrorActionPreference = "Stop"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

$RepoUrl = "https://github.com/kidsmeal/godot-mcp.git"
$ZipUrl  = "https://github.com/kidsmeal/godot-mcp/archive/refs/heads/main.zip"
$Dir = if ($env:GODOT_MCP_DIR) { $env:GODOT_MCP_DIR } else { Join-Path $env:USERPROFILE "godot-mcp" }

if (Test-Path (Join-Path $Dir ".git")) {
  Write-Host "Updating existing clone at $Dir..."
  git -C $Dir pull --ff-only
} elseif (Get-Command git -ErrorAction SilentlyContinue) {
  Write-Host "Cloning godot-mcp into $Dir..."
  git clone --depth 1 $RepoUrl $Dir
} else {
  Write-Host "git not found - downloading zip..."
  $zip = Join-Path $env:TEMP "godot-mcp-main.zip"
  Invoke-WebRequest $ZipUrl -OutFile $zip
  Expand-Archive $zip -DestinationPath $env:TEMP -Force
  if (Test-Path $Dir) { Remove-Item $Dir -Recurse -Force }
  Move-Item (Join-Path $env:TEMP "godot-mcp-main") $Dir
  Remove-Item $zip -Force
}

$setup = Join-Path $Dir "setup.ps1"
if ($env:GODOT_MCP_PROJECT) {
  & $setup -Project $env:GODOT_MCP_PROJECT
} else {
  & $setup
}
