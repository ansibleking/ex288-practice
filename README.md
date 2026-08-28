# Fedora bootc Image — GitHub Actions

Automated pipeline to build and publish a Fedora bootc image with user `mayil`.

## What it does

| Job | Trigger | Result |
|-----|---------|--------|
| **Build & Push** | Push to `main` or PR | Builds container image → pushes to `ghcr.io` |
| **Build QCOW2** | Push to `main` only | Converts container → downloadable `disk.qcow2` |

## Quick Start

### 1. Create your GitHub repository

```bash
git init
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
```

### 2. Copy these files into your repo

```
your-repo/
├── Containerfile
└── .github/
    └── workflows/
        └── bootc-build.yml
```

### 3. Enable GitHub Packages (ghcr.io)

Go to your repo → **Settings → Actions → General → Workflow permissions**
→ select **Read and write permissions** → Save.

### 4. Push to main

```bash
git add .
git commit -m "Add bootc Containerfile and GitHub Actions workflow"
git push origin main
```

The workflow starts automatically. Watch it at:
`https://github.com/YOUR_USERNAME/YOUR_REPO/actions`

## Image tags produced

| Tag | When |
|-----|------|
| `latest` | Every push to `main` |
| `main` | Every push to `main` |
| `sha-abc1234` | Every commit (unique) |
| `pr-42` | Pull requests |

## Pull and boot the image locally

```bash
# Pull the built image
podman pull ghcr.io/YOUR_USERNAME/fedora-bootc-mayil:latest

# OR build the QCOW2 yourself
sudo podman run --rm --privileged \
  --security-opt label=type:unconfined_t \
  -v ./output:/output \
  quay.io/centos-bootc/bootc-image-builder:latest \
  --type qcow2 --rootfs xfs \
  ghcr.io/YOUR_USERNAME/fedora-bootc-mayil:latest

# Boot with virt-install
sudo virt-install \
  --name fedora-bootc-mayil \
  --memory 2048 --vcpus 2 \
  --import \
  --disk ./output/qcow2/disk.qcow2,format=qcow2 \
  --os-variant fedora-eln \
  --network network=default \
  --graphics none \
  --console pty,target_type=serial
```

Login: `mayil` / `redhat`

## Customise the image

Edit `Containerfile` to add packages, configs, or services:

```dockerfile
FROM quay.io/fedora/fedora-bootc:42

# Add your packages
RUN dnf install -y vim htop git && dnf clean all

# Add your user
RUN useradd -m -G wheel -d /var/home/mayil mayil && \
    echo "mayil:redhat" | chpasswd
```

Push → workflow rebuilds automatically.
