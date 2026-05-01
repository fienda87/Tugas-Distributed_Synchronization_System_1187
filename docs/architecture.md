# Arsitektur Sistem

## Ringkasan

`tugasDistribusi` adalah simulasi Distributed Synchronization System berbasis FastAPI, Redis, Docker Compose, pytest, dan Locust. Sistem berjalan sebagai beberapa node HTTP yang saling berkomunikasi di jaringan Docker `distnetv2`.

Komponen utama:

- Lock Manager dengan Raft.
- Distributed Queue dengan consistent hashing dan Redis persistence.
- Distributed Cache dengan MESI-style coherence, TTL, LRU, dan metrics.
- PBFT sebagai bonus consensus.
- Gateway untuk geo-routing dan adaptive load balancer.
- Security layer berupa API key, RBAC, audit log, dan enkripsi antar-node.

## Diagram Deployment

```text
                    Host Machine
                        |
        +---------------+----------------+
        | Docker network: distnetv2       |
        |                                |
        |  +---------+                   |
        |  | Redis   | redis:6379        |
        |  +----+----+                   |
        |       |                        |
        |  +----+--------------------+   |
        |  | Shared distributed state |   |
        |  +----+--------------------+   |
        |       |                        |
        |  Lock Manager                  |
        |  lock_a:9000 lock_b:9001 lock_c:9002
        |       | Raft request_vote / append_entries
        |                                |
        |  Distributed Queue             |
        |  queue_a:9100 queue_b:9101 queue_c:9102
        |       | publish_internal / consume_internal
        |                                |
        |  Distributed Cache             |
        |  cache_a:9200 cache_b:9201 cache_c:9202
        |       | invalidation / propagation
        |                                |
        |  Bonus Services                |
        |  gateway:9300                  |
        |  pbft_a:9400 pbft_b:9401 pbft_c:9402
        +--------------------------------+
```

Port yang diekspos ke host:

- Lock: `9000`, `9001`, `9002`
- Queue: `9100`, `9101`, `9102`
- Cache: `9200`, `9201`, `9202`
- Gateway: `9300`
- PBFT: `9400`, `9401`, `9402`
- Redis: `6379`

## Lock Manager

Lock manager berjalan pada 3 node: `lock_a`, `lock_b`, dan `lock_c`. Modul utama berada di `src/lock/lock_service.py`, sedangkan algoritma Raft berada di `src/consensus/raft.py`.

Fitur:

- Shared lock.
- Exclusive lock.
- Antrean lock saat resource sedang dipegang client lain.
- Deteksi deadlock melalui wait-for graph sederhana.
- Replikasi command lock melalui Raft.
- Endpoint role Raft untuk melihat leader/follower/candidate.

Alur ringkas:

1. Client mengirim `POST /lock/acquire`.
2. Jika node bukan leader, request diteruskan ke leader yang ditemukan dari cluster.
3. Leader mereplikasi command ke node lain dengan `append_entries`.
4. Jika mayoritas menerima, command diterapkan ke state machine lock.
5. Client mendapat status granted atau queued.

## Distributed Queue

Queue berjalan pada `queue_a`, `queue_b`, dan `queue_c`. Modul utama berada di `src/dist_queue/queue_service.py`.

Fitur:

- Consistent hashing untuk menentukan owner topic/key.
- Replikasi pesan sesuai `QUEUE_REPLICA_FACTOR`.
- Redis persistence untuk payload, owner, ready queue, dan inflight queue.
- At-least-once delivery melalui visibility timeout dan requeue expired message.
- Ack berbasis `msg_id`.

Alur publish:

1. Client memanggil `POST /queue/publish`.
2. Ring consistent hashing memilih owner node.
3. Node penerima menyimpan pesan lokal atau meneruskan ke owner lain via `/queue/publish_internal`.
4. Redis menyimpan payload dan daftar owner.

Alur consume:

1. Client memanggil `POST /queue/consume`.
2. Service mencoba owner yang sesuai topic/key.
3. Pesan dipindah dari ready queue ke inflight queue dengan deadline visibility timeout.
4. Jika tidak di-ack sebelum timeout, reaper mengembalikan pesan ke ready queue.

## Distributed Cache

Cache berjalan pada `cache_a`, `cache_b`, dan `cache_c`. Modul utama berada di `src/cache/cache_service.py`.

Fitur:

- MESI-style state untuk cache item.
- Invalidation/update propagation antar cache peer.
- TTL per item.
- LRU replacement berdasarkan kapasitas `CACHE_CAPACITY`.
- Metrics hit/miss melalui Prometheus counters.

Alur put/get:

1. `POST /cache/put` menyimpan key/value pada node penerima.
2. Node mengirim invalidation atau update ke peer.
3. `GET /cache/get` membaca dari cache lokal.
4. Item expired atau item lama dapat dihapus berdasarkan TTL dan LRU.

## PBFT

PBFT berada di `src/consensus/pbft.py` dan berjalan pada `pbft_a`, `pbft_b`, `pbft_c`.

Fitur:

- `pre_prepare` dari node penerima request.
- `prepare` broadcast ke peer.
- `commit` setelah quorum prepare.
- Status quorum, prepared, committed, dan decided.

Implementasi ini cukup untuk demonstrasi dasar PBFT pada 3 node.

## Geo Routing dan Adaptive Balancer

Gateway berjalan pada port `9300`.

Geo-routing:

- Endpoint `GET /geo/route`.
- Memilih region berdasarkan `REGION_MAP`.
- Simulasi latency-aware route untuk client region.

Adaptive balancer:

- Endpoint `POST /balancer/report`.
- Endpoint `GET /balancer/next`.
- Memakai data latency dan status OK untuk memilih node terbaik.

## Security

Security berada di `src/common/security.py`, `src/common/crypto.py`, dan `src/common/audit.py`.

Fitur:

- Header wajib: `X-API-Key`.
- Role:
  - `demo_admin`: admin.
  - `demo_writer`: writer.
  - `demo_reader`: reader.
- Internal node communication memakai `INTERNAL_API_KEY`.
- Enkripsi antar-node memakai AES-GCM jika `INTER_NODE_ENC=true`.
- Audit log dan hash chain untuk pencatatan aktivitas.

## Observability

Endpoint observability:

- `GET /health`
- `GET /readyz`
- `GET /metrics`

Metrics menggunakan `prometheus_client` dan mencatat request, latency, queue publish/ack, cache hit/miss, serta Raft append/term.
