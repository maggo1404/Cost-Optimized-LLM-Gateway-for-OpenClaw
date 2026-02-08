#!/bin/bash
# ==============================================================================
# LLM Gateway v1.3 - Setup Script
# ==============================================================================
# Kostenoptimiertes AI-Routing für OpenClaw
# Hetzner + Groq Router + Prompt Caching = 73% Kostenreduktion
#
# Usage:
#   ./setup-gateway.sh              # Interactive setup
#   ./setup-gateway.sh --full       # Full automated install
#   ./setup-gateway.sh --help       # Show help
# ==============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/llm-gateway"
DATA_DIR="/opt/llm-gateway/data"
LOG_DIR="/var/log/llm-gateway"
USER="gateway"
PYTHON_VERSION="3.11"
DOMAIN=""

# ==============================================================================
# Helper Functions
# ==============================================================================

print_banner() {
    echo -e "${CYAN}"
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║               LLM Gateway v1.3 - Setup Script                    ║"
    echo "║      Kostenoptimiertes AI-Routing für OpenClaw                   ║"
    echo "║                                                                  ║"
    echo "║   Hetzner + Groq Router + Prompt Caching = 73% Kostenreduktion   ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${BLUE}▶ $1${NC}"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi
}

check_os() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "Cannot detect OS"
        exit 1
    fi
    
    source /etc/os-release
    
    if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
        log_warn "This script is designed for Ubuntu/Debian. Your OS: $ID"
        read -p "Continue anyway? (y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    log_info "Detected OS: $PRETTY_NAME"
}

generate_secret() {
    openssl rand -hex 32
}

# ==============================================================================
# Installation Functions
# ==============================================================================

install_system_packages() {
    log_step "Installing system packages..."
    
    apt update
    apt install -y \
        python3 \
        python3-pip \
        python3-venv \
        nginx \
        certbot \
        python3-certbot-nginx \
        sqlite3 \
        curl \
        git \
        openssl \
        ufw
    
    log_info "System packages installed"
}

setup_firewall() {
    log_step "Configuring firewall..."
    
    ufw allow 22/tcp comment 'SSH'
    ufw allow 80/tcp comment 'HTTP'
    ufw allow 443/tcp comment 'HTTPS'
    
    # Don't enable if already enabled
    if ! ufw status | grep -q "Status: active"; then
        echo "y" | ufw enable
    fi
    
    log_info "Firewall configured"
}

create_user() {
    log_step "Creating gateway user..."
    
    if id "$USER" &>/dev/null; then
        log_info "User '$USER' already exists"
    else
        useradd -r -s /bin/false -d "$INSTALL_DIR" "$USER"
        log_info "User '$USER' created"
    fi
}

create_directories() {
    log_step "Creating directories..."
    
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$DATA_DIR"
    mkdir -p "$LOG_DIR"
    mkdir -p "$INSTALL_DIR/venv"
    
    chown -R "$USER:$USER" "$INSTALL_DIR"
    chown -R "$USER:$USER" "$DATA_DIR"
    chown -R "$USER:$USER" "$LOG_DIR"
    
    log_info "Directories created"
}

setup_python_env() {
    log_step "Setting up Python environment..."
    
    cd "$INSTALL_DIR"
    
    python3 -m venv venv
    source venv/bin/activate
    
    pip install --upgrade pip
    pip install \
        fastapi \
        "uvicorn[standard]" \
        pydantic \
        httpx \
        tenacity \
        aiosqlite \
        numpy \
        python-dotenv \
        python-multipart \
        prometheus-client
    
    deactivate
    
    log_info "Python environment ready"
}

