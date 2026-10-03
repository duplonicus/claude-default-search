# Builds your personal copy of the extension in .\extension with a fresh secret code.
# Optional: put PROJECT_URL=<a claude.ai project link> in .env to file searches in that project.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
$bytes = New-Object byte[] 12
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$token = -join ($bytes | ForEach-Object { $_.ToString("x2") })
$project = "__PROJECT__"
$envFile = "$PSScriptRoot\.env"
if (Test-Path $envFile) {
  $line = Get-Content $envFile | Where-Object { $_ -match '^\s*PROJECT_URL\s*=' } | Select-Object -First 1
  if ($line) {
    $value = ($line -replace '^\s*PROJECT_URL\s*=', '').Trim(" `"'")
    if ($value -match '[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}') {
      $project = $Matches[0]
    } elseif ($value) {
      throw "PROJECT_URL in .env has no project id in it (expected https://claude.ai/project/<id>)."
    }
  }
}
New-Item -ItemType Directory -Force -Path "$PSScriptRoot\extension" | Out-Null
foreach ($f in Get-ChildItem "$PSScriptRoot\src" -File) {
  $text = (Get-Content $f.FullName -Raw -Encoding UTF8).Replace("__TOKEN__", $token).Replace("__PROJECT__", $project)
  # WriteAllText writes UTF-8 without a byte-order mark, which Set-Content would add.
  [System.IO.File]::WriteAllText("$PSScriptRoot\extension\$($f.Name)", $text)
}
if ($project -ne "__PROJECT__") {
  Write-Host "Searches will start in claude.ai project $project."
}
Write-Host "Built .\extension. Load it in brave://extensions (or chrome://extensions) with 'Load unpacked'."
