# Builds your personal copy of the extension in .\extension with a fresh secret code.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
$bytes = New-Object byte[] 12
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$token = -join ($bytes | ForEach-Object { $_.ToString("x2") })
New-Item -ItemType Directory -Force -Path "$PSScriptRoot\extension" | Out-Null
foreach ($f in "manifest.json", "autosend.js") {
  (Get-Content "$PSScriptRoot\src\$f" -Raw).Replace("__TOKEN__", $token) |
    Set-Content -NoNewline -Encoding UTF8 "$PSScriptRoot\extension\$f"
}
Write-Host "Built .\extension. Load it in brave://extensions (or chrome://extensions) with 'Load unpacked'."
