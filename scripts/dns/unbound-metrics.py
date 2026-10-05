#!/usr/bin/env python3
"""Unbound metrics for Prometheus, via the node_exporter textfile collector.

Runs on CT 110 from a systemd timer. Debian 13 has no packaged unbound_exporter,
and the point here is not general Unbound monitoring -- it is the data the DNS
flow map needs: how many queries entered, how many AdGuard answered from its own
cache before Unbound ever saw them, how many Unbound resolved recursively, and
how many left the building over DNS-over-TLS.

Two things are deliberately not what they look like:

  num.query.tls counts INBOUND queries that arrived over TLS, i.e. Unbound
  acting as a DoT server. It says nothing about the upstream leg. It is exported
  as unbound_inbound_tls_queries_total so the name cannot mislead.

  The upstream leg has no counter in Unbound at all. What it has is sockets, so
  established connections to port 853 are counted directly from the kernel. That
  is stronger evidence anyway: it shows DoT working right now, which matters on
  this line because the ISP transparently intercepts plain port 53 and a silent
  fallback would otherwise look like normal operation.

Emitted:
  unbound_up                             1 if unbound-control answered
  unbound_queries_total                  counter, all queries into Unbound
  unbound_cache_hits_total               counter
  unbound_cache_misses_total             counter
  unbound_recursive_replies_total        counter, answers needing recursion
  unbound_prefetch_total                 counter
  unbound_query_type_total{type}         counter
  unbound_answer_rcode_total{rcode}      counter
  unbound_inbound_tls_queries_total      counter, see note above
  unbound_recursion_time_seconds{quantile} gauge, avg and median
  unbound_requestlist_current            gauge
  unbound_requestlist_avg                gauge
  unbound_upstream_connections{...}      gauge, live sockets to an upstream
  unbound_upstream_info{...}             label-only, configured DoT upstreams
"""
import os
import re
import subprocess
import sys

OUT = "/var/lib/prometheus/node-exporter/unbound.prom"
CONF_GLOB = "/etc/unbound/unbound.conf.d"

# total.* is the aggregate across threads; the per-thread copies would double
# count, so anything starting thread<N>. is ignored.
SIMPLE = {
    "total.num.queries": ("unbound_queries_total", "counter", "Queries received by Unbound"),
    "total.num.cachehits": ("unbound_cache_hits_total", "counter", "Queries answered from Unbound's cache"),
    "total.num.cachemiss": ("unbound_cache_misses_total", "counter", "Queries that missed Unbound's cache"),
    "total.num.recursivereplies": ("unbound_recursive_replies_total", "counter", "Answers that required recursion"),
    "total.num.prefetch": ("unbound_prefetch_total", "counter", "Cache prefetches"),
    "total.num.expired": ("unbound_expired_served_total", "counter", "Expired entries served"),
    "total.num.queries_timed_out": ("unbound_queries_timed_out_total", "counter", "Queries that timed out"),
    "num.query.tls": ("unbound_inbound_tls_queries_total", "counter",
                      "Queries that ARRIVED over TLS. Not the upstream leg - see unbound_upstream_connections"),
}
GAUGES = {
    "total.requestlist.current.all": ("unbound_requestlist_current", "Queries waiting on recursion right now"),
    "total.requestlist.avg": ("unbound_requestlist_avg", "Average request list length"),
    "total.requestlist.max": ("unbound_requestlist_max", "Longest request list seen"),
}


def stats():
    try:
        out = subprocess.run(["unbound-control", "stats_noreset"],
                             capture_output=True, text=True, timeout=15)
    except Exception as e:
        print(f"unbound-control failed: {e}", file=sys.stderr)
        return None
    if out.returncode != 0:
        print(f"unbound-control rc={out.returncode}: {out.stderr.strip()[:200]}", file=sys.stderr)
        return None
    d = {}
    for line in out.stdout.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        try:
            d[k.strip()] = float(v.strip())
        except ValueError:
            pass
    return d


def configured_upstreams():
    """The DoT upstreams from the forward-zone, so the map has named endpoints."""
    found = []
    try:
        for fn in sorted(os.listdir(CONF_GLOB)):
            if not fn.endswith(".conf"):
                continue
            with open(os.path.join(CONF_GLOB, fn)) as fh:
                for line in fh:
                    line = line.strip()
                    if not line.startswith("forward-addr:"):
                        continue
                    spec = line.split(":", 1)[1].strip()
                    # 1.1.1.1@853#cloudflare-dns.com
                    m = re.match(r"([0-9a-fA-F.:]+)(?:@(\d+))?(?:#(\S+))?$", spec)
                    if m:
                        found.append((m.group(1), m.group(2) or "53", m.group(3) or ""))
    except Exception:
        pass
    return found


