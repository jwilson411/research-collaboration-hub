#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export ASPNETCORE_ENVIRONMENT=Development
export HUB_DEMO_ENABLED=true
export HUB_DEMO_FILE_RELEASE="${HUB_DEMO_FILE_RELEASE:-true}"
printf '%s\n' 'Local synthetic preview: http://127.0.0.1:5080 on this computer only.' 'Synthetic file release permits plain text and the bundled demo PNG only; other binaries stay quarantined.'
exec "${DOTNET:-dotnet}" run --project "$project_root/ResearchHub.csproj" --no-launch-profile
