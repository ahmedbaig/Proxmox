# Ollama (Mac mini)

Set up 1 November 2026. `https://ollama.baig.network` → proxy (CT 111) →
`10.10.20.10:11434`.

| | |
|---|---|
| Runs | `ollama serve` in a terminal on the Mac mini, with `OLLAMA_HOST=0.0.0.0:11434` (in `~/.zshrc`). Not a service: **down after a reboot until started again** |
| Models | `qwen3-coder:30b` (tools, 256k context), `qwen2.5-coder:14b` |
| URL | `https://ollama.baig.network` — native API and the OpenAI-compatible `/v1` |
| Direct | `http://macmini.servers.baig.network:11434` (existing AdGuard rewrite) |
| Who can use it | nginx `allow`: Trusted `10.10.10.0/24`, VPN clients (`10.10.50.20`), Prometheus `10.10.20.5`. Everyone else gets 403 |
| Code | `proxmox` repo, `ollama.baig.network` block in `roles/proxy/templates/baig.conf.j2` |

> **No login.**
> Ollama has no authentication, and editors cannot follow an Entra redirect,
> so the allow-list is the only gate on the proxy. On the network itself port
> 11434 is open to anything that can reach the Servers VLAN (the router's zone
> policies limit that to Trusted and Servers).

## Proxy settings that matter

- `proxy_set_header Host localhost:11434` — Ollama only trusts local Host headers.
- `proxy_buffering off`, 15 min timeouts — tokens stream, and a cold 30B model
  takes a while to load (the 14B loaded in ~6 s).
- `client_max_body_size 64m` — large files or images in context.

## Editors

**Zed** (`~/.config/zed/settings.json`):

```json
"language_models": {
  "ollama": {
    "api_url": "https://ollama.baig.network",
    "available_models": [
      { "name": "qwen3-coder:30b", "display_name": "Qwen3 Coder 30B", "max_tokens": 32768, "supports_tools": true },
      { "name": "qwen2.5-coder:14b", "display_name": "Qwen2.5 Coder 14B", "max_tokens": 32768 }
    ]
  }
}
```

**Cline:** API Provider *Ollama*, custom base URL `https://ollama.baig.network`,
model `qwen3-coder:30b`. Or *OpenAI Compatible* with base URL
`https://ollama.baig.network/v1` and any non-empty API key.

> **Context length.**
> Ollama's default context window is small, and Cline's prompts are long. If
> answers look like they forgot the task, start the server with a bigger window:
> `OLLAMA_CONTEXT_LENGTH=32768 ollama serve` (costs more memory per model).

## Monitoring

- Prometheus `blackbox-http`: `https://ollama.baig.network` (also in `ServiceDown`).
- Gatus (Oracle): **Ollama** in `5-apps`, `/api/version`, Discord after 6 failures
  (30 min) because it is legitimately down after a reboot.
- Service register card on `home.baig.network`.

## Later

- [ ] Run `ollama serve` from a LaunchAgent so it survives reboots.

Related: [Lab Map](lab-map.md) · [Reverse Proxy and Certificates](reverse-proxy-and-certificates.md)
