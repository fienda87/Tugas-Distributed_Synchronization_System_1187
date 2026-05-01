# Deployment Guide

## Prasyarat

- Docker Desktop.
- Docker Compose.
- Python 3.10+.
- PowerShell.

Install dependency lokal untuk pytest dan Locust:

```powershell
python -m pip install -r .\requirements.txt
```

## Konfigurasi Environment

Contoh konfigurasi tersedia di `.env.example`.

Nilai penting:

```dotenv
ROLE=lock
NODE_ID=lock_a
HTTP_PORT=9000
CLUSTER_NODES=http://lock_a:9000,http://lock_b:9001,http://lock_c:9002
CLUSTER_PEERS=http://queue_a:9100,http://queue_b:9101,http://queue_c:9102
REDIS_URL=redis://redis:6379/0
AUTH_ENABLED=true
API_KEYS=demo_admin:admin,demo_writer:writer,demo_reader:reader
INTERNAL_API_KEY=demo_admin
INTER_NODE_ENC=true
```

Docker Compose sudah mengisi environment per service, sehingga file `.env.example` dipakai sebagai referensi konfigurasi.

## Menjalankan Docker Stack

Dari folder `tugasDistribusi`:

```powershell
docker compose -f .\docker\docker-compose.yml up -d --build
```

Cek container:

```powershell
docker compose -f .\docker\docker-compose.yml ps
```

Matikan stack:

```powershell
docker compose -f .\docker\docker-compose.yml down
```

Hapus volume Redis jika ingin state bersih:

```powershell
docker compose -f .\docker\docker-compose.yml down -v
```

## Health Check

```powershell
curl.exe -s http://127.0.0.1:9000/readyz
curl.exe -s http://127.0.0.1:9100/readyz
curl.exe -s http://127.0.0.1:9200/readyz
curl.exe -s http://127.0.0.1:9300/readyz
curl.exe -s http://127.0.0.1:9400/readyz
```

Response sukses:

```json
{"ready":true}
```

## Menjalankan Test Otomatis

Skrip PowerShell utama:

```powershell
.\scripts\run_tests.ps1
```

Mode yang tersedia:

```powershell
.\scripts\run_tests.ps1 -SkipDocker
.\scripts\run_tests.ps1 -WithLocust
.\scripts\run_tests.ps1 -WithLocust -Users 50 -SpawnRate 10 -RunTime 1m
.\scripts\run_tests.ps1 -Down
```

Test terakhir yang sudah diverifikasi:

```text
5 passed in 9.54s
```

## Menjalankan Pytest Manual

```powershell
$env:API_KEY = "demo_writer"
$env:LOCK_LEADER = "http://127.0.0.1:9000"
$env:QUEUE_PRIMARY = "http://127.0.0.1:9100"
$env:QUEUE_REPLICA = "http://127.0.0.1:9102"
$env:CACHE_A = "http://127.0.0.1:9200"
$env:CACHE_B = "http://127.0.0.1:9201"
$env:PBFT_NODE = "http://127.0.0.1:9400"
$env:GATEWAY = "http://127.0.0.1:9300"

python -m pytest -q .\tests\integration
```

## Menjalankan Locust Manual

Headless benchmark:

```powershell
$env:API_KEY = "demo_writer"
$env:QUEUE_HOST = "http://127.0.0.1:9102"
$env:CACHE_HOST = "http://127.0.0.1:9200"
$env:LOCK_HOST = "http://127.0.0.1:9000"

locust -f .\benchmarks\load_test_v2.py --headless -u 20 -r 5 -t 30s
```

Web UI Locust:

```powershell
locust -f .\benchmarks\load_test_v2.py
```

Lalu buka:

```text
http://127.0.0.1:8089
```

## Contoh Request API

Header API key:

```powershell
$h = @{ "X-API-Key" = "demo_writer" }
```

Acquire exclusive lock:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9000/lock/acquire" `
  -Headers $h `
  -ContentType "application/json" `
  -Body '{"resource":"r1","mode":"exclusive","client_id":"c1","timeout_ms":2000}'
```

Publish queue:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9100/queue/publish?topic=alpha&key=user-1" `
  -Headers $h `
  -ContentType "application/json" `
  -Body '{"n":1}'
```

Put cache:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9200/cache/put" `
  -Headers $h `
  -ContentType "application/json" `
  -Body '{"key":"k1","value":"v1"}'
```

## Scaling Node

Compose file sudah mendefinisikan 3 node untuk lock, queue, cache, dan PBFT. Untuk scaling dinamis, tambahkan service baru dengan:

- `NODE_ID` unik.
- `HTTP_PORT` unik.
- URL node baru pada `CLUSTER_NODES` atau `CLUSTER_PEERS`.
- Port mapping baru pada host.

Setelah mengubah compose:

```powershell
docker compose -f .\docker\docker-compose.yml up -d --build
```

## Troubleshooting

Jika test skip semua:

- Pastikan container sudah running.
- Cek `/readyz` pada port utama.
- Jalankan ulang dengan `.\scripts\run_tests.ps1 -SkipDocker`.

Jika request internal timeout:

- Pastikan hostname di `CLUSTER_NODES` dan `CLUSTER_PEERS` sama dengan nama service Compose, misalnya `lock_a`, bukan `lock-a`.

Jika data lama mengganggu test:

```powershell
docker compose -f .\docker\docker-compose.yml down -v
docker compose -f .\docker\docker-compose.yml up -d --build
```

Jika Docker port bentrok:

- Cek proses yang memakai port `9000-9402` atau ubah mapping port di compose.

Jika API mengembalikan 401/403:

- Pastikan request memakai header `X-API-Key`.
- Gunakan `demo_writer` untuk write endpoint dan `demo_reader` untuk read endpoint.
