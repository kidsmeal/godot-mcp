# Dumps Godot's extension_api.json (exact signatures for the installed engine)
# into ../data so the MCP can ground engine API calls. Re-run after upgrading Godot.
$ErrorActionPreference = "Stop"
$data = Join-Path $PSScriptRoot "..\data"
New-Item -ItemType Directory -Force -Path $data | Out-Null
Push-Location $data
try {
    & godot --headless --dump-extension-api
    Write-Host "Wrote $data\extension_api.json"
} finally {
    Pop-Location
}
