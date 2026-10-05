output "containers" {
  value = { for name, ct in proxmox_virtual_environment_container.ct : name => {
    vmid = ct.vm_id
    ip   = var.containers[name].ip
  } }
}
