# Databases — CT 112

`db.servers.baig.network` → `10.10.20.4`. Native packages, **no Docker** — one
shared page cache instead of five container layers, and each engine tuned
against the real 6 GB.

| Engine | Version | Port | Was on Mac mini | Memory budget |
|---|---|---|---|---|
| PostgreSQL | 17.11 | 5432 | 13.21 | `shared_buffers` 1 GB |
| MariaDB | 11.8.6 | 3306 | 10.11.4 | `innodb_buffer_pool_size` 1500 MB |
| Percona MongoDB | 8.0.32-14 | 27017 | 8.0.8-3 | WiredTiger cache 1 GB |
| Redis | 8.0.2 | 6379 | 7 | `maxmemory` 256 MB |
| CouchDB | 3.5.2 | 5984 | — new | default |

All five are `enabled` on boot and verified to return after a container reboot.

## What each one holds

### PostgreSQL

| Database | Owner | Rows | Notes |
|---|---|---|---|
| `wiki` | postgres | 32 tables | Wiki.js — **content extracted, safe to drop** |
| `yamtrack` | postgres | 8,757 items | recovered from a hidden SQLite — see below |
| `hive` | **hive** | 9 tables | |
| `speedtest` | **speedtest** | 16 tables | |

Three more databases belong to a private work test stack and are not listed here.

`hive` and `speedtest` are owned by their own roles, matching the source. They
were restored *as* those roles over TCP — `su - hive` cannot work, because they
are PostgreSQL roles, not Linux users.

**Not restored**, dumps retained in `/var/tmp/migration`:

- `openvpn_monitor` (44 MB) — dies with the Raspberry Pi
- two work databases awaiting a keep/drop decision

### MariaDB

Databases for a private work test stack — 522 tables, about 4.2 GB.

### MongoDB

Only `DAU` (134 MB). `admin`, `config` and `local` are server internals.
Auth is enforced; anonymous access returns an error.

### Redis

38 keys — `db0` 8, `db3` 30. Effectively a cache.

### CouchDB

Backs **Obsidian Self-hosted LiveSync**. Database `obsidian`. Reachable at
https://obsidian.baig.network through the proxy, which supplies TLS.
Anonymous requests get 401.

## Migration status

> [!IMPORTANT]
> **This is a staged copy, not a cutover**
> Applications still point at the Mac mini. Both copies have been diverging
> since the restore. The write-heavy work schemas need a **delta re-dump** at actual
> cutover.

The restore was verified by exact `COUNT(*)` on every table, both sides:

```
source tables: 723   target tables: 723
identical:     723
mismatches:    none
total rows:    22,661,265  (both sides)
```

Mongo and Redis matched exactly too.

> [!NOTE]
> **Why estimates were not good enough**
> A first comparison using `pg_stat_user_tables.n_live_tup` and
> `information_schema.table_rows` showed 214 "mismatches". Both are estimates
> and disagreed purely on statistics age. Exact counts settled it. Do not trust
> either figure when verifying a migration.

### Architecture forced logical dumps

The Mac mini is **aarch64** (Apple Silicon); Proxmox is **amd64**. Data
directories are not portable between them — `/var/lib/postgresql/data` and
`/var/lib/mysql` cannot be copied. Logical dumps (`pg_dump -Fc`,
`mariadb-dump`, `mongodump`) were the only option, and they were run **from CT
112 pulling over the network**, which is the supported direction (newer client,
older server) and skips staging 6 GB on the Mac mini.

## Accounts

Kept at parity with the Mac mini so cutover stays a single variable. **Rotate
after cutover, not during.** Passwords live in the private secrets repo.

| Engine | User | Notes |
|---|---|---|
| PostgreSQL | `postgres` | plus roles `hive`, `speedtest` |
| MariaDB | `root` | local only — `root@'%'` was deliberately not recreated |
| MariaDB | an application account | original password hash carried across; `10.10.%` added because the old `192.168.%` grant could never match after the VLAN move |
| MongoDB | `admin` | |
| CouchDB | `admin` | generated 24-char password |
| Monitoring | `exporter` | read-only, both Postgres and MariaDB |
| MariaDB admin | `ahmed@'10.10.%'` | full privileges, lab subnets only |

