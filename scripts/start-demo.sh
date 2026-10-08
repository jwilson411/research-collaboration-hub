#!/usr/bin/env bash
set -euo pipefail
release=false
case "${1:-}" in
  '') ;;
  --release-synthetic-files) release=true; shift ;;
  *) printf '%s\n' 'Usage: start-demo.sh [--release-synthetic-files]' >&2; exit 2 ;;
esac
if (( $# )); then printf '%s\n' 'Usage: start-demo.sh [--release-synthetic-files]' >&2; exit 2; fi
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
dotnet_command="${DOTNET:-dotnet}"
if ! "$dotnet_command" --list-sdks | grep -q '^10\.0\.'; then
  printf '%s\n' 'Install a currently serviced .NET 10 SDK before starting this preview.' >&2
  exit 1
fi
cd -- "$project_root"
if [[ ! "$("$dotnet_command" --version)" =~ ^10\.0\.[0-9]+$ ]]; then
  printf '%s\n' 'The selected SDK must be stable .NET 10; check global.json and installed SDKs.' >&2
  exit 1
fi
export ASPNETCORE_ENVIRONMENT=Development DOTNET_ENVIRONMENT=Development
export HUB_DEMO_ENABLED=true HUB_STORAGE_PROVIDER=Json HUB_DEMO_FILE_RELEASE="$release"
printf '%s\n' 'Local synthetic JSON preview: http://127.0.0.1:5080 on this computer only. Stop with Ctrl+C.'
if [[ "$release" == true ]]; then
  printf '%s\n' 'Synthetic release enabled: validated text and the bundled demo PNG only; other binaries stay quarantined.'
else
  printf '%s\n' 'All uploads stay quarantined. Use --release-synthetic-files for the synthetic file walkthrough.'
fi
"$dotnet_command" restore --locked-mode
exec "$dotnet_command" run --project "$project_root/ResearchHub.csproj" --no-restore --no-launch-profile
