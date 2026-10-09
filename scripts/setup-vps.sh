#!/usr/bin/env bash
# =============================================================================
# setup-vps.sh — Prepare an Ubuntu 24.04 VPS to run SciBot
#
# Run as root (or with sudo) on the VPS:
#   curl -fsSL https://raw.githubusercontent.com/.../setup-vps.sh | bash
#   -- or --
#   bash scripts/setup-vps.sh
# =============================================================================
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/scibot}"

info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[1;32m[ OK ]\033[0m  $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
fatal() { echo -e "\033[1;31m[FAIL]\033[0m  $*" >&2; exit 1; }

# ── 0. Prerequisites ──────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || fatal "Please run as root or with sudo."
. /etc/os-release
[[ "$ID" == "ubuntu" ]] || warn "This script targets Ubuntu; your OS is '$ID' — proceed with caution."

# ── 1. Install Docker Engine ──────────────────────────────────────────────────
info "Installing Docker Engine..."
apt-get update -qq
apt-get install -y -qq ca-certificates curl

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -qq
apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker
ok "Docker $(docker --version) installed."

# ── 2. Configure Docker log rotation ─────────────────────────────────────────
info "Configuring Docker log rotation..."
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
systemctl restart docker
ok "Log rotation configured (10 MB × 3 files per container)."

# ── 3. Configure firewall (ufw) ───────────────────────────────────────────────
if command -v ufw &>/dev/null; then
    info "Configuring ufw firewall..."
    ufw allow OpenSSH
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 443/udp   # HTTP/3
    ufw --force enable
    ok "ufw enabled: SSH, HTTP(S) allowed; all other inbound blocked."
else
    warn "ufw not found — skip firewall setup. Configure your VPS firewall manually."
fi

# ── 4. Clone the repository ───────────────────────────────────────────────────
if [[ -d "$REPO_DIR/.git" ]]; then
    info "Repo already exists at $REPO_DIR — pulling latest..."
    git -C "$REPO_DIR" pull
else
    info "Cloning repository to $REPO_DIR..."
    read -r -p "  Enter your Git repo URL (e.g. https://github.com/user/scibot.git): " REPO_URL
    git clone "$REPO_URL" "$REPO_DIR"
fi
ok "Repository ready at $REPO_DIR."

# ── 5. Create .env from template ─────────────────────────────────────────────
if [[ ! -f "$REPO_DIR/.env" ]]; then
    info "Creating .env from .env.example..."
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    # Replace the development Postgres password with a random one.
    PG_PASSWORD="$(openssl rand -hex 24)"
    sed -i "s/scibot:scibot@/scibot:${PG_PASSWORD}@/g; s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${PG_PASSWORD}/" "$REPO_DIR/.env"
    ok "Generated a random POSTGRES_PASSWORD."
    echo ""
    warn "IMPORTANT: Edit $REPO_DIR/.env and fill in:"
    echo "  • DOMAIN=yourdomain.com          (must point to this VPS IP via DNS)"
    echo "  • DEFAULT_LLM_PROVIDER and the matching API key"
    echo "  • DEFAULT_EMBEDDING_PROVIDER and the matching API key"
    echo "  • Any optional research/search API keys"
    echo ""
    read -r -p "  Open .env for editing now? [Y/n]: " OPEN_ENV
    if [[ "${OPEN_ENV,,}" != "n" ]]; then
        "${EDITOR:-nano}" "$REPO_DIR/.env"
    fi
else
    ok ".env already exists — skipping."
fi

# ── 6. Add DOMAIN to .env if missing ─────────────────────────────────────────
if ! grep -q "^DOMAIN=" "$REPO_DIR/.env"; then
    read -r -p "  Enter your domain name for HTTPS (leave blank to skip): " DOMAIN_INPUT
    if [[ -n "$DOMAIN_INPUT" ]]; then
        echo "DOMAIN=$DOMAIN_INPUT" >> "$REPO_DIR/.env"
        ok "DOMAIN=$DOMAIN_INPUT added to .env"
    else
        warn "DOMAIN not set — Caddy will fail to start. Add 'DOMAIN=...' to .env manually."
    fi
fi

# ── 7. Pull images and start services ────────────────────────────────────────
# Production = base compose file + HTTPS/limits override. The SciBot image is
# pulled from Docker Hub; if that fails it is built on this machine instead.
info "Pulling images and starting services..."
cd "$REPO_DIR"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
if "${COMPOSE[@]}" pull; then
    "${COMPOSE[@]}" up -d
else
    warn "Could not pull the published image — building locally (this takes a while)..."
    "${COMPOSE[@]}" pull --ignore-buildable
    "${COMPOSE[@]}" up -d --build
fi

ok "Services started. Waiting 30 s for health checks..."
sleep 30

# ── 8. Verify ─────────────────────────────────────────────────────────────────
info "Service status:"
"${COMPOSE[@]}" ps

echo ""
ok "=== Setup complete ==="
echo ""
echo "  App:     https://$(grep '^DOMAIN=' .env | cut -d= -f2)"
echo "  Logs:    docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f"
echo "  Status:  docker compose -f docker-compose.yml -f docker-compose.prod.yml ps"
echo "  Update:  docker compose -f docker-compose.yml -f docker-compose.prod.yml pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
echo "  Stop:    docker compose down"
echo ""
echo "  To confirm internal ports are NOT reachable from outside:"
echo "  Run from your local machine:"
echo "    nmap -p 6379,6380,8000,27017,8080 <VPS-IP>"
echo "  All should show 'filtered' or 'closed'."
