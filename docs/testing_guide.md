# Panduan Testing Lengkap

Panduan ini menjelaskan cara menguji semua fitur utama proyek `tugasDistribusi`: Docker cluster, readiness, lock manager, queue, cache coherence, bonus PBFT/geo/ML/security, pytest, dan Locust. Perintah disusun untuk PowerShell di Windows.

## 1. Persiapan

Masuk ke folder proyek:

```powershell
cd C:\Users\acerr\Documents\sister\tugasDistribusi
```

Install dependency Python jika belum:

```powershell
python -m pip install -r .\requirements.txt
```

Jalankan Docker stack:

```powershell
docker compose -f .\docker\docker-compose.yml up -d --build
```

Cek container:

```powershell
docker compose -f .\docker\docker-compose.yml ps
```

Output yang diharapkan:

```text
docker-lock_a-1    Up    0.0.0.0:9000->9000/tcp
docker-lock_b-1    Up    0.0.0.0:9001->9001/tcp
docker-lock_c-1    Up    0.0.0.0:9002->9002/tcp
docker-queue_a-1   Up    0.0.0.0:9100->9100/tcp
docker-queue_b-1   Up    0.0.0.0:9101->9101/tcp
docker-queue_c-1   Up    0.0.0.0:9102->9102/tcp
docker-cache_a-1   Up    0.0.0.0:9200->9200/tcp
docker-cache_b-1   Up    0.0.0.0:9201->9201/tcp
docker-cache_c-1   Up    0.0.0.0:9202->9202/tcp
docker-gateway-1   Up    0.0.0.0:9300->9300/tcp
docker-pbft_a-1    Up    0.0.0.0:9400->9400/tcp
docker-redis-1     Up    0.0.0.0:6379->6379/tcp
```

Siapkan API key:

```powershell
$h = @{ "X-API-Key" = "demo_writer" }
```

## 2. Health dan Readiness

```powershell
curl.exe -s http://127.0.0.1:9000/readyz
curl.exe -s http://127.0.0.1:9100/readyz
curl.exe -s http://127.0.0.1:9200/readyz
curl.exe -s http://127.0.0.1:9300/readyz
curl.exe -s http://127.0.0.1:9400/readyz
```

Output yang diharapkan:

```json
{"ready":true}
```

## 3. Script Otomatis: Docker + Pytest + Locust

Script utama:

```powershell
.\scripts\run_tests.ps1
```

Mode yang tersedia:

```powershell
.\scripts\run_tests.ps1
.\scripts\run_tests.ps1 -SkipDocker
.\scripts\run_tests.ps1 -SkipDocker -WithLocust -Users 20 -SpawnRate 5 -RunTime 1m
.\scripts\run_tests.ps1 -Down
```

Fungsi script:

- Menyalakan Docker Compose jika tidak memakai `-SkipDocker`.
- Menunggu endpoint `/readyz`.
- Mengisi environment variable untuk pytest dan Locust.
- Menginstall modul Python yang hilang dari `requirements.txt`.
- Menjalankan `python -m pytest -q .\tests\integration`.
- Menjalankan `python -m locust` jika memakai `-WithLocust`.

Output pytest yang pernah didapat pada run bersih:

```text
5 passed in 8.80s
```

Output Locust yang pernah didapat untuk 20 user, 1 menit:

```text
Aggregated 4605 requests, 389 failures, avg 219 ms, median 120 ms, max 2725 ms, 78.93 req/s
```

Catatan: failure Locust terutama berasal dari `lock:acquire` saat banyak user melakukan exclusive lock secara bersamaan. Ini menunjukkan bottleneck contention lock, bukan berarti semua fitur core gagal.

## 4. A. Distributed Lock Manager

### A1. Raft Role dan 3 Node

```powershell
curl.exe -s http://127.0.0.1:9000/raft/role
curl.exe -s http://127.0.0.1:9001/raft/role
curl.exe -s http://127.0.0.1:9002/raft/role
```

Output yang diharapkan:

```json
{"role":"leader","leader":"lock_a"}
{"role":"follower","leader":"lock_a"}
{"role":"follower","leader":"lock_a"}
```

Leader bisa berbeda, tetapi minimal harus ada satu leader yang stabil.

### A2. Exclusive Lock

```powershell
$body = @{
  resource = "file-1"
  mode = "exclusive"
  client_id = "cli-1"
  timeout_ms = 2000
} | ConvertTo-Json -Compress

$ex = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9000/lock/acquire" `
  -Headers $h `
  -ContentType "application/json" `
  -Body $body

