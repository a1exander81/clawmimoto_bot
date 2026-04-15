.PHONY: help install test lint format type-check security clean docker-build docker-run deploy

help:  ## Show this help
	@echo "ClawForge Development Commands"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies
	pip install -e .[dev]
	pre-commit install

test:  ## Run tests with coverage
	pytest tests/ -v --cov=clawforge --cov-report=term-missing

test-fast:  ## Run tests without coverage
	pytest tests/ -v

lint:  ## Run linter (ruff)
	ruff check clawforge/ tests/

format:  ## Auto-format code (black)
	black clawforge/ tests/

type-check:  ## Run mypy type checking
	mypy clawforge/ --ignore-missing-imports

security:  ## Run security scans
	safety check --full-report || true
	bandit -r clawforge/ -ll

all-checks: lint format type-check test security  ## Run all quality checks

docker-build:  ## Build Docker image
	docker build -t clawforge:latest .

docker-run:  ## Run in Docker (dry-run)
	docker-compose up -d
	docker logs -f clawforge

docker-stop:  ## Stop Docker container
	docker-compose down

clean:  ## Clean build artifacts
	find . -type d -name "__pycache__" -exec rm -r {} +
	find . -type d -name "*.egg-info" -exec rm -r {} +
	find . -type d -name ".mypy_cache" -exec rm -r {} +
	find . -type d -name ".ruff_cache" -exec rm -r {} +
	find . -type d -name ".pytest_cache" -exec rm -r {} +
	rm -rf .coverage htmlcov/ build/ dist/

backtest:  ## Run backtest (requires config)
	freqtrade backtesting --strategy Claw5MSniper --timerange 20260101-20260401

dry-run:  ## Start bot in dry-run mode
	freqtrade trade --strategy Claw5MSniper --dry-run

deploy-staging:  ## Deploy to staging VPS
	./deploy/staging.sh

deploy-prod:  ## Deploy to production VPS
	./deploy/prod.sh

# CI simulation
ci-local: all-checks  ## Run local CI pipeline
	@echo "✅ All checks passed — ready to push"