def upstream_sockets():
    """Live established sockets per (peer address, port).

    Counted from the kernel rather than inferred, because it is the only direct
    evidence that the upstream leg is really encrypted.
    """
    counts = {}
    try:
        out = subprocess.run(["ss", "-tnH", "state", "established"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return counts
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        peer = parts[-1] if ":" in parts[-1] else parts[3]
        # Strip IPv6 brackets before splitting off the port.
        m = re.match(r"\[?([0-9a-fA-F.:]+?)\]?:(\d+)$", peer)
        if not m:
            continue
        addr, port = m.group(1), m.group(2)
        if port in ("853", "53"):
            counts[(addr, port)] = counts.get((addr, port), 0) + 1
    return counts


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def main():
    d = stats()
    lines = ["# HELP unbound_up 1 if unbound-control responded",
             "# TYPE unbound_up gauge",
             f"unbound_up {0 if d is None else 1}"]

    if d is None:
        _write(lines)
        return 1

    for key, (name, mtype, help_text) in SIMPLE.items():
        if key in d:
            lines += [f"# HELP {name} {help_text}", f"# TYPE {name} {mtype}",
                      f"{name} {int(d[key])}"]

    for key, (name, help_text) in GAUGES.items():
        if key in d:
            lines += [f"# HELP {name} {help_text}", f"# TYPE {name} gauge",
                      f"{name} {d[key]}"]

    types = [(k.rsplit(".", 1)[1], v) for k, v in d.items() if k.startswith("num.query.type.")]
    if types:
        lines += ["# HELP unbound_query_type_total Queries by RR type",
                  "# TYPE unbound_query_type_total counter"]
        lines += [f'unbound_query_type_total{{type="{esc(t)}"}} {int(v)}' for t, v in sorted(types)]

    rcodes = [(k.rsplit(".", 1)[1], v) for k, v in d.items() if k.startswith("num.answer.rcode.")]
    if rcodes:
        lines += ["# HELP unbound_answer_rcode_total Answers by response code",
                  "# TYPE unbound_answer_rcode_total counter"]
        lines += [f'unbound_answer_rcode_total{{rcode="{esc(r)}"}} {int(v)}' for r, v in sorted(rcodes)]

    rt = []
    if "total.recursion.time.avg" in d:
        rt.append(("avg", d["total.recursion.time.avg"]))
    if "total.recursion.time.median" in d:
        rt.append(("median", d["total.recursion.time.median"]))
    if rt:
        lines += ["# HELP unbound_recursion_time_seconds Time spent resolving recursively",
                  "# TYPE unbound_recursion_time_seconds gauge"]
        lines += [f'unbound_recursion_time_seconds{{quantile="{q}"}} {v}' for q, v in rt]

    socks = upstream_sockets()
    conf = configured_upstreams()
    names = {addr: nm for addr, _, nm in conf}
    lines += ["# HELP unbound_upstream_connections Established sockets to an upstream resolver",
              "# TYPE unbound_upstream_connections gauge"]
    if conf:
        # Emit every configured upstream, including the idle ones. A zero is
        # information; a missing series just looks like the collector broke.
        for addr, port, nm in conf:
            n = socks.get((addr, port), 0)
            lines.append(f'unbound_upstream_connections{{address="{esc(addr)}",port="{esc(port)}",'
                         f'name="{esc(nm)}",encrypted="{"yes" if port == "853" else "no"}"}} {n}')
    for (addr, port), n in sorted(socks.items()):
        if not any(addr == a and port == p for a, p, _ in conf):
            lines.append(f'unbound_upstream_connections{{address="{esc(addr)}",port="{esc(port)}",'
                         f'name="{esc(names.get(addr, ""))}",'
                         f'encrypted="{"yes" if port == "853" else "no"}"}} {n}')

    if conf:
        lines += ["# HELP unbound_upstream_info Configured upstream resolvers, label-only",
                  "# TYPE unbound_upstream_info gauge"]
        for addr, port, nm in conf:
            lines.append(f'unbound_upstream_info{{address="{esc(addr)}",port="{esc(port)}",'
                         f'name="{esc(nm)}",encrypted="{"yes" if port == "853" else "no"}"}} 1')

    _write(lines)
    return 0


def _write(lines):
    tmp = OUT + ".tmp"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(tmp, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, OUT)  # atomic, so node_exporter never reads a partial file


if __name__ == "__main__":
    sys.exit(main())
