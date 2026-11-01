#!/bin/sh
# GPU metrics for node_exporter's textfile collector, straight from nvidia-smi.
# Written to a temp file and renamed so the scrape never sees half a file.
set -eu
dir=/var/lib/prometheus/node-exporter
out="$dir/nvidia.prom"
tmp="$out.$$"

if ! line=$(nvidia-smi --query-gpu=index,name,utilization.gpu,utilization.encoder,utilization.decoder,memory.used,memory.total,temperature.gpu,power.draw,fan.speed,clocks.sm \
            --format=csv,noheader,nounits 2>/dev/null); then
  printf 'nvidia_smi_up 0\n' >"$tmp" && mv "$tmp" "$out"
  exit 0
fi

{
  printf '# HELP nvidia_smi_up 1 if nvidia-smi answered (driver and libraries match).\n# TYPE nvidia_smi_up gauge\nnvidia_smi_up 1\n'
  printf '%s\n' "$line" | while IFS=, read -r idx name gpu enc dec mused mtotal temp power fan clock; do
    l="gpu=\"$idx\",name=\"$(echo "$name" | sed 's/^ *//')\""
    for m in "utilization_gpu_ratio:$gpu:100" "utilization_encoder_ratio:$enc:100" "utilization_decoder_ratio:$dec:100" \
             "memory_used_bytes:$mused:1/1048576" "memory_total_bytes:$mtotal:1/1048576" \
             "temperature_celsius:$temp:1" "power_draw_watts:$power:1" "fan_speed_ratio:$fan:100" "clock_sm_hertz:$clock:1/1000000"; do
      key=${m%%:*}; rest=${m#*:}; val=$(echo "${rest%%:*}" | tr -d ' '); div=${rest#*:}
      case "$val" in ''|*N/A*|*Not*) continue ;; esac
      case "$div" in
        100) val=$(awk "BEGIN{print $val/100}") ;;
        1/*) val=$(awk "BEGIN{print $val*${div#1/}}") ;;
      esac
      printf 'nvidia_%s{%s} %s\n' "$key" "$l" "$val"
    done
  done
} >"$tmp"
mv "$tmp" "$out"