$ex
$tok = $ex.token
```

Output yang diharapkan:

```text
granted : True
token   : lk1
mode    : exclusive
```

Cek state:

```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:9000/lock/state?resource=file-1" `
  -Headers $h
```

Release:

```powershell
$rel = @{ resource = "file-1"; token = $tok } | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9000/lock/release" `
  -Headers $h `
  -ContentType "application/json" `
  -Body $rel
```

Output yang diharapkan:

```text
released : True
```

### A3. Shared Lock

```powershell
$s1 = @{ resource = "file-shared"; mode = "shared"; client_id = "cli-2"; timeout_ms = 2000 } | ConvertTo-Json -Compress
$s2 = @{ resource = "file-shared"; mode = "shared"; client_id = "cli-3"; timeout_ms = 2000 } | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9000/lock/acquire" -Headers $h -ContentType "application/json" -Body $s1
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9000/lock/acquire" -Headers $h -ContentType "application/json" -Body $s2
```

Output yang diharapkan:

```text
granted : True
mode    : shared
```

### A4. Queueing Shared Setelah Exclusive

```powershell
$exBody = @{ resource = "file-queue"; mode = "exclusive"; client_id = "owner"; timeout_ms = 2000 } | ConvertTo-Json -Compress
$ex = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9000/lock/acquire" -Headers $h -ContentType "application/json" -Body $exBody

