#!/usr/bin/env python3
"""DNS flow-graph metrics for Prometheus, via the node_exporter textfile collector.

Runs on CT 110 from a systemd timer. Its job is to emit the graph edges that a
Sankey / Node Graph panel needs, because nothing else in the stack does:

  - the adguard-exporter on CT 113 does NOT export top_upstreams_responses or
    top_upstreams_avg_time, though the AdGuard API returns both. That is the only
    place the AdGuard -> Unbound and AdGuard -> gateway legs exist as real
    numbers, so they are read from the API directly here.
  - Unbound has no per-upstream query counter at all. `unbound-control
    dump_infra` does have real per-resolver rtt / rto / timeout figures, which is
    what the per-resolver panels use.

WHERE THE NUMBERS COME FROM, AND THE ONE PLACE THEY ARE MIXED

AdGuard's statistics are a rolling 24 hour window. Unbound's counters are since
its last restart. Putting both in one Sankey without saying so would be wrong, so
the edge values are ALL taken from AdGuard's 24h window, and the only thing
borrowed from Unbound is a *ratio*:

    Unbound -> cache      = (AdGuard -> Unbound) * cachehits/queries
    Unbound -> Internet   = (AdGuard -> Unbound) * recursivereplies/queries

That ratio is currently about 0.3% cache / 99.7% recursion, because AdGuard
answers from its own cache first and Unbound therefore only ever sees misses. The
split is real, measured, and labelled `basis="ratio"` on the metric so a reader
can tell it apart from a directly counted edge, which carries `basis="counted"`.

Emitted:
  dns_flow_edge_queries{src,dst,src_kind,dst_kind,basis}  gauge, one per edge
  dns_flow_node_queries{node,kind}                        gauge, total through a node
  adguard_upstream_responses{upstream,name}               gauge, 24h window
  adguard_upstream_avg_response_seconds{upstream,name}     gauge
  unbound_infra_rtt_seconds{address,name}                 gauge, smoothed rtt
  unbound_infra_rto_seconds{address,name}                 gauge, retransmit timeout
  unbound_infra_timeouts{address,name,type}               gauge, per-type timeouts
  dns_flow_collector_up                                   gauge
"""
import base64
import ipaddress
import json
import os
import re
import subprocess
import sys
import urllib.request

OUT = "/var/lib/prometheus/node-exporter/dns-flow.prom"
ADGUARD = "http://127.0.0.1"
ADGUARD_AUTH = os.environ.get("ADGUARD_AUTH", "")

# Subnet -> the name to show on the map. Anything unmatched is grouped rather
# than shown as a bare address, or the graph grows a node per stray host.
ZONES = [
    (ipaddress.ip_network("10.10.10.0/24"), "VLAN 10 Trusted"),
    (ipaddress.ip_network("10.10.20.0/24"), "VLAN 20 Servers"),
    (ipaddress.ip_network("10.10.30.0/24"), "VLAN 30 IoT"),
    (ipaddress.ip_network("10.10.40.0/24"), "VLAN 40 Guest"),
    (ipaddress.ip_network("10.10.50.0/24"), "VLAN 50 Lab"),
    (ipaddress.ip_network("10.9.0.0/24"), "WireGuard VPN"),
    (ipaddress.ip_network("192.168.0.0/25"), "VLAN 1 Main Net"),
    (ipaddress.ip_network("127.0.0.0/8"), "localhost"),
]

# Classifying an AdGuard upstream, which the raw stats string cannot do alone.
#
# `top_upstreams_responses` reports the upstream as AdGuard resolved it -- so a
# domain-scoped entry like "[/servers.baig.network/]10.10.20.1" arrives simply as
# "10.10.20.1:53", with nothing to say it only ever handles internal names.
#
# Classifying on the ADDRESS fixes that, and is what actually matters for the
# question the map answers ("did this leave the house, and was it encrypted?"):
#
#   loopback        -> Unbound, which forwards to the internet over DoT
#   private address -> the UniFi gateway, answering internal names and local PTR.
#                      Never leaves the network at all.
#   tls:// https:// quic:// -> left encrypted
#   public + plain  -> left unencrypted, which is the only case worth alarming on
#
# Getting this wrong is not academic. An earlier version treated every non-
# loopback upstream as plain internet egress, which reported ~6,400 queries a day
# "leaking" when they were internal lookups against the gateway, and simultaneously
# filed the tls:// fallback under plain port 53.
UPSTREAM_NAMES = {
    "127.0.0.1:5335": "Unbound (DoT)",
}

PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
]


def classify_upstream(spec):
    """(display name, destination node, destination kind) for an upstream.

    destination None means the query terminated inside the network.
    """
    scheme = ""
    m = re.match(r"^([a-z0-9+]+)://(.*)$", spec)
    body = spec
    if m:
        scheme, body = m.group(1).lower(), m.group(2)

    # Strip a trailing :port, but not from a bare IPv6 literal.
    host = body
    if host.startswith("["):
        host = host.split("]")[0].lstrip("[")
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]

    is_loopback = False
    is_private = False
    try:
        ip = ipaddress.ip_address(host)
        is_loopback = ip.is_loopback
        is_private = any(ip in n for n in PRIVATE_NETS) or ip.is_private
    except ValueError:
        pass  # a hostname, e.g. dns.quad9.net -- treated as public below

    if is_loopback:
        return "Unbound (DoT)", "Internet (DoT :853)", "internet"
    if is_private:
        # Domain-scoped internal upstreams and local_ptr_upstreams both land here.
        return "UniFi gateway (internal names)", None, "internal"
    if scheme in ("tls", "https", "quic", "h3", "sdns"):
        return f"{host} ({scheme.upper()})", "Internet (DoT :853)", "internet"
    return f"{host} (plain)", "Internet (plain :53)", "internet"


def client_names():
    """ip -> friendly name, so the flow map shows hosts and not bare addresses.

    AdGuard already knows these: `clients` holds anything named by hand and
    `auto_clients` holds what it worked out by reverse DNS. Persistent entries win
    because a hand-chosen name beats a PTR record.
    """
    names = {}
    try:
        d = adguard("/control/clients")
    except Exception:
        return names
    for entry in d.get("auto_clients") or []:
        ip, nm = entry.get("ip"), entry.get("name")
        if ip and nm:
            names[ip] = nm
    for entry in d.get("clients") or []:
        nm = entry.get("name")
        for ip in entry.get("ids") or []:
            if nm:
                names[ip] = nm
    return names


def short_name(ip, names):
    """A label that fits on a graph node.

    `iPad.trusted.baig.network` is accurate and far too wide, so the zone and
    domain are dropped -- the zone is already its own node on the map, which
    makes repeating it in every leaf pure noise. The full name stays available as
    a label for the tooltip.
    """
    nm = names.get(ip)
    if not nm:
        return ip, ""
    label = nm
    # Longest first: ".home.baig.network" has to be tried before ".baig.network",
    # or "macbook.home.baig.network" shortens to "macbook.home".
    for suffix in (".trusted.baig.network", ".servers.baig.network",
                   ".iot.baig.network", ".lab.baig.network",
                   ".main.baig.network", ".guest.baig.network",
                   ".home.baig.network", ".vpn.baig.network",
                   ".baig.network"):
        if label.endswith(suffix):
            label = label[: -len(suffix)]
            break
    return (label or ip), nm


def zone_of(addr):
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return "other"
    for net, name in ZONES:
        if ip in net:
            return name
    return "other"


def adguard(path):
    r = urllib.request.Request(ADGUARD + path,
                               headers={"Authorization": "Basic " + ADGUARD_AUTH})
    with urllib.request.urlopen(r, timeout=20) as x:
        return json.load(x)


