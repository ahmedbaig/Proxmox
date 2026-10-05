#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
secrets="${HOMELAB_SECRETS:-../../homelab-secrets}"
eval "$(sops decrypt --output-type dotenv "$secrets/terraform/gitlab-state.sops.yaml" | sed 's/^/export /')"
export TF_HTTP_USERNAME="$gitlab_username" TF_HTTP_PASSWORD="$gitlab_token"
[ -d .terraform ] || terraform init -backend-config=backend.hcl
exec terraform "$@"
