# docker_host

Generic setup for CT 117, the lab's build and deploy host: Docker engine, the GitLab Runner package, and an
nftables egress policy that lets builds reach the internet while the long-running workload stays on the LAN.

Runner registration (`/etc/gitlab-runner/config.toml`), the workload stack it runs and the deploy user are
private and not part of this repo.
