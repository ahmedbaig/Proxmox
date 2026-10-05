#!/usr/bin/env bash
set -euo pipefail
pve=root@10.10.20.20
secrets="${HOMELAB_SECRETS:-$(cd "$(dirname "$0")/../../homelab-secrets" && pwd)}"
tmp="$(mktemp -d)"; trap '/bin/rm -rf -P "$tmp"' EXIT

ssh "$pve" 'set -e
pveum role list --output-format json | grep -q "\"roleid\":\"Terraform\"" || pveum role add Terraform -privs "Datastore.Allocate Datastore.AllocateSpace Datastore.AllocateTemplate Datastore.Audit Pool.Allocate Pool.Audit Sys.Audit Sys.Console Sys.Modify SDN.Use VM.Allocate VM.Audit VM.Clone VM.Config.CDROM VM.Config.Cloudinit VM.Config.CPU VM.Config.Disk VM.Config.HWType VM.Config.Memory VM.Config.Network VM.Config.Options VM.Migrate VM.PowerMgmt VM.GuestAgent.Audit"
pveum user list --output-format json | grep -q "\"userid\":\"terraform@pve\"" || pveum user add terraform@pve --comment "Terraform (proxmox repo)"
pveum acl modify / -user terraform@pve -role Terraform
pveum user token add terraform@pve iac --privsep 0 --output-format json' > "$tmp/pve.json"

python3 - "$tmp/pve.json" > "$tmp/proxmox.yaml" <<'PY'
import json, sys
t = json.load(open(sys.argv[1]))
print(f'proxmox_endpoint: https://10.10.20.20:8006/\nproxmox_api_token: "{t["full-tokenid"]}={t["value"]}"')
PY

ssh "$pve" 'pct exec 118 -- gitlab-rails runner "
u = User.find_by_username(%q(root))
t = u.personal_access_tokens.create!(name: %q(terraform-state), scopes: [:api], expires_at: 365.days.from_now, organization: u.organizations.first)
puts t.token"' | tail -1 > "$tmp/gl.token"
printf 'gitlab_username: root\ngitlab_token: "%s"\n' "$(cat "$tmp/gl.token")" > "$tmp/gitlab-state.yaml"

mkdir -p "$secrets/terraform"
cd "$secrets"
sops encrypt --filename-override terraform/proxmox.sops.yaml "$tmp/proxmox.yaml" > terraform/proxmox.sops.yaml
sops encrypt --filename-override terraform/gitlab-state.sops.yaml "$tmp/gitlab-state.yaml" > terraform/gitlab-state.sops.yaml
echo "stored terraform/proxmox.sops.yaml and terraform/gitlab-state.sops.yaml in $secrets"
