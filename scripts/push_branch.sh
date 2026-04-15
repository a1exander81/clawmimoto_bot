#!/bin/bash
set -e

REPO_DIR="/data/.openclaw/workspace/clawforge-repo"
cd "$REPO_DIR"

# Initialize git if not already
if [ ! -d .git ]; then
  git init
  git config user.name "Zion"
  git config user.email "zion@clawforge.ai"
fi

# Ensure we have a main branch (create initial commit if no commits)
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  git add -A
  git commit -m "Initial commit - ClawForge trading engine"
  git branch -M main
fi

# Ensure we are on main and up to date (if remote exists)
if git remote get-url origin >/dev/null 2>&1; then
  git checkout main
  git pull origin main || true
else
  git checkout main 2>/dev/null || git checkout master
fi

# Create a new branch with timestamp
BRANCH="auto/$(date +%Y-%m-%d_%H-%M-%S)"
git checkout -b "$BRANCH"

# Add all changes and commit (if any)
git add -A
if git diff-index --quiet HEAD --; then
  echo "No changes to commit."
else
  git commit -m "Automated push from OpenClaw Control UI $(date -Iseconds)"
fi

# Push branch (if remote exists)
if git remote get-url origin >/dev/null 2>&1; then
  git push -u origin "$BRANCH"
  echo "✅ Branch $BRANCH pushed successfully."
else
  echo "⚠️  No remote origin configured. Skipping push. Set GITHUB_REPO_URL or add remote manually."
fi
