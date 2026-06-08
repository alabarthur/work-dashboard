#!/usr/bin/env bash
# Install (or reinstall) the launchd agent that runs the collector every 15 min.
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.user.worktable.collector"
DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "$HOME/Library/LaunchAgents"

# Render the template with absolute paths.
sed -e "s#__PROJECT__#${PROJECT}#g" -e "s#__HOME__#${HOME}#g" \
    "${PROJECT}/scripts/${LABEL}.plist" > "$DEST"

# Reload.
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"

echo "Installed ${LABEL}."
echo "  status:    launchctl print gui/$(id -u)/${LABEL} | grep state"
echo "  run now:   launchctl kickstart gui/$(id -u)/${LABEL}"
echo "  uninstall: launchctl bootout gui/$(id -u)/${LABEL} && rm '${DEST}'"
echo "  logs:      ${PROJECT}/data/collector.out.log / .err.log"
