param(
    [string]$Version,
    [switch]$Persist
)

$ErrorActionPreference = "Stop"

function Get-CoreDirectory {
    param([string]$Executable)
    $windowsDirectory = Split-Path -Parent $Executable
    $utilitiesDirectory = Split-Path -Parent $windowsDirectory
    return Split-Path -Parent $utilitiesDirectory
}

function Test-StEdgeAiCandidate {
    param([string]$Executable)
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $false
    }

    $directory = Split-Path -Parent $Executable
    $requiredModule = Get-ChildItem -LiteralPath $directory -Recurse -Filter "c_info_data*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $requiredModule) {
        return $false
    }

    $output = & $Executable --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        return $false
    }
    return ($output -join "`n").Trim().Length -gt 0
}

function Add-Candidate {
    param(
        [System.Collections.Generic.List[string]]$Candidates,
        [string]$Path
    )
    if ($Path -and (Test-Path -LiteralPath $Path -PathType Leaf) -and -not $Candidates.Contains($Path)) {
        $Candidates.Add($Path)
    }
}

$candidates = [System.Collections.Generic.List[string]]::new()
Add-Candidate $candidates $env:ARONA_STEDGEAI_PATH

if ($env:STEDGEAI_CORE_DIR) {
    Add-Candidate $candidates (Join-Path $env:STEDGEAI_CORE_DIR "Utilities\windows\stedgeai.exe")
}

foreach ($root in @("C:\ST\STEdgeAI", "$env:USERPROFILE\STM32Cube\Repository\Packs\STMicroelectronics\X-CUBE-AI")) {
    if (Test-Path -LiteralPath $root -PathType Container) {
        Get-ChildItem -LiteralPath $root -Directory | Sort-Object Name -Descending | ForEach-Object {
            if (-not $Version -or $_.Name -eq $Version) {
                Add-Candidate $candidates (Join-Path $_.FullName "Utilities\windows\stedgeai.exe")
            }
        }
    }
}

$selected = $null
foreach ($candidate in $candidates) {
    if (Test-StEdgeAiCandidate $candidate) {
        $selected = (Resolve-Path -LiteralPath $candidate).Path
        break
    }
}

if (-not $selected) {
    Write-Error "No usable stedgeai.exe was found. Reinstall or repair ST Edge AI Core/X-CUBE-AI, then rerun this script."
}

$coreDirectory = Get-CoreDirectory $selected
$toolDirectory = Split-Path -Parent $selected
$env:ARONA_STEDGEAI_PATH = $selected
$env:STEDGEAI_CORE_DIR = $coreDirectory
if (($env:PATH -split ";") -notcontains $toolDirectory) {
    $env:PATH = "$toolDirectory;$env:PATH"
}

if ($Persist) {
    [Environment]::SetEnvironmentVariable("ARONA_STEDGEAI_PATH", $selected, "User")
    [Environment]::SetEnvironmentVariable("STEDGEAI_CORE_DIR", $coreDirectory, "User")
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if (($userPath -split ";") -notcontains $toolDirectory) {
        [Environment]::SetEnvironmentVariable("PATH", "$toolDirectory;$userPath", "User")
    }
}

Write-Host "ARONA_STEDGEAI_PATH=$env:ARONA_STEDGEAI_PATH"
Write-Host "STEDGEAI_CORE_DIR=$env:STEDGEAI_CORE_DIR"
& $selected --version
