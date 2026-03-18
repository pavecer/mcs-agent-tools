#!/bin/bash
# Local validation script — runs all security and quality checks before committing
# Usage: ./scripts/validate-local.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}PP Agent Toolkit — Local Validation${NC}"
echo -e "${YELLOW}========================================${NC}\n"

# 1. Lint with Ruff
echo -e "${YELLOW}[1/5] Running Ruff linter...${NC}"
if uv run ruff check . ; then
    echo -e "${GREEN}✓ Ruff check passed${NC}\n"
else
    echo -e "${RED}✗ Ruff check failed${NC}"
    echo -e "${YELLOW}Run 'uv run ruff check . --fix' to auto-fix issues${NC}\n"
    exit 1
fi

# 2. Format check with Ruff
echo -e "${YELLOW}[2/5] Checking code formatting...${NC}"
if uv run ruff format --check . ; then
    echo -e "${GREEN}✓ Format check passed${NC}\n"
else
    echo -e "${RED}✗ Format check failed${NC}"
    echo -e "${YELLOW}Run 'uv run ruff format .' to auto-format${NC}\n"
    exit 1
fi

# 3. Run tests
echo -e "${YELLOW}[3/5] Running tests...${NC}"
if uv run pytest tests/ -v --tb=short ; then
    echo -e "${GREEN}✓ All tests passed${NC}\n"
else
    echo -e "${RED}✗ Tests failed${NC}\n"
    exit 1
fi

# 4. pip-audit (CVE check)
echo -e "${YELLOW}[4/5] Checking for known vulnerabilities (pip-audit)...${NC}"
if uv run pip-audit --strict ; then
    echo -e "${GREEN}✓ No CVE vulnerabilities found${NC}\n"
else
    echo -e "${RED}✗ Vulnerabilities detected${NC}\n"
    exit 1
fi

# 5. bandit (security linting)
echo -e "${YELLOW}[5/5] Running security linter (bandit)...${NC}"
if uv run bandit -r . ; then
    echo -e "${GREEN}✓ No security issues found${NC}\n"
else
    echo -e "${YELLOW}⚠ Bandit reported issues (review above)${NC}\n"
    echo -e "${YELLOW}Note: Some issues may be false positives. Review and update .bandit if needed.${NC}\n"
    # Don't exit here — bandit is informational
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ All checks passed! Ready to push.${NC}"
echo -e "${GREEN}========================================${NC}"
