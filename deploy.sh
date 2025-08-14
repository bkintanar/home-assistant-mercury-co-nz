#!/bin/bash

# Quick deployment script for Mercury Energy NZ Custom Component
# Supports both Docker and direct file system deployment

# ================================
# CONFIGURATION
# ================================
DOCKER_CONTAINER="homeassistant"  # Change if your container has a different name
HA_CONFIG_PATH="/config"          # For direct deployment, change this path

# ================================
# DEPLOYMENT SCRIPT
# ================================

echo "🚀 Deploying Mercury Energy NZ Custom Component..."

# Detect deployment method
if command -v docker &> /dev/null && docker ps | grep -q $DOCKER_CONTAINER; then
    echo "🐳 Docker container detected: $DOCKER_CONTAINER"

    # Docker deployment
    echo "📁 Copying component files to Docker container..."
    docker cp custom_components/mercury_co_nz $DOCKER_CONTAINER:/config/custom_components/

    if [ $? -eq 0 ]; then
        echo "✅ Files copied successfully to Docker container!"
        DEPLOYMENT_METHOD="Docker"
    else
        echo "❌ Error copying files to Docker container."
        echo "💡 Check if container name '$DOCKER_CONTAINER' is correct"
        exit 1
    fi

else
    echo "📂 Using direct file system deployment..."

    # Create custom_components directory if it doesn't exist
    mkdir -p "$HA_CONFIG_PATH/custom_components"

    # Direct file system deployment
    echo "📁 Copying component files..."
    cp -r custom_components/mercury_co_nz "$HA_CONFIG_PATH/custom_components/"

    if [ $? -eq 0 ]; then
        echo "✅ Files copied successfully!"
        DEPLOYMENT_METHOD="Direct"
    else
        echo "❌ Error copying files. Check the HA_CONFIG_PATH in this script."
        exit 1
    fi
fi

echo ""
echo "🔄 Next steps:"
echo "1. Restart Home Assistant"
echo "2. Go to Settings → Devices & Services → Add Integration"
echo "3. Search for 'Mercury Energy NZ'"
echo "4. Add the chart card with this YAML:"
echo ""
echo "type: custom:mercury-energy-chart-card"
echo "entity: sensor.mercury_nz_energy_usage"
echo "name: ⚡️ELECTRICITY USAGE"
echo "show_navigation: true"
echo ""
echo "🎉 Deployment complete using $DEPLOYMENT_METHOD method!"
