# Tugas Distribusi - Distributed Synchronization System v2
**Link laporan : https://drive.google.com/file/d/1IS3WWIe6Vyfd531fIvDPAsyPNWaTfIZ-/view?usp=sharing
**Link video youtube: https://youtu.be/E2Wx7unRsoc

Implementasi sistem sinkronisasi terdistribusi berbasis FastAPI, Redis, Docker Compose, pytest, dan Locust. Proyek ini memuat lock manager, distributed queue, cache terdistribusi, PBFT, geo-routing, adaptive balancer, autentikasi API key, audit, dan enkripsi antar-node.

## Komponen

- **Lock Manager**: shared/exclusive lock, antrean lock, deteksi deadlock, dan role Raft.
- **Distributed Queue**: publish, consume, ack, owner-based ack, consistent hashing, replikasi, dan Redis persistence.
- **Distributed Cache**: MESI-style invalidation, LRU capacity, TTL, dan metrics.
- **Bonus**: PBFT request/status, geo-routing, ML/adaptive load balancer, RBAC, audit log, dan inter-node encryption.

## Struktur Proyek

```text
tugasDistribusi/
  benchmarks/              # skenario Locust
  docker/                  # Dockerfile dan docker-compose
  scripts/                 # helper PowerShell dan certificate generator
  src/                     # aplikasi dan modul service
  tests/integration/       # test integrasi pytest
  requirements.txt
```

## Prasyarat

- Docker Desktop dengan Docker Compose.
- Python 3.10+.
- Dependency Python:

```powershell
python -m pip install -r .\requirements.txt
```

## Menjalankan Cluster

Dari folder `tugasDistribusi`:

```powershell
docker compose -f .\docker\docker-compose.yml up -d --build
```

Health check utama:

```powershell
curl.exe -s http://127.0.0.1:9000/readyz
curl.exe -s http://127.0.0.1:9100/readyz
curl.exe -s http://127.0.0.1:9200/readyz
curl.exe -s http://127.0.0.1:9300/readyz
curl.exe -s http://127.0.0.1:9400/readyz
```

Matikan cluster:

```powershell
docker compose -f .\docker\docker-compose.yml down
```

## API Key

Semua request memakai header `X-API-Key`.

- `demo_admin`: akses admin/internal.
- `demo_writer`: akses write.
- `demo_reader`: akses read.

Contoh publish queue:

```powershell
$h = @{ "X-API-Key" = "demo_writer" }
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:9100/queue/publish?topic=alpha&key=user-1" `
  -Headers $h `
  -ContentType "application/json" `
  -Body '{"n":1}'
```

## Endpoint Ringkas

Lock:

- `POST /lock/acquire`
- `POST /lock/release`
- `POST /lock/deadlock`
- `GET /lock/state`
- `GET /raft/role`

Queue:

- `POST /queue/publish`
- `POST /queue/consume`
- `POST /queue/ack`
- `POST /queue/ack_owner`
- `GET /queue/owners`

Cache:

- `POST /cache/put`
- `GET /cache/get`
- `GET /cache/state`
- `GET /cache/metrics`

Bonus:

- `POST /pbft/request`
- `GET /pbft/status`
- `GET /geo/route`
- `POST /balancer/report`
- `GET /balancer/next`

## Skrip Run/Test PowerShell

Skrip utama ada di `scripts\run_tests.ps1`. Skrip ini menjalankan Docker Compose, mengisi environment variable test, menjalankan pytest, dan opsional menjalankan Locust.

Jalankan Docker + pytest:

```powershell
.\scripts\run_tests.ps1
```

Jalankan pytest saja jika cluster sudah hidup:

```powershell
.\scripts\run_tests.ps1 -SkipDocker
```

Jalankan Docker + pytest + Locust headless 30 detik:

```powershell
.\scripts\run_tests.ps1 -WithLocust
```

Atur durasi dan beban Locust:

```powershell
.\scripts\run_tests.ps1 -WithLocust -Users 50 -SpawnRate 10 -RunTime 1m
```

Jalankan test lalu matikan cluster:

```powershell
.\scripts\run_tests.ps1 -Down
```

## Perintah Manual Test

Jika ingin menjalankan tanpa skrip:

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

Locust manual:

```powershell
$env:API_KEY = "demo_writer"
$env:QUEUE_HOST = "http://127.0.0.1:9102"
$env:CACHE_HOST = "http://127.0.0.1:9200"
$env:LOCK_HOST = "http://127.0.0.1:9000"

locust -f .\benchmarks\load_test_v2.py --headless -u 20 -r 5 -t 30s
```
