#!/usr/bin/env bash
set -euo pipefail

# Blackbox Postgres test runner for AgentFabric.
# - Starts a postgres:16 container (unique name + free port by default)
# - Waits for readiness
# - Exports AGENTFABRIC_TEST_DB_URL
# - Runs pytest blackbox tests
# - Cleans up the container if it was started by this script

IMAGE="${AGENTFABRIC_PG_IMAGE:-postgres:16}"
PG_USER="${AGENTFABRIC_PG_USER:-agentfabric}"
PG_PASSWORD="${AGENTFABRIC_PG_PASSWORD:-pass}"
PG_DB="${AGENTFABRIC_PG_DB:-agentfabric_test}"
PG_DATA_VOLUME="${AGENTFABRIC_PG_DATA_VOLUME:-}"

# By default, generate a unique container name to avoid collisions.
if [[ -n "${AGENTFABRIC_PG_NAME:-}" ]]; then
  NAME="$AGENTFABRIC_PG_NAME"
else
  suffix="$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  NAME="agentfabric-pg-test-${suffix}"
fi

# By default, pick a free localhost port to avoid collisions.
if [[ -n "${AGENTFABRIC_PG_PORT:-}" ]]; then
  HOST_PORT="$AGENTFABRIC_PG_PORT"
else
  if command -v python3 >/dev/null 2>&1; then
    HOST_PORT="$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(('127.0.0.1', 0))
print(s.getsockname()[1])
s.close()
PY
)"
  else
    HOST_PORT="55433"
  fi
fi

WAIT_SECS="${AGENTFABRIC_PG_WAIT_SECS:-60}"
KEEP_CONTAINER="${AGENTFABRIC_PG_KEEP:-0}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found; cannot run blackbox postgres tests" >&2
  exit 1
fi

started_by_script=0

container_running() {
  docker ps --format '{{.Names}}' | grep -qx "$NAME"
}

container_exists() {
  docker ps -a --format '{{.Names}}' | grep -qx "$NAME"
}

start_container() {
  local args=(
    run --rm -d --name "$NAME"
    -e "POSTGRES_USER=$PG_USER"
    -e "POSTGRES_PASSWORD=$PG_PASSWORD"
    -e "POSTGRES_DB=$PG_DB"
    -p "$HOST_PORT:5432"
  )

  if [[ -n "$PG_DATA_VOLUME" ]]; then
    args+=( -v "$PG_DATA_VOLUME:/var/lib/postgresql/data" )
  fi

  args+=( "$IMAGE" )

  echo "Starting postgres container: $NAME ($IMAGE) on localhost:$HOST_PORT" >&2
  docker "${args[@]}" >/dev/null
}

cleanup() {
  if [[ "$started_by_script" -eq 1 && "$KEEP_CONTAINER" != "1" ]]; then
    echo "Stopping postgres container: $NAME" >&2
    docker stop "$NAME" >/dev/null 2>&1 || true
  elif [[ "$started_by_script" -eq 1 && "$KEEP_CONTAINER" == "1" ]]; then
    echo "Keeping postgres container running: $NAME (AGENTFABRIC_PG_KEEP=1)" >&2
  fi
}
trap cleanup EXIT

if container_running; then
  echo "Using existing running container: $NAME" >&2
elif container_exists; then
  echo "Container exists but not running; starting: $NAME" >&2
  docker start "$NAME" >/dev/null
else
  start_container
  started_by_script=1
fi

# Wait for readiness.
# Use pg_isready inside the container.
end=$((SECONDS + WAIT_SECS))
while true; do
  if docker exec "$NAME" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1; then
    break
  fi
  if [[ "$SECONDS" -ge "$end" ]]; then
    echo "Postgres did not become ready within ${WAIT_SECS}s" >&2
    docker logs "$NAME" | tail -n 200 >&2 || true
    exit 1
  fi
  sleep 1
done

export AGENTFABRIC_TEST_DB_URL="postgresql+psycopg://${PG_USER}:${PG_PASSWORD}@localhost:${HOST_PORT}/${PG_DB}"

echo "Running blackbox tests with AGENTFABRIC_TEST_DB_URL=$AGENTFABRIC_TEST_DB_URL" >&2
cd "$REPO_ROOT"

# Run all Postgres blackbox test files (coverage from small -> large).
# Any extra args passed to this script are forwarded to pytest.
uv run pytest -q tests/test_inout_postgres*blackbox.py "$@"