def unbound_stats():
    d = {}
    try:
        out = subprocess.run(["unbound-control", "stats_noreset"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return d
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            try:
                d[k.strip()] = float(v.strip())
            except ValueError:
                pass
    return d


def unbound_infra():
    """Per-upstream rtt / rto / timeouts from Unbound's infrastructure cache."""
    rows = []
    try:
        out = subprocess.run(["unbound-control", "dump_infra"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return rows
    for line in out.splitlines():
        # 9.9.9.9@853 . ttl 588 ping 10 var 7 rtt 50 rto 50 tA 0 tAAAA 1 tother 0 ...
        m = re.match(r"(\S+?)@(\d+)\s+\S+\s+(.*)$", line.strip())
        if not m:
            continue
        addr, port, rest = m.group(1), m.group(2), m.group(3)
        vals = {}
        toks = rest.split()
        for i in range(len(toks) - 1):
            if re.match(r"^-?\d+(\.\d+)?$", toks[i + 1]):
                vals[toks[i]] = float(toks[i + 1])
        rows.append((addr, port, vals))
    return rows


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def main():
    lines = []
    ok = 1
    try:
        st = adguard("/control/stats")
    except Exception as e:
        print(f"adguard stats failed: {e}", file=sys.stderr)
        st, ok = {}, 0

    ub = unbound_stats()

    edges = []       # (src, dst, src_kind, dst_kind, value, basis)
    nodes = {}       # name -> (kind, total)
    node_titles = {} # node id -> the shorter label to display on the graph
    node_detail = {} # node id -> fully qualified name, for the tooltip

    def node(name, kind, value):
        k, t = nodes.get(name, (kind, 0.0))
        nodes[name] = (k, t + value)

    if st:
        total = float(st.get("num_dns_queries", 0) or 0)
        blocked = float(st.get("num_blocked_filtering", 0) or 0)
        blocked += float(st.get("num_replaced_safebrowsing", 0) or 0)
        blocked += float(st.get("num_replaced_parental", 0) or 0)

        # ---- clients -> zone -> AdGuard -------------------------------------
        # top_clients is a list of single-key dicts, highest first, capped at 25
        # by AdGuard. The remainder is folded into "other clients" so the zone
        # totals still add up to num_dns_queries.
        cnames = client_names()
        per_zone = {}
        named = 0.0
        for item in st.get("top_clients", []) or []:
            for client, n in item.items():
                n = float(n)
                named += n
                z = zone_of(client)
                label, fqdn = short_name(client, cnames)
                # Two hosts could in principle shorten to the same label; keep the
                # address in the node id so they stay distinct nodes, and show the
                # label as the title.
                display = f"{label} ({client})" if label != client else client
                node_titles[display] = label
                node_detail[display] = fqdn or client
                per_zone[z] = per_zone.get(z, 0.0) + n
                edges.append((display, z, "client", "zone", n, "counted"))
                node(display, "client", n)
        remainder = max(0.0, total - named)
        if remainder > 0:
            edges.append(("other clients", "unclassified", "client", "zone",
                          remainder, "counted"))
            per_zone["unclassified"] = per_zone.get("unclassified", 0.0) + remainder
            node("other clients", "client", remainder)

        for z, n in per_zone.items():
            edges.append((z, "AdGuard", "zone", "resolver", n, "counted"))
            node(z, "zone", n)
        node("AdGuard", "resolver", total)

        # ---- AdGuard -> outcome ---------------------------------------------
        if blocked > 0:
            edges.append(("AdGuard", "Blocked", "resolver", "sink", blocked, "counted"))
            node("Blocked", "sink", blocked)

        upstream_total = 0.0
        to_unbound = 0.0
        onward_by_name = {}   # upstream display name -> (destination, kind)
        for item in st.get("top_upstreams_responses", []) or []:
            for up, n in item.items():
                n = float(n)
                upstream_total += n
                name, dest, dkind = classify_upstream(up)
                if dest == "Internet (DoT :853)" and name == "Unbound (DoT)":
                    to_unbound += n
                edges.append(("AdGuard", name, "resolver", "upstream", n, "counted"))
                node(name, "upstream" if dest else "internal", n)
                if dest:
                    onward_by_name.setdefault(name, (dest, dkind))
                    if name != "Unbound (DoT)":
                        # Unbound's onward leg is added below with its own ratio.
                        edges.append((name, dest, "upstream", dkind, n, "counted"))
                        node(dest, dkind, n)

        # Whatever AdGuard neither blocked nor forwarded, it answered itself.
        own_cache = max(0.0, total - blocked - upstream_total)
        if own_cache > 0:
            edges.append(("AdGuard", "AdGuard cache", "resolver", "sink",
                          own_cache, "counted"))
            node("AdGuard cache", "sink", own_cache)

        # ---- Unbound -> cache / Internet ------------------------------------
        # The only ratio-derived edges in the graph; see the module docstring.
        uq = ub.get("total.num.queries", 0.0)
        if to_unbound > 0 and uq > 0:
            hit_ratio = ub.get("total.num.cachehits", 0.0) / uq
            rec_ratio = ub.get("total.num.recursivereplies", 0.0) / uq
            cached = to_unbound * hit_ratio
            out_net = to_unbound * rec_ratio
            if cached > 0:
                edges.append(("Unbound (DoT)", "Unbound cache", "upstream", "sink",
                              cached, "ratio"))
                node("Unbound cache", "sink", cached)
            if out_net > 0:
                edges.append(("Unbound (DoT)", "Internet (DoT :853)", "upstream",
                              "internet", out_net, "ratio"))
                node("Internet (DoT :853)", "internet", out_net)
        elif to_unbound > 0:
            edges.append(("Unbound (DoT)", "Internet (DoT :853)", "upstream",
                          "internet", to_unbound, "counted"))
            node("Internet (DoT :853)", "internet", to_unbound)


    if edges:
        # Several distinct upstreams share one display name -- both UniFi gateway
        # addresses map to "UniFi gateway" -- which would emit two samples with
        # an identical label set. Prometheus rejects that outright, and the
        # textfile collector reports the whole file as failed, taking every other
        # metric here down with it. Sum them into one edge instead.
        merged = {}
        for src, dst, sk, dk, v, basis in edges:
            key = (src, dst, sk, dk, basis)
            merged[key] = merged.get(key, 0.0) + v
        lines += ["# HELP dns_flow_edge_queries Queries traversing one edge of the DNS path, AdGuard's 24h window",
                  "# TYPE dns_flow_edge_queries gauge"]
        # src/dst feed a Sankey; id/source/target are the field names Grafana's
        # built-in Node Graph panel requires, and it identifies the edges frame by
        # their presence. Emitting both spellings means neither panel needs a
        # rename transformation that silently breaks when a label is added.
        for (src, dst, sk, dk, basis), v in merged.items():
            lines.append(f'dns_flow_edge_queries{{src="{esc(src)}",dst="{esc(dst)}",'
                         f'id="{esc(src)} -> {esc(dst)}",source="{esc(src)}",target="{esc(dst)}",'
                         f'src_kind="{esc(sk)}",dst_kind="{esc(dk)}",basis="{basis}"}} {v:.0f}')
    if nodes:
        lines += ["# HELP dns_flow_node_queries Queries passing through one node of the DNS path",
                  "# TYPE dns_flow_node_queries gauge"]
        for name, (kind, tot) in sorted(nodes.items()):
            # `id` and `title` are what the Node Graph panel looks for; `node` is
            # kept because the existing panels and any ad-hoc query use it.
            title = node_titles.get(name, name)
            detail = node_detail.get(name, "")
            lines.append(f'dns_flow_node_queries{{node="{esc(name)}",id="{esc(name)}",'
                         f'title="{esc(title)}",subtitle="{esc(kind)}",kind="{esc(kind)}",'
                         f'detail__name="{esc(detail or title)}"}} {tot:.0f}')

    # ---- named per-client totals -------------------------------------------
    # adguard_top_clients from the exporter carries only `client` (the address)
    # and `hostname` (the AdGuard instance answering, not the client), so a panel
    # built on it can only ever show two IP addresses. This adds the resolved
    # name and the zone, so "Top clients" reads as hosts.
    if st:
        cn = client_names()
        lines += ["# HELP dns_flow_client_queries Queries per client with its resolved name, 24h window",
                  "# TYPE dns_flow_client_queries gauge"]
        for item in st.get("top_clients", []) or []:
            for client, n in item.items():
                label, fqdn = short_name(client, cn)
                lines.append(f'dns_flow_client_queries{{client="{esc(client)}",'
                             f'name="{esc(label)}",fqdn="{esc(fqdn or client)}",'
                             f'zone="{esc(zone_of(client))}"}} {float(n):.0f}')

    # ---- a real three-level path -------------------------------------------
    # One row per whole resolution path. The client -> outcome path is NOT
    # knowable: AdGuard reports per-client totals and per-upstream totals but
    # never the cross-tab, so attributing a client's queries to an outcome would
    # be invention.
    #
    # Edges must be merged BEFORE joining. Two gateway addresses can share one
    # display name, so the raw list holds several AdGuard -> gateway edges; joining
    # unmerged double counts the leg.
    if st:
        me = {}
        for src, dst, sk, dk, v, basis in edges:
            me[(src, dst, sk, dk)] = me.get((src, dst, sk, dk), 0.0) + v

        paths = {}
        for (src, dst, sk, dk), v in me.items():
            if src != "AdGuard":
                continue
            if dk in ("sink", "internal"):
                # Blocked, cache hits and internal-name lookups all stop here.
                # Repeating the name as the third stage keeps every row the same
                # width without implying the query went anywhere.
                key = ("AdGuard", dst, dst)
            else:
                onward = {b: vv for (a, b, _, _), vv in me.items()
                          if a == dst and b.startswith("Internet")}
                if onward:
                    for b, vv in onward.items():
                        k = ("AdGuard", dst, b)
                        paths[k] = paths.get(k, 0.0) + vv
                    continue
                key = ("AdGuard", dst, dst)
            paths[key] = paths.get(key, 0.0) + v

        if paths:
            lines += ["# HELP dns_flow_path_queries One whole resolution path. 24h window.",
                      "# TYPE dns_flow_path_queries gauge"]
            for (a, b, c), v in paths.items():
                lines.append(f'dns_flow_path_queries{{stage1="{esc(a)}",stage2="{esc(b)}",'
                             f'stage3="{esc(c)}"}} {v:.0f}')

    # ---- the upstream figures the exporter leaves out -----------------------
    ur = st.get("top_upstreams_responses", []) or []
    if ur:
        lines += ["# HELP adguard_upstream_responses Responses per upstream, 24h window. Absent from adguard-exporter.",
                  "# TYPE adguard_upstream_responses gauge"]
        for item in ur:
            for up, n in item.items():
                lines.append(f'adguard_upstream_responses{{upstream="{esc(up)}",'
                             f'name="{esc(UPSTREAM_NAMES.get(up, up))}"}} {float(n):.0f}')
    ua = st.get("top_upstreams_avg_time", []) or []
    if ua:
        lines += ["# HELP adguard_upstream_avg_response_seconds Mean response time per upstream, 24h window",
                  "# TYPE adguard_upstream_avg_response_seconds gauge"]
        for item in ua:
            for up, v in item.items():
                lines.append(f'adguard_upstream_avg_response_seconds{{upstream="{esc(up)}",'
                             f'name="{esc(UPSTREAM_NAMES.get(up, up))}"}} {float(v):.6f}')

    infra = unbound_infra()
    if infra:
        conf_names = {}
        try:
            for fn in sorted(os.listdir("/etc/unbound/unbound.conf.d")):
                if fn.endswith(".conf"):
                    for line in open(os.path.join("/etc/unbound/unbound.conf.d", fn)):
                        m = re.search(r"forward-addr:\s*([0-9a-fA-F.:]+)(?:@\d+)?(?:#(\S+))?", line)
                        if m:
                            conf_names[m.group(1)] = m.group(2) or ""
        except Exception:
            pass
        lines += ["# HELP unbound_infra_rtt_seconds Smoothed round-trip time to an upstream resolver",
                  "# TYPE unbound_infra_rtt_seconds gauge",
                  "# HELP unbound_infra_rto_seconds Retransmit timeout for an upstream resolver",
                  "# TYPE unbound_infra_rto_seconds gauge",
                  "# HELP unbound_infra_timeouts Timeouts recorded against an upstream, by query type",
                  "# TYPE unbound_infra_timeouts gauge"]
        for addr, port, v in infra:
            lbl = f'address="{esc(addr)}",port="{esc(port)}",name="{esc(conf_names.get(addr, ""))}"'
            if "rtt" in v:
                lines.append(f"unbound_infra_rtt_seconds{{{lbl}}} {v['rtt'] / 1000.0:.4f}")
            if "rto" in v:
                lines.append(f"unbound_infra_rto_seconds{{{lbl}}} {v['rto'] / 1000.0:.4f}")
            for tk, tname in (("tA", "A"), ("tAAAA", "AAAA"), ("tother", "other")):
                if tk in v:
                    lines.append(f'unbound_infra_timeouts{{{lbl},type="{tname}"}} {v[tk]:.0f}')

    lines += ["# HELP dns_flow_collector_up 1 if the AdGuard API answered",
              "# TYPE dns_flow_collector_up gauge",
              f"dns_flow_collector_up {ok}"]

    # A duplicate series does not just lose that one metric -- node_exporter
    # rejects the WHOLE file and every metric in it disappears, with
    # node_textfile_scrape_error going to 1 as the only clue. That has happened
    # twice here: once when two upstreams shared a display name, and once when an
    # editing slip emitted a whole block twice. Cheaper to catch it here than to
    # wonder why the dashboard emptied.
    seen, dupes = set(), []
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        series = line.rsplit(" ", 1)[0]
        if series in seen:
            dupes.append(series)
        seen.add(series)
    if dupes:
        for d in dupes[:5]:
            print(f"duplicate series, refusing to write: {d}", file=sys.stderr)
        print(f"{len(dupes)} duplicate series total; {OUT} left unchanged",
              file=sys.stderr)
        return 1

    tmp = OUT + ".tmp"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(tmp, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, OUT)  # atomic, so node_exporter never reads a partial file
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
