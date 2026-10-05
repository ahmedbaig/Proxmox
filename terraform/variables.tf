variable "secrets_dir" {
  description = "Checkout of the private homelab-secrets repo"
  type        = string
  default     = "../../homelab-secrets"
}

variable "node_name" {
  type    = string
  default = "pve"
}

variable "template_file_id" {
  description = "Template used when a container is (re)created"
  type        = string
  default     = "local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst"
}
