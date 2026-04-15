# Contributing to ClawForge

Thanks for helping build the ClawForge empire. Please follow these guidelines.

---

## 🚀 Quick Start

```bash
# Fork & clone
git clone https://github.com/your-org/clawforge.git
cd clawforge

# Setup environment
python -m venv venv
source venv/bin/activate
pip install -e .[dev]

# Pre-commit hooks
pre-commit install

# Make your changes, then:
pytest tests/
black clawforge/
ruff check clawforge/
mypy clawforge/
```

---

## 📋 Development Workflow

1. **Create issue** — Describe bug or feature
2. **Create branch** — `git checkout -b feat/my-feature`
3. **Code** — Write tests first (TDD encouraged)
4. **Lint** — `black . && ruff check . && mypy clawforge/`
5. **Test** — `pytest -v`
6. **Commit** — Conventional commits (see below)
7. **Push & PR** — Fill template, request review
8. **Address feedback** — Iterate until approved
9. **Merge** — Auto-deploy to production

---

## 🏷️ Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <description>

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code restructuring
- `perf`: Performance improvement
- `test`: Add tests
- `docs`: Documentation
- `chore`: Maintenance tasks
- `ci`: CI/CD changes
- `build`: Build system changes

**Examples:**
```
feat(strategy): add RSI divergence detection
fix(telegram): prevent button callback race condition
docs: update deployment instructions
ci: add security scanning with bandit
```

---

## 🧪 Testing Requirements

### All PRs Must Include:
- [ ] **Unit tests** for new logic (pytest)
- [ ] **Backtest** results if strategy changes (attach CSV/plot)
- [ ] **Dry-run** validation (at least 24h simulated trading)
- [ ] **Type hints** complete (mypy clean)

### Test Coverage
- Minimum 80% line coverage
- New code must be covered
- Run: `pytest --cov=clawforge --cov-report=html`

---

## 🔍 Code Review Process

1. **CodeRabbit AI** — First pass (automated)
2. **Human reviewer** — At least 1 approval required
3. **Rentardio** — Final approval for core files

**Reviewers check:**
- Risk management intact?
- No secrets leaked?
- Config backwards compatible?
- Error handling present?
- Logging adequate?
- Performance impact?

---

## 🛡️ Security Policies

### Never commit:
- API keys, secrets, tokens
- Database dumps
- Private keys / wallet seeds
- Real user data

### Report vulnerabilities:
- Email: security@clawforge.ai (private)
- Or open private security advisory on GitHub

---

## 📊 Monitoring After Merge

After merge to main:
1. **CI/CD** auto-deploys to staging
2. Smoke test: `freqtrade status` (bot responds)
3. Check logs for errors
4. If green, auto-deploys to production within 5 minutes
5. Notify #dev channel

---

## 🎯 Project Structure

```
clawforge/
├── clawforge/          # Core package
│   ├── strategy.py     # Base trading strategy
│   ├── telegram.py     # 0-Type UI
│   ├── integrations/   # StepFun, meme gen, etc.
│   └── subscription.py # Web3 gating
├── configs/            # Docker & app config
├── tests/              # Unit/integration tests
├── scripts/            # Setup & deployment
├── .github/            # CI/CD & templates
├── README.md           # Public docs
└── pyproject.toml      # Dependencies & tooling
```

---

## ❓ Questions?

Open an issue or ask in #dev channel. Keep PRs focused — one feature/fix per PR.

**Let's build an empire.**
