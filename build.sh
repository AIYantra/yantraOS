#!/usr/bin/env bash
set -e

echo "Starting YantraOS Gold Master v1.2 Build Preparation..."

# 1. Copies the releng profile to the archlive working directory first.
if [ -d "archlive" ]; then
    echo "Cleaning up existing archlive directory..."
    rm -rf archlive/
fi
cp -a /usr/share/archiso/configs/releng/ archlive/

# 2. Injects the docker package into packages.x86_64.
echo "Injecting docker package..."
echo "docker" >> archlive/packages.x86_64

# 3. Creates the exact directory structure.
echo "Creating directory structures..."
mkdir -p archlive/airootfs/opt/yantra/core
mkdir -p archlive/airootfs/etc/yantra
mkdir -p archlive/airootfs/etc/systemd/system/multi-user.target.wants

# 4. Correctly copies the Python codebase.
echo "Copying Python codebase..."
cp -r core/* archlive/airootfs/opt/yantra/core/

# 5. Securely copies the secrets.env file and sets permissions.
echo "Creating and copying secrets.env..."
cat << 'EOF' > secrets.env
YANTRA_TELEMETRY_TOKEN=<REDACTED_FOR_PUBLIC_REPO>
YANTRA_KRIYA_TOKEN=<REDACTED_FOR_PUBLIC_REPO>
GOOGLE_GENERATIVE_AI_API_KEY=<REDACTED_FOR_PUBLIC_REPO>
EOF

cp secrets.env archlive/airootfs/etc/yantra/
chmod 0600 archlive/airootfs/etc/yantra/secrets.env

# Inject file permissions into profiledef.sh
sed -i 's/file_permissions=(/file_permissions=(\n  ["\/etc\/yantra\/secrets.env"]="0:0:0600"/' archlive/profiledef.sh

# 6. Copies yantra.service and creates symlink.
echo "Copying yantra.service..."
cp deploy/systemd/yantra.service archlive/airootfs/etc/systemd/system/
ln -sf /etc/systemd/system/yantra.service archlive/airootfs/etc/systemd/system/multi-user.target.wants/yantra.service

echo "Build preparation script complete."
