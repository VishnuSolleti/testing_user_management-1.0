##!/bin/bash
## Pulls images and starts containers using docker-compose
#set -euo pipefail
#
#APP_DIR="/home/ubuntu/tarafirst_backend"
#ENV_FILE="$APP_DIR/image_tag.txt"
#
#echo "========== STARTING CONTAINERS =========="
#cd "$APP_DIR" || { echo "App directory not found: $APP_DIR"; exit 1; }
#
#if [ ! -f "$ENV_FILE" ]; then
#    echo "Env file not found: $ENV_FILE"
#    exit 1
#fi
#
## Pull latest versioned images
#echo "Pulling Docker images..."
#docker-compose --env-file "$ENV_FILE" pull
#
## Start containers in detached mode
#echo "Starting containers..."
#docker-compose --env-file "$ENV_FILE" up -d
#
## Show running containers
##echo "Currently running containers:"
##docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
#
#echo "Containers started successfully."
#!/bin/bash
# Pulls images and starts containers using docker-compose without a .env file
#!/bin/bash
# Pulls images and starts containers using docker-compose
#set -euo pipefail
#
#APP_DIR="/home/ubuntu/tarafirst_backend"
#ENV_FILE="$APP_DIR/image_tag.txt"
#
#echo "========== STARTING CONTAINERS =========="
#cd "$APP_DIR" || { echo "App directory not found: $APP_DIR"; exit 1; }
#
#if [ ! -f "$ENV_FILE" ]; then
#    echo "Env file not found: $ENV_FILE"
#    exit 1
#fi
#
## Show which images will be used
#echo "Using images from $ENV_FILE:"
#cat "$ENV_FILE"
#
## Pull the latest versioned images from Docker Hub
#echo "Pulling Docker images..."
#docker-compose --env-file "$ENV_FILE" pull
#
## Start containers in detached mode
#echo "Starting containers..."
#docker-compose --env-file "$ENV_FILE" up -d
#
## Show running containers
#echo "Currently running containers:"
#docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
#
#echo "Containers started successfully."
#!/bin/bash
set -e

echo "[ApplicationStart] 🚀 Starting Docker containers..."
cd /home/ubuntu/tarafirst_user_management

# 1. Load image variables
if [ -f "image_vars.env" ]; then
    set -a
    source image_vars.env
    set +a
else
    echo "❌ image_vars.env not found!"
    exit 1
fi

# 2. Validate required variables
if [[ -z "$DOCKER_IMAGE" || -z "$IMAGE_TAG" ]]; then
    echo "❌ DOCKER_IMAGE or IMAGE_TAG is missing"
    exit 1
fi


echo "✅ Using app image: ${DOCKER_IMAGE}:${IMAGE_TAG}"

# 3. Always pull latest images before starting
echo "[ApplicationStart] 🔄 Pulling latest images..."
docker-compose --env-file image_vars.env pull

# 4. Start containers with new images
echo "[ApplicationStart] 🚀 Launching containers..."
docker-compose --env-file image_vars.env up -d --force-recreate

# Remove all images of the repo except the one currently running
CURRENT_IMAGE="${DOCKER_IMAGE}:${IMAGE_TAG}"

for IMG in $(docker images "$DOCKER_IMAGE" --format "{{.Repository}}:{{.Tag}}"); do
  if [ "$IMG" != "$CURRENT_IMAGE" ]; then
    echo "[Cleanup] Removing old image: $IMG"
    docker rmi -f "$IMG" || true
  fi
done


echo "[ApplicationStart] ✅ Done. Containers are up and running."
