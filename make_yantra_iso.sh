#!/usr/bin/env bash
set -e

echo "Starting YantraOS Gold Master local ISO build..."

# Set required environment variables
export GOOGLE_GENERATIVE_AI_API_KEY="your-api-key-here"

echo "Replacing redacted keys in build.sh with valid local secrets..."
sed -i 's/<REDACTED_FOR_PUBLIC_REPO>/6f3595fabc679e6a17ad2694dd6a472ce1d3909fddbae4c5da1b7c1cd5c62f8a/g' build.sh
sed -i 's/<GOOGLE_API_KEY_REDACTED>/your-api-key-here/g' build.sh
sed -i 's/<REDACTED_FOR_PUBLIC_REPO>/695f0dd6a855615ee67e29797626fd983e7976d5b0334b044ba9259abe923a6b/g' build.sh

echo "Running build.sh..."
sudo bash build.sh

echo "Restoring compile_iso.sh after build.sh wiped the archlive directory..."
sudo chown -R admin:admin archlive
git checkout archlive/compile_iso.sh

echo "Re-redacting keys in build.sh..."
git checkout build.sh

echo "Preparation complete! To build the full ISO, run:"
echo "sudo -E GOOGLE_GENERATIVE_AI_API_KEY=\"your-api-key-here\" bash archlive/compile_iso.sh"
