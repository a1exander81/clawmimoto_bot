# GitHub Automation Setup — Complete Guide

This document explains how the ClawForge GitHub repository is automated for CI/CD, code review, and deployment.

---

## 📦 What's Automated

### 1. **Continuous Integration (CI)**
Every push/PR triggers:
- ✅ **Unit tests** (pytest)
- ✅ **Code coverage** (codecov)
- ✅ **Linting** (black + ruff)
- ✅ **Type checking** (mypy)
- ✅ **Security scanning** (safety + bandit)
- ✅ **Docker build** (multi-stage)
- ✅ **AI Code Review** (CodeRabbit)

### 2. **Code Review Workflow**
```
Push → CodeRabbit AI Scan → Human Review → Merge → Deploy
```
- CodeRabbit provides first-pass review comments
- PR cannot merge without at least 1 human approval
- Rentardio auto-assigned as reviewer for core files (CODEOWNERS)

### 3. **Auto-Deployment**
Merge to `main` → GitHub Actions builds Docker image → Deploys to VPS via SSH → Health check → Notify

---

## 🚀 Quick Start (One-Time Setup)

### Step 1: Clone & Initialize
```bash
cd /data/.openclaw/workspace/clawforge-repo
./scripts/init_github.sh
```
This script will:
- Initialize git
- Configure user/email
- Install pre-commit hooks
- Create GitHub repo (via `gh` CLI)
- Set branch protection

### Step 2: Add GitHub Secrets
Go to your repo: `Settings → Secrets and variables → Actions → New repository secret`

Add these secrets (see `.github/SECRETS_TEMPLATE.md` for details):

| Secret | Value | Required? |
|--------|-------|-----------|
| `VPS_SSH_KEY` | Private SSH key to your VPS | ✅ Yes |
| `VPS_HOST` | VPS IP/domain | ✅ Yes |
| `VPS_USER` | SSH user (root/ubuntu) | ✅ Yes |
| `STEPFUN_API_KEY` | StepFun API key | ⚠️ For LLM features |
| `BINGX_API_KEY` | BingX API key | ⚠️ For integration tests |
| `BINGX_API_SECRET` | BingX secret | ⚠️ For integration tests |
| `CODECRABBIT_API_KEY` | CodeRabbit AI key | ✅ For PR reviews |
| `DOCKERHUB_USERNAME` | Docker Hub user | ⚠️ If pushing images |
| `DOCKERHUB_TOKEN` | Docker Hub token | ⚠️ If pushing images |

### Step 3: Enable CodeRabbit
1. Install CodeRabbit app from GitHub Marketplace
2. Connect to your repository
3. Add API key to secrets

---

## 🔄 Daily Development Workflow

### 1. Start a Feature
```bash
git checkout -b feat/5m-rsi-improvement
```

### 2. Make Changes
Edit files, add tests.

### 3. Run Pre-Commit (Optional)
```bash
make ci-local  # Runs all checks locally before push
```

### 4. Commit & Push
```bash
git add .
git commit -m "feat(strategy): add RSI divergence detection

- Add bullish/bearish divergence logic
- Improve entry accuracy by 15% in backtests
- Update tests"

git push -u origin feat/5m-rsi-improvement
```

### 5. Open Pull Request
- GitHub URL will appear after push
- Fill PR template
- CodeRabbit will auto-comment with review
- Wait for human reviewer (Rentardio)

### 6. Address Feedback
- Make requested changes
- Push to same branch (PR updates automatically)

### 7. Merge & Deploy
- Once approved, click "Merge"
- CI runs final checks
- Auto-deploys to production VPS
- Bot restarts within 2 minutes

---

## 📊 CI/CD Pipeline Details

### Jobs in `.github/workflows/ci.yml`

| Job | Purpose | When Runs |
|-----|---------|-----------|
| `test` | pytest + coverage | Every PR & push |
| `security` | safety + bandit | Every PR |
| `docker` | Build & test image | Every PR |
| `coderabbit` | AI code review | Every PR |

