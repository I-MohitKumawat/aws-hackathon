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
echo " Starting AI Incident Investigator Environment via $COMPOSE_CMD"
echo "================================================================="

$COMPOSE_CMD up -d

echo ""
echo "Waiting for services to become healthy..."
sleep 5

echo "================================================================="
echo " Environment Running Services & Endpoints:"
echo "================================================================="
echo "  - Frontend Dashboard   : http://localhost:3000"
echo "  - E-Commerce Store UI  : http://localhost:3000/store"
echo "  - Fault Injection UI   : http://localhost:3000/simulate"
echo "  - Live Telemetry UI    : http://localhost:3000/telemetry"
echo "  - Backend API          : http://localhost:8000/api/v1"
echo "  - Checkout Service     : http://localhost:8080"
echo "  - Inventory Service    : http://localhost:8081"
echo "  - Payment Service      : http://localhost:8082"
echo "  - Jaeger UI            : http://localhost:16686"
echo "  - OTel Collector gRPC  : localhost:4317 (HTTP: 4318, Health: 13133)"
echo "  - Ollama LLM Service   : http://localhost:11435"
echo "================================================================="
