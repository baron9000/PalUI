# PalUI

Lightweight web UI for managing a Palworld 1.0 server over REST plus config file editing.

## Features

- Runs on port `8005`.
- Shows server statistics from Palworld REST API.
- Exposes the documented community-server REST commands:
  - `info`, `players`, `settings`, `metrics`, `game-data`
  - `announce`, `kick`, `ban`, `unban`, `save`, `shutdown`, `stop`
- Shows and edits:
  - `PalWorldSettings.ini`
  - `Engine.ini`
- Uses UI controls by type:
  - checkbox for booleans
  - sliders for common `*Rate` style values
  - radio options for known enums (`Difficulty`, `DeathPenalty`)
  - text/number inputs for everything else
- Includes moderation/admin tasks:
  - send announcement
  - kick player
  - ban player
  - restart server
  - shutdown server
- Backup management:
  - list available backups
  - create timestamped backup archives
  - restore selected backup from list
- Any config save now triggers this order:
  - announcement: `Config change made, server restarting.`
  - stop server
  - write config files
  - start server (or rely on wrapper auto-start if no start endpoint is exposed)

## Required Mount

This container expects your Palworld root folder mounted at:

`/palworld`

It reads config from:

`/palworld/Pal/Saved/Config/LinuxServer`

It stores backup archives in:

`/palworld/backups`

## Quick Start (Docker Compose)

1. Edit [docker-compose.yml](docker-compose.yml) and replace:

`/volume1/Games/palworld`

with your host path containing full Palworld data.

2. Optionally set API auth variables:

- `PALWORLD_API_BASE_URL`
- `PALWORLD_STATS_COMMAND` to choose the default query command shown on load
- `PALWORLD_API_USERNAME` and `PALWORLD_API_PASSWORD` for the REST API basic auth used by the community-server app
- `PALWORLD_API_TOKEN`
- `PALWORLD_API_TOKEN_HEADER` (default `Authorization`)
- `PALWORLD_API_TOKEN_PREFIX` (default `Bearer`)
- `PALWORLD_RESTART_STRATEGY` (default `save-stop-then-shutdown`)
  - `save-stop-then-shutdown`: try `save` + `stop` first, fallback to `shutdown`
  - `save-stop`: only `save` + `stop`
  - `shutdown`: only graceful shutdown (legacy behavior)

If you are using thijsvanloef/palworld-server-docker, the REST wrapper uses the admin password for REST calls. Set `PALWORLD_API_USERNAME=admin` and `PALWORLD_API_PASSWORD=<your ADMIN_PASSWORD>`.

If your config values keep reverting after restart, your Palworld server container may be regenerating config on boot from its own environment. In that case, disable boot-time config generation in the server container (for example `UPDATE_ON_BOOT=false` in thijsvanloef/palworld-server-docker) or update that container's config source to match your edits.

3. Start:

```bash
docker compose up -d --build
```

4. Open:

`http://<docker-host>:8005`

## Portainer Deployment

Use **Stacks** in Portainer:

1. Create a new stack.
2. Paste the content from [docker-compose.yml](docker-compose.yml).
3. Update the volume mount source path.
4. Deploy the stack.

## Notes on API Compatibility

Different Palworld REST wrappers can use different endpoint paths/payload keys. This UI tries multiple common endpoint variants for stats and admin actions. If your API differs, update endpoint lists in [app/app.py](app/app.py).
