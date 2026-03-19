# VPS / Cloud VM Deployment

**Recommended:** Hetzner CPX31 (4 vCPU, 8GB RAM, ~€13/mo) or DigitalOcean
equivalent for single-tenant use.

## System Setup

```bash
# On fresh Ubuntu 24.04 VM
sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip
sudo apt install -y nginx certbot python3-certbot-nginx  # for HTTPS
```

## Install NeuralClaw

```bash
python3.12 -m venv /opt/neuralclaw
source /opt/neuralclaw/bin/activate
pip install "neuralclaw[vector,google,microsoft]"
```

## Create Service User

```bash
sudo useradd -m -s /bin/bash neuralclaw
sudo -u neuralclaw neuralclaw init
```

## Nginx Reverse Proxy

```bash
cat > /etc/nginx/sites-available/neuralclaw << 'EOF'
server {
    server_name your-domain.com;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";  # WebSocket support
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/neuralclaw /etc/nginx/sites-enabled/
sudo certbot --nginx -d your-domain.com
```

## Systemd Service

```bash
sudo -u neuralclaw neuralclaw service install
sudo loginctl enable-linger neuralclaw  # keep alive after SSH disconnect
```

## Firewall

```bash
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw --force enable
```

## Verify

```bash
neuralclaw doctor
curl http://localhost:8080/health
curl http://localhost:8080/ready
```

## Docker Alternative

```bash
docker compose up -d
```

See `docker-compose.yml` in the repo root for the full configuration.
