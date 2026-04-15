# GitHub Secrets for ClawForge CI/CD

Add these secrets in your GitHub repository Settings → Secrets and variables → Actions:

## Required Secrets

### `VPS_SSH_KEY`
- **Type:** SSH private key
- **What:** SSH key to connect to your Hostinger VPS (without passphrase for automation)
- **Generate:** `ssh-keygen -t ed25519 -C "clawforge-deploy"`
- **Add public key** to `~/.ssh/authorized_keys` on VPS

### `VPS_HOST`
- **Type:** Plain text
- **What:** Your VPS IP or domain (e.g., `123.45.67.89` or `clawforge.example.com`)

### `VPS_USER`
- **Type:** Plain text
- **What:** SSH user (usually `root` or `ubuntu`)

### `STEPFUN_API_KEY`
- **Type:** Plain text
- **What:** StepFun API key for LLM sentiment analysis
- **From:** https://platform.stepfun.com/

### `BINGX_API_KEY` (optional for CI tests)
- **Type:** Plain text
- **What:** BingX API key for integration tests
- **Note:** Can be a testnet/dry-run key

### `BINGX_API_SECRET` (optional for CI tests)
- **Type:** Plain text
- **What:** BingX API secret

### `TELEGRAM_BOT_TOKEN` (optional for CI tests)
- **Type:** Plain text
- **What:** Telegram bot token from BotFather

### `TELEGRAM_CHAT_ID` (optional for CI tests)
- **Type:** Plain text
- **What:** Your Telegram user ID (7093901111)

### `CODECRABBIT_API_KEY` (for AI PR reviews)
- **Type:** Plain text
- **What:** CodeRabbit API key from https://coderabbit.ai
- **Get:** Sign up, integrate GitHub, get API key

### `DOCKERHUB_USERNAME` (optional)
- **Type:** Plain text
- **What:** Docker Hub username if pushing images

### `DOCKERHUB_TOKEN` (optional)
- **Type:** Plain text
- **What:** Docker Hub access token

## How to Add Secrets

```bash
# Option 1: Via GitHub CLI
gh secret set VPS_SSH_KEY < ~/.ssh/id_ed25519
gh secret set VPS_HOST -b"123.45.67.89"
gh secret set VPS_USER -b"root"

# Option 2: Via GitHub UI
# 1. Go to repo Settings → Secrets and variables → Actions
# 2. Click "New repository secret"
# 3. Paste value, save
```

## Security Notes
- These secrets are encrypted by GitHub
- Only visible to repo admins
- Never appear in logs (masked automatically)
- Rotate keys quarterly