### Jobs in `.github/workflows/deploy.yml`

| Job | Purpose | Trigger |
|-----|---------|---------|
| `deploy` | Build + SSH deploy | Push to `main` only |

---

## 🔐 Security Model

### Secrets Management
- All secrets stored in GitHub Encrypted Storage
- Never appear in logs (GitHub masks them)
- Rotate quarterly

### VPS Access
- Deploy uses SSH key only (no passwords)
- Key has limited commands (docker-compose only)
- Separate key per environment (staging/prod)

### Dependency Scanning
- `safety` checks for known vulnerabilities in Python packages
- `bandit` scans for security anti-patterns
- Fails CI on critical issues

---

## 🛠️ Customization

### Change CI Triggers
Edit `on:` in workflow files. For example, to run CI only on PRs:
```yaml
on:
  pull_request:
    branches: [main]
```

### Add Custom Checks
Create new job in `ci.yml`:
```yaml
integration-test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Run integration tests
      run: pytest tests/integration/ -v
```

### Change Deployment Target
Edit `deploy.yml` SSH action:
```yaml
- name: Deploy to VPS
  uses: appleboy/ssh-action@v1.0.0
  with:
    host: ${{ secrets.VPS_HOST }}
    username: ${{ secrets.VPS_USER }}
    key: ${{ secrets.VPS_SSH_KEY }}
    script: |
      cd /opt/clawforge
      ./deploy.sh  # Custom script
```

---

## 🐛 Troubleshooting

### CI Job Fails
```bash
# Check logs on GitHub Actions tab
# Download artifacts from "Artifacts" section
# Re-run locally: make ci-local
```

### Deployment Fails
```bash
# SSH to VPS and check:
docker logs clawforge
# Or via GitHub Actions logs (shows SSH output)
```

### CodeRabbit Not Commenting
- Verify app installed in repo "Installed apps"
- Check API key is set in secrets
- Ensure PR size < 500 files (CodeRabbit limit)

### Branch Protection Blocking Merge
- Ensure all required status checks pass
- Wait for CodeRabbit review (may take 2-5 min)
- Request review from Rentardio if auto-assignment fails

---

## 📈 Monitoring

### GitHub Insights
- `Insights → Community` — PR merge time, review time
- `Insights → Actions` — CI success rate, duration
- `Insights → Traffic` — clones, views

### VPS Health
```bash
# After deployment, check:
ssh root@VPS_HOST 'docker ps | grep clawforge'
ssh root@VPS_HOST 'docker logs clawforge --tail 50'
```

### Bot Health
- Telegram: `/cmd` should open menu
- `/status` shows PnL
- No errors in `user_data/logs/`

---

## 🔄 Updating the Workflow

When you need to modify CI/CD:

1. **Edit workflow files** in `.github/workflows/`
2. **Test locally** (use `act` for GitHub Actions simulation)
3. **Open PR** → Review → Merge
4. **New workflow version** auto-enables on merge

### Using `act` (Local GitHub Actions)
```bash
# Install act: https://github.com/nektos/act
act pull_request
act push -j test
```

---

## 🎯 Best Practices

1. **Small PRs** — < 400 lines changed, single purpose
2. **Descriptive titles** — Use conventional commits
3. **Link issues** — "Fixes #123" auto-closes issue on merge
4. **Update docs** — If user-facing change, update README
5. **Don't skip CI** — Wait for all checks before merging
6. **Review promptly** — Aim for < 24h review time

---

## 📞 Support

- **CI/CD Issues:** Check `.github/workflows/` logs first
- **Deployment Issues:** Check VPS docker logs
- **Code Review:** Ping Rentardio in Telegram
- **GitHub Actions:** https://docs.github.com/en/actions

---

**This automation setup ensures:**
- ✅ Every change is tested
- ✅ Code quality enforced
- ✅ Security scanned
- ✅ Deployed automatically
- ✅ Review process followed

**No manual steps after initial setup.** Just code → PR → merge → live.
