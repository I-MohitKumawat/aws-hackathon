#!/usr/bin/env bash
set -e

# Detect container runtime
if command -v podman &> /dev/null; then
    COMPOSE_CMD="podman compose"
elif command -v docker &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    echo "[ERROR] Neither podman nor docker found in PATH."
    exit 1
fi

echo "================================================================="
echo " Stopping AI Incident Investigator Environment via $COMPOSE_CMD"
echo "================================================================="

$COMPOSE_CMD down

echo "[OK] Environment stopped cleanly."
