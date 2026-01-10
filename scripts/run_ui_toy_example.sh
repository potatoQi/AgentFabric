#!/usr/bin/env bash
set -euo pipefail

# One-command toy runner for AgentFabric UI.
#
# What it does:
#   1) Starts a disposable postgres:16 docker container
#   2) Generates a temporary config (based on examples/acebench_schema.yaml) with a random schema
#   3) Seeds 100 diverse rows + previewable file URLs
#   4) Launches the Streamlit UI
#
# Usage:
#   bash scripts/run_ui_toy_example.sh
#   bash scripts/run_ui_toy_example.sh --help
#
# Optional env:
#   AGENTFABRIC_UI_PG_IMAGE=postgres:16
#   AGENTFABRIC_UI_PG_PORT=59687
#   AGENTFABRIC_UI_KEEP_PG=1          # keep container running after UI exits
#   AGENTFABRIC_UI_NO_BROWSER=1       # do not auto-open browser
#   AGENTFABRIC_UI_HOST=127.0.0.1
#   AGENTFABRIC_UI_PORT=8501

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'TXT'
AgentFabric UI toy runner

Starts a disposable Postgres, seeds toy data, then launches the UI.

Usage:
  bash scripts/run_ui_toy_example.sh

Optional env:
  AGENTFABRIC_UI_PG_IMAGE=postgres:16
  AGENTFABRIC_UI_PG_PORT=59687
  AGENTFABRIC_UI_KEEP_PG=1          # keep container running after UI exits
  AGENTFABRIC_UI_NO_BROWSER=1       # do not auto-open browser
  AGENTFABRIC_UI_HOST=127.0.0.1
  AGENTFABRIC_UI_PORT=8501
TXT
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found; please install Docker first" >&2
  exit 1
fi

IMAGE="${AGENTFABRIC_UI_PG_IMAGE:-postgres:16}"
PG_USER="${AGENTFABRIC_UI_PG_USER:-agentfabric}"
PG_PASSWORD="${AGENTFABRIC_UI_PG_PASSWORD:-pass}"
PG_DB="${AGENTFABRIC_UI_PG_DB:-agentfabric}"
WAIT_SECS="${AGENTFABRIC_UI_PG_WAIT_SECS:-60}"
KEEP_PG="${AGENTFABRIC_UI_KEEP_PG:-0}"

HOST="${AGENTFABRIC_UI_HOST:-127.0.0.1}"
UI_PORT="${AGENTFABRIC_UI_PORT:-8501}"
NO_BROWSER="${AGENTFABRIC_UI_NO_BROWSER:-0}"

suffix="$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
NAME="agentfabric-ui-toy-${suffix}"

# Fixed default port for convenience (override via AGENTFABRIC_UI_PG_PORT).
HOST_PORT="${AGENTFABRIC_UI_PG_PORT:-59687}"

ARTIFACT_DIR="$(mktemp -d -t agentfabric-ui-artifacts-XXXXXX)"
CFG_DIR="$(mktemp -d -t agentfabric-ui-cfg-XXXXXX)"
CFG_PATH="$CFG_DIR/acebench_schema_ui.yaml"