$waitBody = @{ resource = "file-queue"; mode = "shared"; client_id = "waiter"; timeout_ms = 2000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9000/lock/acquire" -Headers $h -ContentType "application/json" -Body $waitBody
```

Output yang diharapkan untuk request kedua:

```text
granted : False
queued  : True
```

Release owner:

```powershell
$rel = @{ resource = "file-queue"; token = $ex.token } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9000/lock/release" -Headers $h -ContentType "application/json" -Body $rel
```

### A5. Deadlock Detection

```powershell
$a1 = @{ resource = "R1"; mode = "exclusive"; client_id = "A"; timeout_ms = 2000 } | ConvertTo-Json -Compress
$b1 = @{ resource = "R2"; mode = "exclusive"; client_id = "B"; timeout_ms = 2000 } | ConvertTo-Json -Compress

$tokA = (Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9000/lock/acquire" -Headers $h -ContentType "application/json" -Body $a1).token
$tokB = (Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9000/lock/acquire" -Headers $h -ContentType "application/json" -Body $b1).token

$aWait = @{ resource = "R2"; mode = "exclusive"; client_id = "A"; timeout_ms = 2000 } | ConvertTo-Json -Compress
$bWait = @{ resource = "R1"; mode = "exclusive"; client_id = "B"; timeout_ms = 2000 } | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9000/lock/acquire" -Headers $h -ContentType "application/json" -Body $aWait
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9000/lock/acquire" -Headers $h -ContentType "application/json" -Body $bWait

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9000/lock/deadlock" -Headers $h -ContentType "application/json" -Body "{}"
```

Output yang diharapkan:

```text
deadlock : True
```

Jika resource sudah pernah dipakai dari run lama, gunakan nama resource unik seperti `R1_001`.

### A6. Network Partition Scenario

Putuskan satu follower dari network Docker:

```powershell
$cid = docker compose -f .\docker\docker-compose.yml ps -q lock_b
$net = (docker inspect -f "{{json .NetworkSettings.Networks}}" $cid | ConvertFrom-Json).psobject.Properties.Name | Select-Object -First 1
docker network disconnect $net $cid
```

Cek role:

```powershell
curl.exe -s http://127.0.0.1:9000/raft/role
curl.exe -s http://127.0.0.1:9001/raft/role
curl.exe -s http://127.0.0.1:9002/raft/role
```

Sambungkan kembali:

```powershell
docker network connect $net $cid
```

Ekspektasi:

- Majority partition tetap bisa memiliki leader.
- Node yang diputus mungkin gagal menjawab request internal.
- Setelah reconnect, node kembali ikut cluster.

## 5. B. Distributed Queue System

### B1. Consistent Hashing Owner

```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:9100/queue/owners?topic=alpha&key=user42" `
  -Headers $h
```

Output yang diharapkan:

```text
owners : {http://queue_b:9101, http://queue_a:9100}
self   : http://queue_a:9100
```

Owner bisa berbeda tergantung hash ring.

### B2. Publish, Consume, Ack Owner

Publish 5 pesan:

```powershell
1..5 | ForEach-Object {
  Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:9100/queue/publish?topic=alpha&key=user42" `
    -Headers $h `
    -ContentType "application/json" `
    -Body (@{ n = $_ } | ConvertTo-Json -Compress)
}
```

Consume dari replica:

```powershell
$items = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9102/queue/consume?topic=alpha&key=user42&visibility_ttl=3000&max=10" `
  -Headers $h

$items | Format-Table
```

Output yang diharapkan:

```text
msg_id                            owner                 payload
------                            -----                 -------
...                               http://queue_b:9101   @{n=1}
```

Ack semua item:

```powershell
foreach ($m in @($items)) {
  $owner = [uri]::EscapeDataString($m.owner)
  Invoke-RestMethod -Method Post `
    -Uri ("http://127.0.0.1:9102/queue/ack_owner?topic=alpha&owner={0}&msg_id={1}" -f $owner, $m.msg_id) `
    -Headers $h
}
```

Output yang diharapkan:

```text
acked : True
```

### B3. At-least-once Delivery

Publish satu pesan:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9100/queue/publish?topic=retry&key=u1" `
  -Headers $h `
  -ContentType "application/json" `
  -Body '{"n":1}'
```

Consume tanpa ack:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9102/queue/consume?topic=retry&key=u1&visibility_ttl=3000&max=1" `
  -Headers $h
```

Tunggu TTL, lalu consume lagi:

```powershell
Start-Sleep -Seconds 4
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9102/queue/consume?topic=retry&key=u1&visibility_ttl=3000&max=1" `
  -Headers $h
```

Output yang diharapkan:

```text
Pesan yang sama muncul lagi karena belum di-ack.
```

### B4. Persistence dan Recovery

Publish pesan:

```powershell
1..3 | ForEach-Object {
  Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:9100/queue/publish?topic=persist&key=u1" `
    -Headers $h `
    -ContentType "application/json" `
    -Body (@{ n = $_ } | ConvertTo-Json -Compress)
}
```

Restart queue node:

```powershell
docker compose -f .\docker\docker-compose.yml restart queue_a
```

Consume setelah node hidup kembali:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9100/queue/consume?topic=persist&key=u1&visibility_ttl=5000&max=10" `
  -Headers $h
```

Ekspektasi:

- Pesan tetap tersedia karena payload dan owner disimpan di Redis.
- Jika owner berbeda, consume dari queue node lain seperti `9102`.

## 6. C. Distributed Cache Coherence

### C1. Put dan Get Antar Node

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9200/cache/put" `
  -Headers $h `
  -ContentType "application/json" `
  -Body '{"key":"k1","value":"v1"}'

Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:9201/cache/get?key=k1" `
  -Headers $h
```

Output yang diharapkan:

```text
hit   : True
key   : k1
value : v1
```

### C2. Invalidation dan Update Propagation

Update dari node A:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9200/cache/put" `
  -Headers $h `
  -ContentType "application/json" `
  -Body '{"key":"k1","value":"v2"}'
```

Baca dari node B:

```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:9201/cache/get?key=k1" `
  -Headers $h
```

Output yang diharapkan:

```text
value : v2
```

### C3. TTL Expiration

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9200/cache/put?ttl_ms=1000" `
  -Headers $h `
  -ContentType "application/json" `
  -Body '{"key":"temp","value":"123"}'

Start-Sleep -Seconds 2

Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:9200/cache/get?key=temp" `
  -Headers $h
```

Output yang diharapkan:

```text
hit : False
```

### C4. LRU dan Metrics

Isi banyak key untuk mendorong LRU:

```powershell
1..700 | ForEach-Object {
  Invoke-RestMethod -Method Post `
    -Uri "http://127.0.0.1:9200/cache/put" `
    -Headers $h `
    -ContentType "application/json" `
    -Body (@{ key = "k$_"; value = $_ } | ConvertTo-Json -Compress)
}
```

Cek metrics:

```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:9200/cache/metrics" `
  -Headers $h
```

Ekspektasi:

- Metrics hit/miss bertambah setelah get.
- Jumlah item tidak tumbuh tanpa batas karena ada kapasitas cache dan LRU.

## 7. D. Bonus Features

### D1. PBFT

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9400/pbft/request" `
  -Headers $h `
  -ContentType "application/json" `
  -Body '{"op":"set","k":"x","v":1}'

Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:9400/pbft/status" `
  -Headers $h
```

Output yang diharapkan:

```text
accepted : True
decided  : True
quorum   : 2
```

Jika PBFT lambat setelah stress test Locust, restart stack Docker terlebih dahulu.

### D2. Geo Routing

```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:9300/geo/route?client_region=us-east" `
  -Headers $h
```

Output yang diharapkan:

```text
region atau route terbaik berdasarkan latency map.
```

### D3. Adaptive Load Balancer

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9300/balancer/report" `
  -Headers $h `
  -ContentType "application/json" `
  -Body '{"node":"n1","latency_ms":120,"ok":true}'

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9300/balancer/report" `
  -Headers $h `
  -ContentType "application/json" `
  -Body '{"node":"n2","latency_ms":220,"ok":true}'

Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:9300/balancer/next?nodes=n1,n2" `
  -Headers $h
```

Output yang diharapkan:

```text
selected node cenderung n1 karena latency lebih rendah.
```

### D4. Security dan RBAC

Request tanpa API key:

```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:9100/queue/owners?topic=alpha"
```

Output yang diharapkan:

```text
401 missing_api_key
```

Request memakai API key:

```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:9100/queue/owners?topic=alpha" `
  -Headers @{ "X-API-Key" = "demo_reader" }
```

Output yang diharapkan:

```text
owners : {...}
self   : http://queue_a:9100
```

## 8. Pytest Per Fitur

Jalankan semua test:

```powershell
python -m pytest -q .\tests\integration
```

Jalankan per fitur:

```powershell
python -m pytest -q .\tests\integration\test_lock_basic.py
python -m pytest -q .\tests\integration\test_queue_e2e.py
python -m pytest -q .\tests\integration\test_cache_coherence.py
python -m pytest -q .\tests\integration\test_pbft_full.py
python -m pytest -q .\tests\integration\test_geo_ml.py
```

Output yang diharapkan:

```text
5 passed
```

Jika ada `skipped`, biasanya service belum ready. Jika ada timeout setelah Locust, restart Docker stack.

## 9. Locust Benchmark

Headless:

```powershell
.\scripts\run_tests.ps1 -SkipDocker -WithLocust -Users 20 -SpawnRate 5 -RunTime 1m
```

Manual:

```powershell
$env:API_KEY = "demo_writer"
$env:QUEUE_HOST = "http://127.0.0.1:9102"
$env:CACHE_HOST = "http://127.0.0.1:9200"
$env:LOCK_HOST = "http://127.0.0.1:9000"

python -m locust -f .\benchmarks\load_test_v2.py --headless -u 20 -r 5 -t 1m
```

Output ringkas yang pernah didapat:

```text
Aggregated 4605 requests
389 failures
Average latency 219 ms
Median latency 120 ms
Max latency 2725 ms
Throughput 78.93 req/s
```

Interpretasi:

- Cache stabil: `cache:get` dan `cache:put` 0 failure.
- Queue relatif stabil: `queue:ack_owner` 0 failure, `queue:publish` failure kecil.
- Lock menjadi bottleneck saat exclusive lock berkompetisi tinggi.

## 10. Kesesuaian dengan Instruksi Tugas 2

| Requirement | Status | Cara Testing |
| --- | --- | --- |
| Raft distributed lock | Sudah | `/raft/role`, `/lock/acquire`, pytest lock |
| Minimum 3 lock nodes | Sudah | `docker compose ps`, port 9000-9002 |
| Shared/exclusive locks | Sudah | A2 dan A3 |
| Network partition scenario | Ada skenario uji | A6 |
| Deadlock detection | Sudah | A5, `/lock/deadlock` |
| Queue consistent hashing | Sudah | B1, `/queue/owners` |
| Multiple producers/consumers | Sudah | B2, Locust QueueUser |
| Persistence/recovery | Sudah sebagian | B4, Redis volume |
| Node failure tanpa kehilangan data | Sudah sebagian | B4 dan replica owner |
| At-least-once delivery | Sudah | B3 visibility timeout |
| MESI cache coherence | Sudah | C1 dan C2 |
| Multiple cache nodes | Sudah | port 9200-9202 |
| Invalidation/update propagation | Sudah | C2 |
| LRU/LFU replacement | Sudah LRU | C4 |
| Metrics collection | Sudah | `/metrics`, `/cache/metrics` |
| Dockerfile dan Compose | Sudah | `docker/Dockerfile.node`, `docker-compose.yml` |
| Dynamic scaling | Didukung manual | tambah service/port/peer di Compose |
| `.env` configuration | Sudah | `.env.example` |
| Technical documentation | Sudah | `docs/architecture.md`, `docs/api_spec.yaml`, `docs/deployment_guide.md` |
| Performance report | Sudah | `docs/report_tugas_distribusi.pdf` |
| Pytest dan Locust | Sudah | script dan command di atas |
| Video YouTube | Belum di repo | perlu dibuat dan link ditempel di README/report |

Kesimpulan: proyek sudah menjawab mayoritas instruksi Tugas 2 untuk core functionality, testing, Docker, Redis, dokumentasi, dan performance analysis. Bagian yang masih perlu dilengkapi untuk pengumpulan adalah video YouTube publik, screenshot hasil test, dan link repository/pengumpulan.
