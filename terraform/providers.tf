data "sops_file" "proxmox" {
  source_file = "${var.secrets_dir}/terraform/proxmox.sops.yaml"
}

provider "proxmox" {
  endpoint  = data.sops_file.proxmox.data["proxmox_endpoint"]
  api_token = data.sops_file.proxmox.data["proxmox_api_token"]
  insecure  = true

  ssh {
    agent    = true
    username = "root"
  }
}
