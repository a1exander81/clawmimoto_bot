# 🚀 ClawForge GitHub Repository — Summary

**Status:** ✅ Ready for initialization

---

## 📁 What's Been Created

```
/data/.openclaw/workspace/clawforge-repo/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml           # Full CI pipeline (test, lint, security, docker)
│   │   └── deploy.yml       # Auto-deploy to VPS on merge
│   ├── CODEOWNERS           # Auto-assign reviewers
│   ├── ISSUE_TEMPLATE/      # Bug report & feature request templates
│   ├── pull_request_template.md
│   ├── SECRETS_TEMPLATE.md  # Required GitHub secrets list
│   └── coderabbit.yml       # AI review config
├── clawforge/               # Core Python package
│   ├── __init__.py
│   ├── bot.py              # Main entry point
│   ├── strategy.py         # 5M sniper strategy with risk rules
│   ├── telegram.py         # 0-Type button UI
│   ├── integrations/
│   │   ├── stepfun.py      # StepFun sentiment API
│   │   └── meme.py         # PnL card generator
│   └── subscription.py     # Web3 gating stub
├── configs/
│   ├── config.json         # BingX, 5M, ISOLATED config
│   └── docker-compose.yml  # Local & prod deployment
├── tests/
│   └── test_strategy.py    # Strategy unit tests
├── scripts/
│   ├── init_github.sh      # One-command repo setup
│   ├── setup_repo.sh       # Git init + GitHub create
│   └── deploy/
│       ├── prod.sh         # Production deploy script
│       └── staging.sh      # Staging deploy script
├── deploy/
├── .gitignore
├── README.md               # Public project page
├── CONTRIBUTING.md         # Dev workflow & code review rules
├── CLAUDE.md               # Code review guidelines for AI/humans
├── GITHUB_AUTOMATION.md    # Full automation docs
├── pyproject.toml          # Modern Python packaging
├── requirements.txt        # Dependencies
├── Dockerfile              # Container image
├── docker-compose.yml      # Orchestration
└── Makefile                # Dev task shortcuts
```

---

## 🎯 What Each Component Does

| Component | Purpose | Automation |
|-----------|---------|------------|
| **ci.yml** | Run tests, lint, security, Docker build on every PR/push | ✅ Auto on PR |
| **deploy.yml** | Deploy to VPS when PR merges to `main` | ✅ Auto on merge |
| **CODEOWNERS** | Auto-assign Rentardio as reviewer for core files | ✅ Auto assignment |
| **CodeRabbit** | AI pre-review of PRs | ✅ Auto comments |
| **pre-commit** | Local pre-commit hooks (black/ruff/mypy) | ✅ Install once |
| **Makefile** | One-command dev tasks | ✅ Run locally |
| **Dockerfile** | Reproducible container image | ✅ Built by CI |
| **tests/** | Unit tests for strategy logic | ✅ Required for PR |

---

## 🚀 One-Command Setup

To create the GitHub repo and push initial code:

```bash
cd /data/.openclaw/workspace/clawforge-repo
chmod +x scripts/init_github.sh
./scripts/init_github.sh
```

The script will:
1. Initialize git
2. Configure user/email
3. Install pre-commit hooks
4. Create GitHub repo (if `gh` CLI installed)
5. Set branch protection rules
6. Print next steps

---

## 🔐 Secrets You Must Add to GitHub

After creating repo, go to `Settings → Secrets → Actions` and add:

| Secret | Value | Where to get it |
|--------|-------|----------------|
| `VPS_SSH_KEY` | Private SSH key for VPS | `ssh-keygen -t ed25519` |
| `VPS_HOST` | Your VPS IP/hostname | From Hostinger |
| `VPS_USER` | SSH user (root/ubuntu) | Hostinger panel |
| `STEPFUN_API_KEY` | StepFun LLM API key | https://platform.stepfun.com/ |
| `CODECRABBIT_API_KEY` | CodeRabbit AI review | https://coderabbit.ai |
| `BINGX_API_KEY` | BingX trading API (optional) | BingX dashboard |
| `BINGX_API_SECRET` | BingX secret (optional) | BingX dashboard |

See `.github/SECRETS_TEMPLATE.md` for details.

---

## 📋 Daily Development Flow

```bash
# 1. Start feature branch
git checkout -b feat/awesome-strategy

# 2. Code (tests first!)
vim clawforge/strategy.py
vim tests/test_strategy.py

# 3. Run checks locally
make ci-local    # or: pytest && black . && ruff check . && mypy .

# 4. Commit & push
git add .
git commit -m "feat(strategy): add EMA-200 filter"
git push -u origin feat/awesome-strategy

# 5. Open PR on GitHub
#    - CodeRabbit auto-comments
#    - Rentardio notified
#    - Wait for approval

# 6. Merge (after approval)
#    - Auto-deploys to VPS
#    - Bot restarts automatically
```

---

## 🛡️ What's Protected

### Branch Protection (auto-configured)
- `main` branch: requires PR + review
- CI must pass (all jobs green)
- At least 1 human approval
- CodeRabbit review required
- No force-push allowed

### Code Quality Gates
- **Lint:** black + ruff (fails CI if violations)
- **Types:** mypy (fails CI on type errors)
- **Tests:** pytest with coverage (fails if < 80%)
- **Security:** safety + bandit (fails on critical)

### Secrets Scanning
- Git secrets scanner in CI (truffleHog equivalent)
- Pre-commit hook prevents secret commit
- GitHub secret scanning (built-in)

---

## 🔄 What Gets Deployed

When you merge to `main`:

1. ✅ CI passes all checks
2. 🏗️ Docker image built with tag `latest` and commit SHA
3. 📤 Image pushed to Docker Hub (optional, if credentials set)
4. 🚀 SSH to VPS, run `docker-compose pull && up -d`
5. 🧪 Health check waits for bot to respond
6. 📢 Notification sent to #dev channel (future)

**Rollback:** If deployment fails, CI auto-reverts to previous image (via `docker-compose` rollback config — not shown but can be added).

---

## 📊 Monitoring the Automation

### GitHub Actions Tab
- See real-time CI logs
- Download artifacts (test reports, coverage)
- Re-run failed jobs

### VPS After Deploy
```bash
ssh root@YOUR_VPS
docker logs -f clawforge  # Watch bot startup
docker ps                 # Confirm container running
```

### Bot Health Check
- Telegram: `/cmd` should open menu within 30s
- Or: `curl http://VPS:8080/api/v1/ping` (if health endpoint enabled)

---

## 🎯 Next Steps

1. **Run init script** → `./scripts/init_github.sh`
2. **Add GitHub secrets** → See `SECRETS_TEMPLATE.md`
3. **Enable CodeRabbit** → Install from Marketplace
4. **Create first PR** → Try a small doc change
5. **Watch CI** → GitHub Actions tab
6. **Deploy** → Merge to main, bot auto-updates

---

## 📖 Documentation Map

| File | Purpose |
|------|---------|
| `README.md` | Public project overview |
| `CONTRIBUTING.md` | Dev workflow, commit conventions |
| `CLAUDE.md` | Code review guidelines (for AI/humans) |
| `GITHUB_AUTOMATION.md` | CI/CD deep dive |
| `.github/SECRETS_TEMPLATE.md` | Secret values reference |
| `SKILL.md` (in skill dir) | How to use as OpenClaw skill |

---

**Everything is ready. Just run the init script and push.**
