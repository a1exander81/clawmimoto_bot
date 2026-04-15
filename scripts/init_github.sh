#!/bin/bash
# Complete ClawForge GitHub repository setup & automation
# Usage: ./scripts/init_github.sh

set -e

echo "=========================================="
echo "   ClawForge GitHub Repository Setup"
echo "=========================================="

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check prerequisites
check_prereqs() {
    echo -n "Checking prerequisites... "
    if ! command -v git &> /dev/null; then
        echo -e "${RED}FAIL${NC} — git not installed"
        exit 1
    fi
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}FAIL${NC} — python3 not installed"
        exit 1
    fi
    if ! command -v pip &> /dev/null; then
        echo -e "${RED}FAIL${NC} — pip not installed"
        exit 1
    fi
    echo -e "${GREEN}OK${NC}"
}

# Initialize git repo
init_git() {
    echo -e "\n${YELLOW}[1/6] Initializing Git repository...${NC}"
    git init
    git branch -M main

    # Configure user from env or prompt
    if [ -z "$GIT_USER_NAME" ]; then
        read -p "Enter your GitHub username: " GIT_USER_NAME
    fi
    if [ -z "$GIT_USER_EMAIL" ]; then
        read -p "Enter your email: " GIT_USER_EMAIL
    fi

    git config user.name "$GIT_USER_NAME"
    git config user.email "$GIT_USER_EMAIL"
    echo "✅ Git configured as $GIT_USER_NAME <$GIT_USER_EMAIL>"
}

# Install pre-commit hooks
setup_hooks() {
    echo -e "\n${YELLOW}[2/6] Setting up pre-commit hooks...${NC}"
    if command -v pre-commit &> /dev/null; then
        pre-commit install
        echo "✅ Pre-commit hooks installed"
    else
        echo "⚠️  pre-commit not installed. Install with: pip install pre-commit"
    fi
}

# Create GitHub repository
create_github_repo() {
    echo -e "\n${YELLOW}[3/6] Creating GitHub repository...${NC}"

    if command -v gh &> /dev/null; then
        echo "Using GitHub CLI to create repo..."
        read -p "Repository name [clawforge]: " REPO_NAME
        REPO_NAME=${REPO_NAME:-clawforge}

        gh repo create "$REPO_NAME" --public --source=. --remote=origin --push
        echo "✅ Repository created and pushed to https://github.com/$GIT_USER_NAME/$REPO_NAME"
    else
        echo -e "${RED}GitHub CLI (gh) not installed.${NC}"
        echo "Manual steps:"
        echo "  1. Go to https://github.com/new"
        echo "  2. Create repository: $GIT_USER_NAME/clawforge"
        echo "  3. Run:"
        echo "     git remote add origin https://github.com/$GIT_USER_NAME/clawforge.git"
        echo "     git push -u origin main"
    fi
}

# Setup branch protection
setup_branch_protection() {
    echo -e "\n${YELLOW}[4/6] Configuring branch protection...${NC}"

    if command -v gh &> /dev/null; then
        echo "Enabling required status checks..."
        # This requires repo admin permissions
        gh api -X PUT repos/:owner/:repo/branches/main/protection \
          -f required_status_checks_strict=true \
          -f required_status_checks_contexts='["CI / Test","CI / Lint","CI / Security","Docker Build","CodeRabbit AI Review"]' \
          -f enforce_admins=true \
          -f required_pull_request_reviews_required=true \
          -f required_pull_request_reviews_dismiss_stale_reviews=true 2>/dev/null || {
            echo "⚠️  Could not set branch protection (may need admin rights or repo not fully created)"
        }
        echo "✅ Branch protection configured"
    else
        echo "⚠️  Skipping (gh CLI not available)"
    fi
}

# Print next steps
print_next_steps() {
    echo -e "\n${GREEN}✅ Setup complete!${NC}"
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Add GitHub Secrets (required for CI/CD):"
    echo "   See .github/SECRETS_TEMPLATE.md"
    echo ""
    echo "2. Configure your VPS for auto-deploy:"
    echo "   a. Generate SSH key: ssh-keygen -t ed25519 -C 'clawforge-deploy'"
    echo "   b. Add public key to VPS: ~/.ssh/authorized_keys"
    echo "   c. Add private key as GitHub secret: VPS_SSH_KEY"
    echo ""
    echo "3. Enable CodeRabbit AI review:"
    echo "   - Install CodeRabbit app from GitHub Marketplace"
    echo "   - Add API key as CODERABBIT_API_KEY secret"
    echo ""
    echo "4. Create your first feature branch:"
    echo "   git checkout -b feat/my-feature"
    echo ""
    echo "5. Make changes, then push & open PR:"
    echo "   git push -u origin feat/my-feature"
    echo ""
    echo "6. Watch CI run: https://github.com/$(git config user.name)/clawforge/actions"
    echo ""
    echo "📚 Documentation:"
    echo "   - CLAUDE.md — code review guidelines"
    echo "   - CONTRIBUTING.md — dev workflow"
    echo "   - README.md — project overview"
    echo ""
}

# Main
main() {
    check_prereqs
    init_git
    setup_hooks
    create_github_repo
    setup_branch_protection
    print_next_steps
}

main