cleanup() {
  if [[ "$KEEP_PG" != "1" ]]; then
    echo "Stopping postgres container: $NAME" >&2
    docker stop "$NAME" >/dev/null 2>&1 || true
  else
    echo "Keeping postgres container: $NAME (AGENTFABRIC_UI_KEEP_PG=1)" >&2
  fi

  rm -rf "$CFG_DIR" >/dev/null 2>&1 || true
  rm -rf "$ARTIFACT_DIR" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Starting postgres container: $NAME ($IMAGE) on localhost:$HOST_PORT" >&2
docker run --rm -d --name "$NAME" \
  -e "POSTGRES_USER=$PG_USER" \
  -e "POSTGRES_PASSWORD=$PG_PASSWORD" \
  -e "POSTGRES_DB=$PG_DB" \
  -p "$HOST_PORT:5432" \
  "$IMAGE" >/dev/null || {
  echo "Failed to start Postgres on port $HOST_PORT (maybe already in use)." >&2
  echo "Try setting AGENTFABRIC_UI_PG_PORT to a free port." >&2
  exit 1
}

# Wait for readiness.
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

DB_URL="postgresql+psycopg://${PG_USER}:${PG_PASSWORD}@localhost:${HOST_PORT}/${PG_DB}"
ARTIFACT_BASE_URL="file://${ARTIFACT_DIR}"

if [[ ! -f "examples/acebench_schema.yaml" ]]; then
  echo "Missing examples/acebench_schema.yaml" >&2
  exit 1
fi

echo "Generating temp config: $CFG_PATH" >&2
CFG_PATH="$CFG_PATH" DB_URL="$DB_URL" ARTIFACT_BASE_URL="$ARTIFACT_BASE_URL" uv run python - <<'PY'
import uuid
from pathlib import Path
import os
import yaml

src = Path("examples/acebench_schema.yaml")
data = yaml.safe_load(src.read_text(encoding="utf-8"))
assert isinstance(data, dict)
data["postgres_schema"] = f"af_ui_{uuid.uuid4().hex[:10]}"
data["db_url"] = os.environ["DB_URL"]
data["artifact_base_url"] = os.environ["ARTIFACT_BASE_URL"]
dst = Path(os.environ["CFG_PATH"])
dst.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
print(str(dst))
PY

echo "Seeding toy data (100 diverse rows) + previewable file URLs" >&2
CFG_PATH="$CFG_PATH" ARTIFACT_DIR="$ARTIFACT_DIR" DB_URL="$DB_URL" ARTIFACT_BASE_URL="$ARTIFACT_BASE_URL" uv run python - <<'PY'
from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
import random
import os

from sqlalchemy import text

from agentfabric import AgentFabric

db, store = AgentFabric(os.environ["CFG_PATH"])
if store is None:
  raise SystemExit("artifact_base_url is missing in config; cannot seed previewable artifacts")

schema = db.registry.postgres_schema
if schema:
  with db.engine.begin() as conn:
    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

db.init_schema()

Instance = db.models.get("ace_instance")
Traj = db.models.get("ace_traj")
if Instance is None or Traj is None:
    raise SystemExit("examples/acebench_schema.yaml must define ace_instance and ace_traj")

# Create local files, store them (file://), and write their URLs into the DB.
artifact_dir = Path(os.environ["ARTIFACT_DIR"])

agents = ["agent-a", "agent-b", "agent-c"]
models = ["model-x", "model-y", "model-z"]
repos = ["repo/alpha", "repo/beta", "repo/gamma"]
images = ["ubuntu:22.04", "python:3.11", "debian:12"]
now = datetime.now(timezone.utc)
random.seed(42)

for i in range(100):
  instance_id = f"ins_ui_{i:03d}"
  cov = round(((i % 20) / 20.0), 2)

  # URLs: keep many non-None so preview + filters are testable.
  prd_path = artifact_dir / f"prd_{i:03d}.txt"
  prd_path.write_text(f"prd for {instance_id}\n", encoding="utf-8")
  prd_url = store.put(str(prd_path), f"runs/ui/prd/{instance_id}.txt").url

  # Additional formats for preview debugging.
  json_path = artifact_dir / f"payload_{i:03d}.json"
  json_path.write_text(
    '{"instance_id": "%s", "i": %d, "ok": %s, "tags": ["ui", "%s"]}\n'
    % (instance_id, i, "true" if i % 2 == 0 else "false", f"t{i%7}"),
    encoding="utf-8",
  )
  json_url = store.put(str(json_path), f"runs/ui/json/{instance_id}.json").url

  md_path = artifact_dir / f"note_{i:03d}.md"
  md_path.write_text(
    f"# Note for {instance_id}\n\n- cov: {cov}\n- idx: {i}\n\n```diff\n+ hello\n- bye\n```\n",
    encoding="utf-8",
  )
  md_url = store.put(str(md_path), f"runs/ui/md/{instance_id}.md").url

  gold_patch_url = None
  test_patch_url = None
  if i % 3 != 0:
    gp = artifact_dir / f"gold_patch_{i:03d}.diff"
    gp.write_text(f"diff --git a/x b/x\n# gold patch {instance_id}\n", encoding="utf-8")
    gold_patch_url = store.put(str(gp), f"runs/ui/gold_patch/{instance_id}.diff").url
  if i % 4 != 0:
    tp = artifact_dir / f"test_patch_{i:03d}.diff"
    tp.write_text(f"diff --git a/y b/y\n# test patch {instance_id}\n", encoding="utf-8")
    test_patch_url = store.put(str(tp), f"runs/ui/test_patch/{instance_id}.diff").url

  # Lists + scalars: mixed None/non-None.
  f2p = None if i % 5 == 0 else [f"f{i%7}", f"f{(i+1)%7}"]
  p2p = None if i % 6 == 0 else [f"p{i%11}"]

  repo = None if i % 10 == 0 else repos[i % len(repos)]
  commit = None if i % 8 == 0 else f"{i:06x}{(i*i)%0xFFFFFF:06x}"
  image_name = None if i % 9 == 0 else images[i % len(images)]

  base_pass_rate = None if i % 7 == 0 else round(0.1 + (i % 9) * 0.1, 2)
  lines = None if i % 11 == 0 else (50 + i * 3)
  test_count = None if i % 12 == 0 else (1 + (i % 20))

  commit_time = (now - timedelta(days=i)).isoformat() if i % 4 != 0 else None
  end_time_data = (now - timedelta(hours=i)).isoformat() if i % 3 == 0 else None

  db.add(
    Instance(
      instance_id=instance_id,
      gold_patch_cov=cov,
      gold_patch_url=gold_patch_url,
      test_patch_url=test_patch_url,
      json_url=json_url,
      md_url=md_url,
      f2p=f2p,
      p2p=p2p,
      image_name=image_name,
      repo=repo,
      commit=commit,
      prd_url=prd_url,
      base_pass_rate=base_pass_rate,
      lines=lines,
      test_count=test_count,
      commit_time=commit_time,
      end_time_data=end_time_data,
      extra={"tag": "ui", "i": i, "bucket": (i % 3)},
    )
  )

  agent = agents[i % len(agents)]
  model = models[i % len(models)]
  attempt = i % 3

  patch_url = None
  if i % 2 == 0:
    patch_path = artifact_dir / f"patch_{i:03d}.diff"
    patch_path.write_text(f"diff --git a/z b/z\n# patch {instance_id} attempt={attempt}\n", encoding="utf-8")
    patch_url = store.put(str(patch_path), f"runs/ui/patch/{instance_id}_{attempt}.diff").url

  traj_url = None
  if i % 5 != 0:
    traj_path = artifact_dir / f"traj_{i:03d}.jsonl"
    traj_path.write_text("{\"step\": 1}\n{\"step\": 2}\n", encoding="utf-8")
    traj_url = store.put(str(traj_path), f"runs/ui/traj/{instance_id}_{attempt}.jsonl").url

  metric = None
  if i % 3 != 0:
    metric = {
      "score": round(random.random(), 3),
      "pass": bool(i % 4),
      "tokens": 1000 + i,
    }
    metric = json.dumps(metric, ensure_ascii=False)

  end_time_infer = (now - timedelta(minutes=i)).isoformat() if i % 2 == 1 else None
  end_time_harness = (now - timedelta(minutes=i * 2)).isoformat() if i % 7 == 0 else None

  db.upsert(
    "ace_traj",
    Traj(
      instance_id=instance_id,
      gold_patch_cov=cov,
      agent=agent,
      model=model,
      attempt=attempt,
      patch_url=patch_url,
      traj_url=traj_url,
      metric=metric,
      end_time_infer=end_time_infer,
      end_time_harness=end_time_harness,
      extra={"kind": "toy", "i": i, "attempt": attempt},
    ),
  )

print("seed ok")
print("db_url=", os.environ.get("DB_URL"))
print("config=", os.environ.get("CFG_PATH"))
print("artifact_base_url=", os.environ.get("ARTIFACT_BASE_URL"))
PY

echo "Launching UI…" >&2
echo "  Config: $CFG_PATH" >&2

UI_ARGS=(
  ui
  --config "$CFG_PATH"
  --host "$HOST"
  --port "$UI_PORT"
)
if [[ "$NO_BROWSER" == "1" ]]; then
  UI_ARGS+=(--no-browser)
fi

uv run agentfabric "${UI_ARGS[@]}"
