# =============================================================================
# Team Onboarding Guide — TTA Project Secrets
# =============================================================================
# This guide explains how collaborators get access to project secrets.
# Created for: TTA (Therapeutic Text Adventure) Project
# =============================================================================

## Overview

The TTA project uses **1Password** for secret management. All API keys
and credentials are stored in a shared "TTA" vault.

## Who Has Access

**Current access:**
- Primary developer: Full vault access (you)

**When collaborators join:**
- You'll share vault access via 1Password Teams
- Or manually share keys (copy-paste) for simpler setup

## Getting Access as a Collaborator

### Option A: Full Vault Access (Recommended)

1. Create a 1Password account at https://1password.com
2. Request access from the project lead (you)
3. Once added to TTA vault, you'll see all project secrets

### Option B: Manual Sharing (Simpler)

1. Request specific keys you need
2. Lead shares via secure channel (not email/chat)
3. Store locally in `.env` file

## Setting Up Your Environment

### Step 1: Install 1Password CLI

```bash
# macOS
brew install 1password-cli

# Linux (Debian/Ubuntu) — download and review before running
curl -fsSLO https://downloads.1password.com/linux/install.sh
less install.sh
bash install.sh

# Arch/Manjaro/CachyOS
# Review the PKGBUILD before installing from AUR
paru -S 1password-cli
```

### Step 2: Sign In

```bash
op signin my.1password.com
# Follow browser prompts
```

### Step 3: Get Project Secrets

```bash
# List available secrets
op item list --vault TTA

# Read a specific key
op read op://TTA/Groq/credential
```

### Step 4: Configure Your Local Environment

```bash
# Navigate to project directory
cd ~/Repos/fictional-barnacle  # or TTA, TTA.dev

# Create a local .env from the committed template
cp .env.example .env

# Optionally replace selected values with op:// references, then resolve once
op inject -i .env -o .env.resolved
mv .env.resolved .env

# Run the project normally
python -m tta
```

## Project-Specific Setup

### fictional-barnacle (TTA Rebuild)

```bash
cd ~/Repos/fictional-barnacle
cp .env.example .env
# Optionally swap selected values to op:// references first
op inject -i .env -o .env.resolved
mv .env.resolved .env

# Start (requires Docker for databases)
docker compose up -d
python -m tta
```

### TTA (Main Project)

```bash
cd ~/Repos/TTA
cp .env.example .env
op inject -i .env -o .env.resolved
mv .env.resolved .env

# Start
python src/main.py start
```

### TTA.dev (Library)

```bash
cd ~/Repos/TTA.dev
cp .env.example .env
op inject -i .env -o .env.resolved
mv .env.resolved .env

# Run
uv run python -m ttadev.observability
```

## Available Secrets

| Secret | Project(s) | Purpose |
|--------|------------|--------|
| Anthropic | Claude Code | Claude API |
| Groq | All projects | Free LLM inference |
| OpenRouter | All projects | LLM routing |
| Google | TTA.dev | Gemini API |
| E2B | TTA.dev | Code sandbox |
| HuggingFace | All | Model access |
| Cerebras | All | Fast inference |
| Langfuse | All | Observability |
| Artificial Analysis | All | Model benchmarking |

## Security Guidelines

1. **Never commit `.env`** — It's in `.gitignore`
2. **Don't share keys in chat** — Use 1Password sharing
3. **Report leaks immediately** — Rotate keys if exposed
4. **Use least privilege** — Only request keys you need

## Troubleshooting

### "Not signed in"

```bash
op signin my.1password.com
```

### "Item not found"

```bash
op item list --vault TTA
# Verify the item exists
```

### "Authorization prompt dismissed"

- Unlock 1Password Desktop
- Try the command again

## Questions?

Contact: Project lead (you)

## Quick Reference Card

```bash
# Read a secret
op read op://TTA/KEY_NAME/credential

# Materialize .env from any op:// references
op inject -i .env -o .env.resolved && mv .env.resolved .env

# List all secrets
op item list --vault TTA
```

---
*Last updated: April 2026*