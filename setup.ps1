<#
.SYNOPSIS
  One-command setup for the godot-grounding MCP.
.DESCRIPTION
  Bootstraps the repo (venv, deps, locates Godot + shims it onto PATH, dumps the
  engine API) and, with -Project, onboards a Godot project end to end
  (godot-mcp.toml profile + /godot agent mode + .mcp.json). Idempotent.
.EXAMPLE
  .\setup.ps1
.EXAMPLE
  .\setup.ps1 -Project "C:\Users\me\Documents\MyGame"
#>
[CmdletBinding()]
param(
  [string]$Project,
  [string]$GodotBin,
  [switch]$Force,
  [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Py   = Join-Path $Root ".venv\Scripts\python.exe"

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }

# Uninstall the integration from a project (repo untouched).
if ($Uninstall) {
  if (-not $Project) { Write-Error "Uninstall requires -Project <path>"; exit 1 }
  $pyExe = if (Test-Path $Py) { $Py } else { "py" }
  $env:PYTHONPATH = Join-Path $Root "src"
  & $pyExe -m godot_mcp.init --uninstall $Project
  exit 0
}

# 1) venv
if (-not (Test-Path $Py)) {
  Step "Creating virtual environment (.venv)"
  & py -m venv (Join-Path $Root ".venv")
}

# 2) dependencies
& $Py -c "import mcp, gdtoolkit" 2>$null
if ($LASTEXITCODE -ne 0) {
  Step "Installing dependencies (mcp + gdtoolkit)"
  & $Py -m pip install -q --upgrade pip -r (Join-Path $Root "requirements.txt")
} else {
  Step "Dependencies present"
}

# 3) locate Godot
function Find-Godot {
  if ($GodotBin) {
    if (Test-Path $GodotBin) { return $GodotBin } else { Write-Warning "GodotBin '$GodotBin' not found" }
  }
  $cmd = Get-Command godot -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $roots = @("$env:USERPROFILE\Desktop", "$env:USERPROFILE\Downloads", "$env:USERPROFILE\Documents",
             "$env:LOCALAPPDATA\Programs", "C:\Program Files", "C:\Program Files (x86)")
  foreach ($r in $roots) {
    if (Test-Path $r) {
      $hit = Get-ChildItem $r -Recurse -Depth 4 -Filter "Godot*win64*.exe" -File -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -notmatch "console" } | Select-Object -First 1
      if ($hit) { return $hit.FullName }
    }
  }
  return $null
}

$godot = Find-Godot
if (-not $godot) {
  Write-Warning "Godot binary not found. Re-run with -GodotBin <path-to-Godot.exe> to enable the API dump."
} else {
  Step "Godot: $godot"
  # make `godot` resolvable on PATH via a ~/bin shim
  $bin  = Join-Path $env:USERPROFILE "bin"
  $shim = Join-Path $bin "godot.cmd"
  New-Item -ItemType Directory -Force $bin | Out-Null
  if (-not (Test-Path $shim)) {
    "@echo off`r`n`"$godot`" %*" | Out-File -FilePath $shim -Encoding ascii
    Step "Wrote shim $shim"
  }
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  if ($userPath -notlike "*$bin*") {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $bin), 'User')
    Step "Added $bin to your PATH (new shells will resolve ``godot``)"
  }

  # 4) dump the engine API
  $api = Join-Path $Root "data\extension_api.json"
  if ($Force -or -not (Test-Path $api)) {
    Step "Dumping extension_api.json"
    New-Item -ItemType Directory -Force (Join-Path $Root "data") | Out-Null
    Push-Location (Join-Path $Root "data")
    try { & $godot --headless --dump-extension-api } finally { Pop-Location }
  } else {
    Step "extension_api.json present (use -Force to re-dump)"
  }
}

# 5) onboard a project
if ($Project) {
  Step "Onboarding project: $Project"
  $env:PYTHONPATH = Join-Path $Root "src"
  & $Py -m godot_mcp.init $Project
}

Write-Host ""
Step "Done."
if (-not $Project) {
  Write-Host "Onboard a project:  .\setup.ps1 -Project `"C:\path\to\your\game`""
}
Write-Host "Then reload Claude Code / reconnect the MCP server in the project, and run /godot."