> [!NOTE]
> **You cannot connect to MariaDB as root remotely, by design**
> `root` is `localhost` only — the Mac mini had `root@'%'` reachable from the
> whole flat network and recreating that was the wrong default. Remote
> administration uses `ahmed@'10.10.%'` instead:
>
> ```bash
> mariadb -h db.servers.baig.network -u ahmed -p
> ```
>
> `Access denied for user 'root'@'macmini.servers.baig.network'` is this working
> as intended, not a fault.

> [!WARNING]
> **Giving root a password broke socket logins**
> Setting `root@localhost` to `mysql_native_password` for parity means a bare
> `mariadb` command no longer authenticates via unix socket. Every script needs
> `-u root -p<password>`. This silently broke the first restore attempt.

## TLS

All engines present the wildcard certificate, which now covers
`*.servers.baig.network`, so `db.servers.baig.network` validates properly.

TLS is **offered, not enforced** — no user has `REQUIRE SSL` and `pg_hba` still
accepts non-TLS from the Servers and Trusted VLANs, so existing clients are
unaffected. Clients that want it can use `sslmode=require` or `--ssl`.

Certificates are redistributed from CT 111 by `/root/distribute-certs.sh` on the
Proxmox host, run daily at 03:23. It compares fingerprints and does nothing
when they already match.

> [!NOTE]
> **PostgreSQL will not start with a group-readable key**
> Hence its own copy at `/var/lib/postgresql/baig.key`, owned by `postgres`,
> mode `0600`. The shared copy under `/etc/ssl/baig/` is group `certaccess`.

## The trap that nearly ate 6 GB

On the Mac mini, PostgreSQL and MariaDB were on **anonymous Docker volumes** —
neither compose file declared a `volumes:` block, so the data landed on
image-created volumes with names like
`d26a4fa4511a8f03cb2a8b868c07ef7cafba04c0a8673deb6714f2cf3b5f703f`.

That is 6.2 GB of work data, one
`docker compose down -v` or `docker volume prune` from deletion, with no name
to recognise it by.

CT 112 uses **native packages with normal data directories**. Where Docker is
used elsewhere (CT 113), data is on **bind mounts** under `/opt/data/`, never
named or anonymous volumes.

## Other gotchas

- **MariaDB 11.4+ clients require TLS by default.** Connecting to the Mac
  mini's 10.11 server fails with
  `ERROR 2026 "SSL is required, but the server does not support it"`.
  Use `--skip-ssl` for one-off transfers.
- **Debian's `prometheus-mongodb-exporter` is from 2018** and cannot talk to
  MongoDB 8. Percona's image runs on CT 113 instead.
- **Collation matters.** The source databases are `en_US.utf8`; a fresh Debian
  cluster initialises as `C`. The cluster was dropped and recreated with
  `pg_createcluster 17 main --locale=en_US.UTF-8` while it was still empty.

## yamtrack's data was hiding in the container

Worth recording because the same trap applies to anything using `DATABASE_URL`.

yamtrack 0.26 reads `DB_HOST` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_PORT`
and **ignores `DATABASE_URL` entirely**. With `DB_HOST` unset it silently falls
back to SQLite at `/yamtrack/db/db.sqlite3` — a path with no volume mounted.

So the Mac mini instance accumulated real data there for months while its
Postgres database sat empty, one `docker rm` from oblivion:

```
users: 1 (ahmed)   items: 8,757   movies: 127   tv: 146   seasons: 576   episodes: 8,008
```

The migration path that worked, given the version gap (0.24.9 → 0.26.3):

1. Copy the old SQLite into the **new** image and start it — it runs the
   intervening Django migrations and upgrades the schema in place
2. `manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.Permission -e sessions`
3. Strip `django_celery_beat.*` and `django_celery_results.*` from the fixture —
   migrations recreate those rows and loading them collides on
   `django_celery_beat_periodictask_name_key`
4. Switch the container to `DB_HOST` and let it migrate a fresh Postgres schema
5. `manage.py loaddata`
6. **Delete the internal SQLite** so it can never silently take over again

Verified: 38,242 objects loaded, counts match the source exactly.
