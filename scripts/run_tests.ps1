param(
    [switch]$SkipDocker,
    [switch]$WithLocust,
    [switch]$Down,
    [int]$Users = 20,
    [int]$SpawnRate = 5,
    [string]$RunTime = "30s"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Compose = Join-Path $Root "docker\docker-compose.yml"
$Requirements = Join-Path $Root "requirements.txt"

function Test-PythonModule {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModuleName
    )

    python -c "import $ModuleName" *> $null
    return $LASTEXITCODE -eq 0
}

function Ensure-PythonDeps {
    param(
        [string[]]$Modules
    )

    $missing = @()
    foreach ($module in $Modules) {
        if (-not (Test-PythonModule $module)) {
            $missing += $module
        }
    }

    if ($missing.Count -eq 0) {
        return
    }

    Write-Host "Installing missing Python modules: $($missing -join ', ')"
    python -m pip install -r $Requirements

    $stillMissing = @()
    foreach ($module in $Modules) {
        if (-not (Test-PythonModule $module)) {
            $stillMissing += $module
        }
    }

    if ($stillMissing.Count -gt 0) {
        throw "Python modules masih belum tersedia: $($stillMissing -join ', ')"
    }
}

function Set-TestEnv {
    $env:API_KEY = "demo_writer"
    $env:LOCK_LEADER = "http://127.0.0.1:9000"
    $env:QUEUE_PRIMARY = "http://127.0.0.1:9100"
    $env:QUEUE_REPLICA = "http://127.0.0.1:9102"
    $env:CACHE_A = "http://127.0.0.1:9200"
    $env:CACHE_B = "http://127.0.0.1:9201"
    $env:PBFT_NODE = "http://127.0.0.1:9400"
    $env:GATEWAY = "http://127.0.0.1:9300"
    $env:QUEUE_HOST = $env:QUEUE_REPLICA
    $env:CACHE_HOST = $env:CACHE_A
    $env:LOCK_HOST = $env:LOCK_LEADER
}

function Wait-Ready {
    param(
        [string[]]$Urls,
        [int]$TimeoutSeconds = 180
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $allReady = $true
        foreach ($url in $Urls) {
            try {
                $resp = curl.exe -s --max-time 5 "$url/readyz" | ConvertFrom-Json
                if ($LASTEXITCODE -ne 0 -or -not $resp.ready) {
                    $allReady = $false
                    break
                }
            }
            catch {
                $allReady = $false
                break
            }
        }

        if ($allReady) {
            return
        }
        Start-Sleep -Seconds 2
    }

    throw "Services were not ready after $TimeoutSeconds seconds."
}

Push-Location $Root
try {
    Set-TestEnv
    $requiredModules = @("pytest")
    if ($WithLocust) {
        $requiredModules += "locust"
    }
    Ensure-PythonDeps $requiredModules

    if (-not $SkipDocker) {
        Write-Host "[1/4] Starting Docker stack..."
        docker compose -f $Compose up -d --build
    }

    Write-Host "[2/4] Waiting for services..."
    Wait-Ready @(
        $env:LOCK_LEADER,
        $env:QUEUE_PRIMARY,
        $env:QUEUE_REPLICA,
        $env:CACHE_A,
        $env:CACHE_B,
        $env:PBFT_NODE,
        $env:GATEWAY
    )

    Write-Host "Waiting 15 seconds for Raft Leader Election & Cluster Stabilization..."
    Start-Sleep -Seconds 15

    Write-Host "[3/4] Running pytest integration suite..."
    python -m pytest -q .\tests\integration

    if ($WithLocust) {
        Write-Host "[4/4] Running Locust headless benchmark..."
        python -m locust -f .\benchmarks\load_test_v2.py --headless -u $Users -r $SpawnRate -t $RunTime
    }
    else {
        Write-Host "[4/4] Locust skipped. Add -WithLocust to run it."
    }
}
finally {
    if ($Down) {
        Write-Host "Stopping Docker stack..."
        docker compose -f $Compose down
    }
    Pop-Location
}
