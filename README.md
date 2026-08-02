# PalUI

Lightweight web UI for managing a Palworld 1.0 server over REST plus config file editing.

## Features

- Runs on port `8005`.
- Shows server statistics from Palworld REST API.
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
- Any config save triggers:
  - announcement: `Config change made, server restarting.`
  - restart request via Palworld REST API

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
- `PALWORLD_API_TOKEN`
- `PALWORLD_API_TOKEN_HEADER` (default `Authorization`)
- `PALWORLD_API_TOKEN_PREFIX` (default `Bearer`)

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
