#!/usr/bin/env pwsh
$env:API_KEY = "demo_writer"
$env:LOCK_LEADER = "http://127.0.0.1:9000"
$env:QUEUE_PRIMARY = "http://127.0.0.1:9100"
$env:QUEUE_REPLICA = "http://127.0.0.1:9102"
$env:CACHE_A = "http://127.0.0.1:9200"
$env:CACHE_B = "http://127.0.0.1:9201"
$env:PBFT_NODE = "http://127.0.0.1:9400"
$env:GATEWAY = "http://127.0.0.1:9300"

Write-Host "Running integration tests..."
python -m pytest -v .\tests\integration
