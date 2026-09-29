#!/usr/bin/env bash
#
# setup_flower_hackathon.sh
#
# Automates the setup steps of the README for:
#
#   1. Create a key pair for each of the four SuperNodes
#   2. Log in to SuperGrid and register the SuperNodes
#   3. Launch the SuperNodes (Docker Compose by default, or native processes)
#
# The script does NOT clone the repo. Run it from the repo root (the folder
# containing compose.yaml and data/).
#
# The federation setup (create a `deployment` federation and add the SuperNodes)
# and running the agent app are done on flower.ai / with the Flower CLI, so the
# script prints reminders for them.
#
# Usage:
#   ./setup_flower_hackathon.sh                 # Docker Compose mode
#
# Environment:
#   FLWR_MODEL_API_KEY   Model API key (flower.ai -> Profile -> Settings -> API Keys).
#                        If unset, you will be prompted for it.
#
# On Windows, run this from WSL or Git Bash.

set -euo pipefail

SUPERLINK_ADDR="fleet-supergrid.flower.ai:443"

# Example site names/locations shown on the federation map (order = key index 0..3).
NAMES=(
  "Building A: Solaire"
  "Building B: Sales Force Tower"

)
LOCATIONS=(
  "-37.788241,-122.393614"
  "-37.789774,-22.396932"
 
)
NUM_NODES=${#NAMES[@]}

MODE="docker"      # docker | native
LAUNCH=1

# ---------- helpers ----------
info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed. $2"
}

usage() {
  sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

# ---------- parse args ----------
for arg in "$@"; do
  case "$arg" in
    --no-docker)  MODE="native" ;;
    --setup-only) LAUNCH=0 ;;
    -h|--help)    usage ;;
    *) die "Unknown option: $arg (try --help)" ;;
  esac
done

# ---------- prerequisites ----------
info "Checking prerequisites"
need ssh-keygen "Install OpenSSH (on Windows, use WSL or Git Bash)."
need uvx "Install uv: https://docs.astral.sh/uv/getting-started/installation/"

if [[ "$LAUNCH" -eq 1 && "$MODE" == "docker" ]]; then
  [[ -f compose.yaml ]] || die "compose.yaml not found. Run this script from the repo root, or use --no-docker."
  need docker "Install Docker, or re-run with --no-docker."
  docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker, or re-run with --no-docker."
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 ('docker compose') is required."
fi

# ---------- model API key ----------
if [[ "$LAUNCH" -eq 1 && -z "${FLWR_MODEL_API_KEY:-}" ]]; then
  read -r -s -p "Enter your FLWR_MODEL_API_KEY (flower.ai -> Profile -> Settings -> API Keys): " FLWR_MODEL_API_KEY
  echo
  [[ -n "$FLWR_MODEL_API_KEY" ]] || die "A model API key is required to launch the SuperNodes."
fi
export FLWR_MODEL_API_KEY="${FLWR_MODEL_API_KEY:-}"

# ---------- 1. create key pairs ----------
info "Creating SuperNode key pairs in ./keys"
mkdir -p keys
for ((i = 0; i < NUM_NODES; i++)); do
  if [[ -f "keys/supernode-$i" && -f "keys/supernode-$i.pub" ]]; then
    echo "  keys/supernode-$i already exists — keeping it"
  else
    ssh-keygen -t ecdsa -b 384 -N "" -C "supernode-$i" -f "keys/supernode-$i" -q
    echo "  created keys/supernode-$i"
  fi
done

# ---------- 2. login + register ----------
info "Logging in to SuperGrid (follow the prompts)"
uvx flwr login supergrid

info "Registering SuperNodes"
for ((i = 0; i < NUM_NODES; i++)); do
  marker="keys/.registered-$i"
  if [[ -f "$marker" ]]; then
    echo "  supernode-$i (${NAMES[$i]}) already registered by this script — skipping"
    continue
  fi
  if uvx flwr supernode register "keys/supernode-$i.pub" supergrid \
       --name="${NAMES[$i]}" --location="${LOCATIONS[$i]}"; then
    touch "$marker"
  else
    warn "Registration of supernode-$i failed (it may already be registered). Continuing."
  fi
done

# ---------- next-steps reminder (printed before launch, since launch blocks) ----------
print_next_steps() {
  cat <<'EOF'

----------------------------------------------------------------------
Next steps (done outside this script):

  - Add the SuperNodes to the `deployment` federation @alaind/smart-legos
    (via the Flower CLI or flower.ai):
      uvx flwr supernode list supergrid --verbose      # get the SuperNode IDs
      uvx flwr federation add-supernode <supernode-id> @alaind/smart-legos supergrid
      https://flower.ai/docs/framework/how-to-connect-supernodes-to-supergrid.html

  - Run the agent app (@flwrlabs/collaborative-agent):
      https://flower.ai/docs/agent/tutorials/get-started-with-flower-agent.html
      https://flower.ai/docs/agent/tutorials/quickstart.html

  Check that nodes are online with:
      uvx flwr supernode list supergrid --verbose
----------------------------------------------------------------------
EOF
}

if [[ "$LAUNCH" -eq 0 ]]; then
  info "Setup complete (--setup-only): not launching SuperNodes."
  print_next_steps
  exit 0
fi

print_next_steps

# ---------- 3. launch ----------
if [[ "$MODE" == "docker" ]]; then
  info "Launching SuperNodes with Docker Compose (Ctrl+C to stop)"
  cleanup() {
    echo
    info "Stopping and removing containers"
    docker compose down || true
  }
  trap cleanup EXIT
  docker compose up
else
  info "Launching SuperNodes natively (no Docker). Logs: ./logs/supernode-N.log"
  warn "In Docker mode, Compose mounts each node's data/ folder into its container."
  warn "Natively, nodes use your local filesystem. Make sure the agent can find each"
  warn "node's data (data/supernode-a .. d). Volume mounts from compose.yaml, if present:"
  if [[ -f compose.yaml ]]; then
    grep -n -A4 'volumes:' compose.yaml 2>/dev/null | sed 's/^/    /' >&2 || true
  fi

  mkdir -p logs
  PIDS=()
  cleanup() {
    echo
    info "Stopping SuperNodes"
    for pid in "${PIDS[@]:-}"; do
      [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
  }
  trap cleanup EXIT INT TERM

  for ((i = 0; i < NUM_NODES; i++)); do
    uvx --from flwr flower-supernode \
      --superlink="$SUPERLINK_ADDR" \
      --auth-supernode-private-key="keys/supernode-$i" \
      --allow-runtime-dependency-installation \
      >"logs/supernode-$i.log" 2>&1 &
    PIDS+=("$!")
    echo "  started supernode-$i (pid ${PIDS[-1]}) -> logs/supernode-$i.log"
  done

  info "SuperNodes running. Verify with: uvx flwr supernode list supergrid --verbose"
  info "Press Ctrl+C to stop them."
  wait
fi
