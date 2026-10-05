#!/bin/bash
# runs inside CT 118
export LANG=C DEBIAN_FRONTEND=noninteractive
exec > /root/gitlab-install.log 2>&1
set -x
curl -fsSL https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh | bash
apt-get install -y gitlab-ce
echo "INSTALL-EXIT=$?"
