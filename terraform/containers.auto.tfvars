containers = {
  dns1 = {
    vmid        = 110, order = 1, cores = 1, memory = 8192, swap = 8192, disk = 4
    ip          = "10.10.20.2/24", gateway = "10.10.20.1", vlan = 20, mac = "BC:24:11:3C:BE:E1"
    dns         = ["127.0.0.1", "1.1.1.1"], search = "servers.baig.network"
    description = "AdGuard Home + Unbound"
  }
  proxy = {
    vmid        = 111, order = 2, cores = 1, memory = 512, swap = 512, disk = 8
    ip          = "10.10.20.3/24", gateway = "10.10.20.1", vlan = 20, mac = "BC:24:11:4B:68:5A"
    search      = "servers.baig.network"
    description = "nginx reverse proxy + wildcard certificate"
  }
  db = {
    vmid        = 112, order = 3, cores = 2, memory = 6144, swap = 1024, disk = 32, keyctl = true
    ip          = "10.10.20.4/24", gateway = "10.10.20.1", vlan = 20, mac = "BC:24:11:EC:A4:29"
    description = "PostgreSQL, MariaDB, MongoDB, Redis, CouchDB"
  }
  apps = {
    vmid        = 113, order = 4, cores = 2, memory = 2048, swap = 512, disk = 16, keyctl = true
    ip          = "10.10.20.6/24", gateway = "10.10.20.1", vlan = 20, mac = "BC:24:11:DE:B0:DC"
    description = "Docker apps: yamtrack, webhook, mailcatcher, exporters"
  }
  metrics = {
    vmid        = 114, order = 5, cores = 2, memory = 4096, swap = 1024, disk = 40
    ip          = "10.10.20.5/24", gateway = "10.10.20.1", vlan = 20, mac = "BC:24:11:7E:61:61"
    description = "Prometheus, Loki, Alertmanager, blackbox"
  }
  grafana = {
    vmid        = 115, order = 6, cores = 2, memory = 2048, swap = 512, disk = 16
    ip          = "10.10.20.7/24", gateway = "10.10.20.1", vlan = 20, mac = "BC:24:11:0B:99:19"
    description = "Grafana"
  }
  vpn = {
    vmid        = 116, order = 7, cores = 2, memory = 1024, swap = 512, disk = 8
    ip          = "10.10.50.20/24", gateway = "10.10.50.1", vlan = 50, mac = "BC:24:11:54:93:68"
    description = "WireGuard + WGDashboard"
  }
  docker = {
    vmid        = 117, order = 8, cores = 4, memory = 10240, swap = 2048, disk = 90, keyctl = true
    ip          = "10.10.50.30/24", gateway = "10.10.50.1", vlan = 50, mac = "BC:24:11:E3:56:4C"
    search      = "lab.baig.network"
    description = "Docker host + GitLab runners for the work test stack"
  }
  gitlab = {
    vmid        = 118, order = 10, cores = 4, memory = 5120, swap = 1024, disk = 40
    ip          = "10.10.50.40/24", gateway = "10.10.50.1", vlan = 50, mac = "BC:24:11:A9:1A:F9"
    search      = "lab.baig.network"
    description = "GitLab CE"
  }
  registry = {
    vmid        = 119, order = 9, cores = 1, memory = 1024, swap = 512, disk = 48, keyctl = true
    ip          = "10.10.50.41/24", gateway = "10.10.50.1", vlan = 50, mac = "BC:24:11:2B:EE:E2"
    search      = "lab.baig.network"
    description = "Docker registry"
  }
}