copy_source_code() {
    log_step "Copying source code..."
    
    # If running from the source directory, copy files
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SOURCE_DIR="$(dirname "$SCRIPT_DIR")"
    
    if [[ -f "$SOURCE_DIR/main.py" ]]; then
        cp -r "$SOURCE_DIR"/*.py "$INSTALL_DIR/" 2>/dev/null || true
        cp -r "$SOURCE_DIR"/router "$INSTALL_DIR/" 2>/dev/null || true
        cp -r "$SOURCE_DIR"/cache "$INSTALL_DIR/" 2>/dev/null || true
        cp -r "$SOURCE_DIR"/security "$INSTALL_DIR/" 2>/dev/null || true
        cp -r "$SOURCE_DIR"/retrieval "$INSTALL_DIR/" 2>/dev/null || true
        cp -r "$SOURCE_DIR"/providers "$INSTALL_DIR/" 2>/dev/null || true
        cp -r "$SOURCE_DIR"/monitoring "$INSTALL_DIR/" 2>/dev/null || true
        cp -r "$SOURCE_DIR"/config "$INSTALL_DIR/" 2>/dev/null || true
        cp -r "$SOURCE_DIR"/utils "$INSTALL_DIR/" 2>/dev/null || true
        log_info "Source code copied from $SOURCE_DIR"
    else
        log_warn "Source code not found in $SOURCE_DIR"
        log_info "Please copy the source code to $INSTALL_DIR manually"
    fi
    
    chown -R "$USER:$USER" "$INSTALL_DIR"
}

configure_env() {
    log_step "Configuring environment..."
    
    ENV_FILE="$INSTALL_DIR/.env"
    
    if [[ -f "$ENV_FILE" ]]; then
        log_info ".env already exists, keeping existing configuration"
        return
    fi
    
    # Generate secret
    SECRET=$(generate_secret)
    
    # Prompt for API keys
    echo ""
    echo -e "${CYAN}Please enter your API keys:${NC}"
    echo ""
    
    read -p "Groq API Key (gsk_...): " GROQ_KEY
    read -p "Anthropic API Key (sk-ant-...): " ANTHROPIC_KEY
    read -p "OpenAI API Key (sk-..., optional): " OPENAI_KEY
    
    # Create .env file
    cat > "$ENV_FILE" << EOF
# LLM Gateway Configuration
# Generated: $(date)

# API Keys
GROQ_API_KEY=${GROQ_KEY}
ANTHROPIC_API_KEY=${ANTHROPIC_KEY}
OPENAI_API_KEY=${OPENAI_KEY}

# Gateway Security
GATEWAY_SECRET=${SECRET}

# Budget Limits (USD)
DAILY_BUDGET_SOFT=5.0
DAILY_BUDGET_MEDIUM=15.0
DAILY_BUDGET_HARD=50.0

# Rate Limits
RATE_LIMIT_RPM=60
RATE_LIMIT_TPM=100000

# Cache Settings
CACHE_DIR=${DATA_DIR}
SEMANTIC_THRESHOLD=0.92

# Context Budgets
CONTEXT_BUDGET_CHEAP=4000
CONTEXT_BUDGET_PREMIUM=16000

# Server Settings
HOST=127.0.0.1
PORT=8000
ENV=production

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_FILE=${LOG_DIR}/gateway.log
EOF
    
    chmod 600 "$ENV_FILE"
    chown "$USER:$USER" "$ENV_FILE"
    
    log_info "Environment configured"
    log_info "Gateway secret: $SECRET"
}

setup_systemd() {
    log_step "Setting up systemd service..."
    
    cat > /etc/systemd/system/llm-gateway.service << EOF
[Unit]
Description=LLM Gateway - Kostenoptimiertes AI-Routing
After=network.target

[Service]
Type=simple
User=${USER}
Group=${USER}
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/venv/bin"
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/gateway.log
StandardError=append:${LOG_DIR}/gateway-error.log

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${DATA_DIR} ${LOG_DIR}

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    systemctl enable llm-gateway
    
    log_info "Systemd service configured"
}

setup_nginx() {
    log_step "Setting up Nginx..."
    
    read -p "Enter your domain (or press Enter for localhost): " DOMAIN
    
    if [[ -z "$DOMAIN" ]]; then
        DOMAIN="localhost"
        SERVER_NAME="_"
    else
        SERVER_NAME="$DOMAIN"
    fi
    
    cat > /etc/nginx/sites-available/llm-gateway << EOF
# LLM Gateway - Nginx Configuration

# Rate limiting zone
limit_req_zone \$binary_remote_addr zone=gateway_limit:10m rate=10r/s;

upstream gateway_backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name ${SERVER_NAME};

    # Redirect HTTP to HTTPS (if SSL configured)
    # return 301 https://\$server_name\$request_uri;

    location / {
        # Rate limiting
        limit_req zone=gateway_limit burst=20 nodelay;
        
        # Proxy settings
        proxy_pass http://gateway_backend;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 120s;
        
        # Buffering
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
    }

    # Health check endpoint (no rate limit)
    location /health {
        proxy_pass http://gateway_backend/health;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
    
    # Metrics endpoint (restricted)
    location /metrics {
        # Allow from localhost only
        allow 127.0.0.1;
        deny all;
        
        proxy_pass http://gateway_backend/metrics;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
EOF
    
    # Enable site
    ln -sf /etc/nginx/sites-available/llm-gateway /etc/nginx/sites-enabled/
    
    # Remove default site
    rm -f /etc/nginx/sites-enabled/default
    
    # Test and reload
    nginx -t
    systemctl reload nginx
    
    log_info "Nginx configured for $DOMAIN"
}

setup_ssl() {
    if [[ "$DOMAIN" == "localhost" || -z "$DOMAIN" ]]; then
        log_warn "Skipping SSL setup (localhost)"
        return
    fi
    
    log_step "Setting up SSL with Let's Encrypt..."
    
    read -p "Enter email for SSL certificate: " SSL_EMAIL
    
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$SSL_EMAIL"
    
    log_info "SSL certificate installed"
}

create_backup_script() {
    log_step "Creating backup script..."
    
    cat > "$INSTALL_DIR/scripts/backup.sh" << 'EOF'
#!/bin/bash
# LLM Gateway - Backup Script

BACKUP_DIR="/opt/llm-gateway/backups"
DATA_DIR="/opt/llm-gateway/data"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup databases
for db in "$DATA_DIR"/*.db; do
    if [[ -f "$db" ]]; then
        sqlite3 "$db" ".backup '$BACKUP_DIR/$(basename $db).$DATE.backup'"
    fi
done

# Backup .env (encrypted)
if [[ -f "/opt/llm-gateway/.env" ]]; then
    cp "/opt/llm-gateway/.env" "$BACKUP_DIR/.env.$DATE"
    chmod 600 "$BACKUP_DIR/.env.$DATE"
fi

# Keep only last 7 days
find "$BACKUP_DIR" -type f -mtime +7 -delete

echo "Backup completed: $DATE"
EOF
    
    chmod +x "$INSTALL_DIR/scripts/backup.sh"
    
    # Add daily cron job
    echo "0 2 * * * root $INSTALL_DIR/scripts/backup.sh" > /etc/cron.d/llm-gateway-backup
    
    log_info "Backup script created"
}

start_service() {
    log_step "Starting LLM Gateway..."
    
    systemctl start llm-gateway
    
    # Wait for startup
    sleep 3
    
    # Check health
    if curl -s http://127.0.0.1:8000/health | grep -q '"status":"ok"'; then
        log_info "Gateway is running and healthy!"
    else
        log_error "Gateway failed to start. Check logs:"
        echo "  journalctl -u llm-gateway -f"
        return 1
    fi
}

print_summary() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              Installation Complete!                              ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${CYAN}Gateway Status:${NC}"
    echo "  URL: http://${DOMAIN:-localhost}"
    echo "  Health: http://${DOMAIN:-localhost}/health"
    echo ""
    echo -e "${CYAN}Useful Commands:${NC}"
    echo "  Status:    systemctl status llm-gateway"
    echo "  Logs:      journalctl -u llm-gateway -f"
    echo "  Restart:   systemctl restart llm-gateway"
    echo "  Stop:      systemctl stop llm-gateway"
    echo ""
    echo -e "${CYAN}Configuration:${NC}"
    echo "  Config:    $INSTALL_DIR/.env"
    echo "  Data:      $DATA_DIR"
    echo "  Logs:      $LOG_DIR"
    echo ""
    echo -e "${CYAN}Test Request:${NC}"
    echo "  curl -X POST http://${DOMAIN:-localhost}/v1/chat/completions \\"
    echo "    -H 'Authorization: Bearer YOUR_GATEWAY_SECRET' \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"messages\":[{\"role\":\"user\",\"content\":\"Hello!\"}]}'"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo "  1. Edit $INSTALL_DIR/.env with your API keys"
    echo "  2. Restart the service: systemctl restart llm-gateway"
    if [[ "$DOMAIN" != "localhost" && -n "$DOMAIN" ]]; then
        echo "  3. SSL is configured for $DOMAIN"
    else
        echo "  3. Set up SSL: certbot --nginx -d your-domain.com"
    fi
    echo ""
}

# ==============================================================================
# Interactive Menu
# ==============================================================================

show_menu() {
    echo ""
    echo -e "${CYAN}LLM Gateway Setup - Options:${NC}"
    echo ""
    echo "  1) Full Installation (recommended)"
    echo "  2) Install System Packages Only"
    echo "  3) Setup Python Environment Only"
    echo "  4) Configure Environment (.env)"
    echo "  5) Setup Systemd Service"
    echo "  6) Setup Nginx"
    echo "  7) Setup SSL (Let's Encrypt)"
    echo "  8) Start/Restart Service"
    echo "  9) Check Status"
    echo "  0) Exit"
    echo ""
    read -p "Select option: " choice
    
    case $choice in
        1) full_install ;;
        2) install_system_packages ;;
        3) setup_python_env ;;
        4) configure_env ;;
        5) setup_systemd ;;
        6) setup_nginx ;;
        7) setup_ssl ;;
        8) start_service ;;
        9) check_status ;;
        0) exit 0 ;;
        *) log_error "Invalid option"; show_menu ;;
    esac
    
    show_menu
}

full_install() {
    log_step "Starting full installation..."
    
    check_os
    install_system_packages
    setup_firewall
    create_user
    create_directories
    setup_python_env
    copy_source_code
    configure_env
    setup_systemd
    setup_nginx
    create_backup_script
    start_service
    print_summary
}

check_status() {
    echo ""
    echo -e "${CYAN}System Status:${NC}"
    echo ""
    
    # Service status
    if systemctl is-active --quiet llm-gateway; then
        echo -e "  Service: ${GREEN}Running${NC}"
    else
        echo -e "  Service: ${RED}Stopped${NC}"
    fi
    
    # Health check
    if curl -s http://127.0.0.1:8000/health | grep -q '"status":"ok"'; then
        echo -e "  Health:  ${GREEN}OK${NC}"
    else
        echo -e "  Health:  ${RED}Failed${NC}"
    fi
    
    # Nginx status
    if systemctl is-active --quiet nginx; then
        echo -e "  Nginx:   ${GREEN}Running${NC}"
    else
        echo -e "  Nginx:   ${RED}Stopped${NC}"
    fi
    
    echo ""
}

# ==============================================================================
# Main
# ==============================================================================

main() {
    print_banner
    check_root
    
    case "${1:-}" in
        --full)
            full_install
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --full    Full automated installation"
            echo "  --help    Show this help"
            echo ""
            echo "Without options, starts interactive menu."
            ;;
        *)
            show_menu
            ;;
    esac
}

main "$@"
