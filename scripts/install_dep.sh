#!/bin/bash
set -e

echo "[Bootstrap] 🔧 Setting up EC2: Docker, Compose, Nginx, CodeDeploy Agent..."

# Docker
if ! command -v docker &>/dev/null; then
  echo "-> Installing Docker..."
  sudo apt-get update
  sudo apt-get install -y docker.io
  sudo systemctl enable docker
  sudo usermod -aG docker ubuntu
else
  echo "-> Docker already installed"
fi

# Docker Compose
if ! command -v docker-compose &>/dev/null; then
  echo "-> Installing Docker Compose..."
  sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
    -o /usr/local/bin/docker-compose
  sudo chmod +x /usr/local/bin/docker-compose
else
  echo "-> Docker Compose already installed"
fi

# Nginx
if ! command -v nginx &>/dev/null; then
  echo "-> Installing Nginx..."
  sudo apt-get install -y nginx
else
  echo "-> Nginx already installed"
fi

# CodeDeploy Agent
if [ ! -f /etc/init.d/codedeploy-agent ]; then
  echo "-> Installing CodeDeploy Agent..."
  sudo apt-get install -y ruby wget
  REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)
  cd /tmp
  wget "https://aws-codedeploy-${REGION}.s3.${REGION}.amazonaws.com/latest/install"
  chmod +x ./install
  sudo ./install auto
  sudo service codedeploy-agent start
else
  echo "-> CodeDeploy agent already installed"
fi

echo "[Bootstrap] ✅ EC2 Bootstrap Setup Completed"
