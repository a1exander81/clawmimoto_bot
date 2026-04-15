#!/bin/bash
# Initialize ClawForge GitHub repository
# Usage: ./scripts/setup_repo.sh

set -e

echo "🔧 Setting up ClawForge GitHub repository..."

# 1. Initialize git
git init
git branch -M main

# 2. Configure git user (read from env or prompt)
GIT_USER="${GIT_USER_NAME:-Zion}"
GIT_EMAIL="${GIT_USER_EMAIL:-zion@clawforge.ai}"
git config user.name "$GIT_USER"
git config user.email "$GIT_EMAIL"

# 3. Add all files
git add .

# 4. Create initial commit
git commit -m "chore: initial commit - ClawForge trading engine

- Add Freqtrade-based 5M sniper strategy
- Implement Telegram 0-Type UI
- Configure Docker deployment
- Add CI/CD workflows (test, lint, security)
- Add CodeRabbit AI review integration
- Add risk management: ISOLATED margin, 3 trades/day, trailing SL @ +50%"

# 5. Create GitHub repo (requires gh CLI)
if command -v gh &> /dev/null; then
    echo "📦 Creating GitHub repository..."
    gh repo create clawforge --public --source=. --remote=origin --push
    echo "✅ Repository created and pushed!"
else
    echo "⚠️  gh CLI not installed. Manual steps:"
    echo "   1. Create repo at https://github.com/new"
    echo "   2. git remote add origin <repo-url>"
    echo "   3. git push -u origin main"
fi

# 6. Set up branch protection (requires gh)
if command -v gh &> /dev/null; then
    echo "🛡️  Enabling branch protection rules..."
    gh api -X PUT repos/:owner/:repo/branches/main/protection \
      -f required_status_checks_strict=true \
      -f required_status_checks_contexts='["CI / Test", "CI / Lint", "CI / Security", "Docker Build", "CodeRabbit AI Review"]' \
      -f enforce_admins=true \
      -f required_pull_request_reviews_required=true \
      -f required_pull_request_reviews_dismiss_stale_reviews=true
fi

echo "✅ Repository setup complete!"
