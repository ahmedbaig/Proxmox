variable "containers" {
  type = map(object({
    vmid        = number
    order       = number
    cores       = number
    memory      = number
    swap        = number
    disk        = number
    keyctl      = optional(bool, false)
    ip          = string
    gateway     = string
    vlan        = number
    mac         = string
    dns         = optional(list(string), ["10.10.20.2"])
    search      = optional(string)
    description = optional(string)
    mounts      = optional(list(object({ host = string, path = string, read_only = optional(bool, false) })), [])
    devices     = optional(list(string), [])
  }))
}

resource "proxmox_virtual_environment_container" "ct" {
  for_each = var.containers

  node_name     = var.node_name
  vm_id         = each.value.vmid
  description   = each.value.description
  unprivileged  = true
  start_on_boot = true

  startup {
    order = each.value.order
  }

  features {
    nesting = true
    keyctl  = each.value.keyctl
  }

  cpu {
    cores = each.value.cores
  }

  memory {
    dedicated = each.value.memory
    swap      = each.value.swap
  }

  disk {
    datastore_id = "local-lvm"
    size         = each.value.disk
  }

  dynamic "mount_point" {
    for_each = each.value.mounts
    content {
      volume    = mount_point.value.host
      path      = mount_point.value.path
      read_only = mount_point.value.read_only
    }
  }

  dynamic "device_passthrough" {
    for_each = each.value.devices
    content {
      path = device_passthrough.value
    }
  }

  network_interface {
    name        = "eth0"
    bridge      = "vmbr1"
    firewall    = true
    vlan_id     = each.value.vlan
    mac_address = each.value.mac
  }

  initialization {
    hostname = each.key

    dns {
      servers = each.value.dns
      domain  = each.value.search
    }

    ip_config {
      ipv4 {
        address = each.value.ip
        gateway = each.value.gateway
      }
    }
  }

  operating_system {
    template_file_id = var.template_file_id
    type             = "debian"
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [operating_system, initialization[0].user_account, description]
  }
}

import {
  for_each = var.containers
  to       = proxmox_virtual_environment_container.ct[each.key]
  id       = "${var.node_name}/${each.value.vmid}"
}
