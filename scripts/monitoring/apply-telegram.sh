#!/usr/bin/env bash
# Run ON THE PROXMOX HOST. Configures Alertmanager to send to Telegram.
#
#   ./apply-telegram.sh <bot-token> <chat-id>
#
# Getting the two values:
#   1. Message @BotFather on Telegram, /newbot, copy the token
#      (looks like 8123456789:AAH...)
#   2. Send any message to your new bot, then:
#        curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" \
#          | grep -o '"chat":{"id":[-0-9]*'
#      The id is negative for groups, positive for a direct chat.
#
# The webhook-tester receiver is kept as a secondary route so alerts remain
# visible in a browser even if Telegram delivery fails.

set -euo pipefail

TOKEN="${1:?usage: apply-telegram.sh <bot-token> <chat-id>}"
CHAT="${2:?usage: apply-telegram.sh <bot-token> <chat-id>}"

cat > /root/alertmanager.yml <<EOF
# /etc/prometheus/alertmanager.yml  —  CT 114 (metrics, 10.10.20.5)
#
# Certificate expiry and service-health rules fire in Prometheus; Alertmanager
# turns them into notifications. Telegram is primary; webhook-tester is kept as
# a secondary so alerts stay visible in a browser if delivery fails.

global:
  resolve_timeout: 5m

templates: []

route:
  receiver: telegram
  group_by: ['alertname', 'instance']
  group_wait: 30s
  group_interval: 5m
  # Certificates expire on a scale of weeks. A warning that repeats every four
  # hours is one you learn to ignore.
  repeat_interval: 24h

  routes:
    - matchers:
        - severity = "critical"
      receiver: telegram
      repeat_interval: 4h

receivers:
  - name: telegram
    telegram_configs:
      - bot_token: '${TOKEN}'
        chat_id: ${CHAT}
        parse_mode: HTML
        send_resolved: true
        message: |
          {{ if eq .Status "firing" }}⚠️ <b>{{ .CommonLabels.severity | toUpper }}</b>{{ else }}✅ <b>RESOLVED</b>{{ end }}
          {{ range .Alerts }}
          <b>{{ .Labels.alertname }}</b>
          {{ .Annotations.summary }}
          {{ if .Annotations.description }}{{ .Annotations.description }}{{ end }}
          {{ end }}
    webhook_configs:
      - url: http://10.10.20.6:8083/
        send_resolved: true

inhibit_rules:
  # If a host is entirely unreachable, its individual probe failures add
  # nothing — keep the one alert that matters.
  - source_matchers:
      - alertname = "ExporterDown"
    target_matchers:
      - alertname = "ServiceDown"
    equal: ['instance']
EOF

pct push 114 /root/alertmanager.yml /etc/prometheus/alertmanager.yml
pct exec 114 -- amtool check-config /etc/prometheus/alertmanager.yml
pct exec 114 -- systemctl restart prometheus-alertmanager
sleep 5
printf 'alertmanager: %s\n' "$(pct exec 114 -- systemctl is-active prometheus-alertmanager)"

echo "sending a test alert..."
pct exec 114 -- amtool alert add \
  alertname=TelegramTest severity=warning instance=setup \
  --annotation=summary="Telegram delivery test from the Lidcombe lab" \
  --alertmanager.url=http://127.0.0.1:9093 || true

echo "done — check Telegram"
