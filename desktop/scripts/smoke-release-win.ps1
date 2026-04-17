param(
  [string]$ExePath = "",
  [int]$HealthTimeoutSeconds = 90,
  [switch]$SkipRelaunch
)

$ErrorActionPreference = "Stop"

function Resolve-ExePath {
  param([string]$Candidate)

  if ($Candidate -and (Test-Path -LiteralPath $Candidate)) {
    return (Resolve-Path -LiteralPath $Candidate).Path
  }

  $defaultPath = Join-Path $PSScriptRoot "..\src-tauri\target\release\neuralclaw-desktop.exe"
  $resolvedDefault = Resolve-Path -LiteralPath $defaultPath -ErrorAction SilentlyContinue
  if ($resolvedDefault) {
    return $resolvedDefault.Path
  }

  throw "Could not find neuralclaw-desktop.exe. Pass -ExePath explicitly."
}

function Stop-StaleProcesses {
  $names = @(
    "neuralclaw-desktop",
    "neuralclaw-sidecar",
    "neuralclaw-sidecar-x86_64-pc-windows-msvc"
  )
  foreach ($name in $names) {
    Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  }
}

function Wait-ForHealth {
  param([int]$TimeoutSeconds)

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8080/health" -TimeoutSec 3
      if ($resp.status -eq "healthy") {
        return $true
      }
    } catch {
      Start-Sleep -Milliseconds 1200
      continue
    }
    Start-Sleep -Milliseconds 1200
  }
  return $false
}

function Run-LaunchCycle {
  param(
    [string]$BinaryPath,
    [string]$Label,
    [int]$TimeoutSeconds
  )

  Write-Host "[smoke] Starting $Label from $BinaryPath"
  $proc = Start-Process -FilePath $BinaryPath -PassThru
  if (-not (Wait-ForHealth -TimeoutSeconds $TimeoutSeconds)) {
    throw "$Label failed: backend health never became healthy within $TimeoutSeconds seconds."
  }

  Write-Host "[smoke] $Label healthy on http://127.0.0.1:8080/health"

  try {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  } catch {
  }

  Start-Sleep -Seconds 3
  Stop-StaleProcesses
}

$resolvedExe = Resolve-ExePath -Candidate $ExePath
Write-Host "[smoke] Using executable: $resolvedExe"

Stop-StaleProcesses
Run-LaunchCycle -BinaryPath $resolvedExe -Label "first launch" -TimeoutSeconds $HealthTimeoutSeconds

if (-not $SkipRelaunch) {
  Run-LaunchCycle -BinaryPath $resolvedExe -Label "relaunch" -TimeoutSeconds $HealthTimeoutSeconds
}

Write-Host "[smoke] Release smoke test passed."
