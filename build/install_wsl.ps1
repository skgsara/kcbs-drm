$out = Join-Path $PSScriptRoot "wsl_install.log"
"=== elevated: $(Get-Date) ===" | Out-File $out
foreach ($f in @("Microsoft-Windows-Subsystem-Linux","VirtualMachinePlatform")) {
  $s = (Get-WindowsOptionalFeature -Online -FeatureName $f).State
  "BEFORE $f = $s" | Out-File $out -Append
  if ($s -ne "Enabled") {
    "enabling $f ..." | Out-File $out -Append
    $r = Enable-WindowsOptionalFeature -Online -FeatureName $f -All -NoRestart -ErrorAction Continue
    "  restartNeeded=$($r.RestartNeeded)" | Out-File $out -Append
  }
  "AFTER  $f = $((Get-WindowsOptionalFeature -Online -FeatureName $f).State)" | Out-File $out -Append
}
"--- wsl --status ---" | Out-File $out -Append
(& wsl --status 2>&1 | Out-String) | Out-File $out -Append
"--- wsl --update ---" | Out-File $out -Append
(& wsl --update 2>&1 | Out-String) | Out-File $out -Append
"DONE" | Out-File $out -Append
