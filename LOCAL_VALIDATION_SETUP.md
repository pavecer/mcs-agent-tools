# Local Security Validation Setup — Quick Start

## What Changed

✅ **Non-deployment CI workflow removed** — Validation ownership is local before deployment
✅ **Pre-commit hooks configured** — Automatic validation runs before each commit
✅ **Local validation script added** — `scripts/validate-local.sh` for manual verification
✅ **Copilot instructions updated** — Full developer workflow documented

---

## One-Time Local Setup (Do This Once)

### 1. Install pre-commit framework
```bash
pip install pre-commit
```

### 2. Install git hooks
```bash
cd /Users/pavelvecer/GitHubRepos/pp-agent-renamer
pre-commit install
```

### 3. (Optional) Verify setup
```bash
# Run checks on all files
pre-commit run --all-files
```

---

## Your New Developer Workflow

### Before Each Commit (Automatic)
After setup, every time you run `git commit`:
1. **Trailing whitespace** is removed
2. **End-of-file** issues are fixed
3. **YAML/JSON/TOML** syntax is validated
4. **Merge conflicts** are detected

✅ If checks pass → commit succeeds
❌ If checks fail → commit is blocked until you fix

### Comprehensive Validation Before Pushing
```bash
# Run full validation suite (Ruff, tests, CVE, security)
bash scripts/validate-local.sh

# Or run individual checks:
uv run ruff check .                    # Lint
uv run ruff format .                   # Auto-format
uv run pytest tests/ -v                # Run tests
uv run pip-audit --strict              # CVE scan
uv run bandit -r .                     # Security scan
```

### Auto-Fix Common Issues
```bash
# Auto-fix linting issues
uv run ruff check . --fix

# Auto-format code
uv run ruff format .
```

---

## GitHub Actions Now (Deployment-Focused)

Only deployment-related workflows remain.

This means:
- ✅ Local validation is the primary quality and security gate
- ✅ Deployment pipeline stays focused on Azure release steps
- ✅ You should run the full checklist before every deployment-related change

---

## What Each Check Does

| Check | Purpose | Auto-fix? |
|-------|---------|-----------|
| **Ruff Lint** | Code style, import sorting | Yes (with `--fix`) |
| **Ruff Format** | Consistent formatting (line length 120) | Yes |
| **Pytest** | Unit tests (76 tests) | No — debug and fix |
| **pip-audit** | CVE/vulnerability scan | No — update deps |
| **Bandit** | Security issue scanner | No — review issues |

---

## Troubleshooting

### Pre-commit isn't running on commit
```bash
# Re-install hooks
pre-commit install --force-all
```

### Skip checks once (emergency only)
```bash
# Bypass pre-commit for this commit
git commit --no-verify

# ⚠️ Remember: you're responsible for the validation then!
```

### Update pre-commit hooks
```bash
pre-commit autoupdate
```

---

## Next Steps

1. Run the one-time setup commands above
2. Make a test commit to verify pre-commit works
3. Read `.github/copilot-instructions.md` for full context
4. You're done! — Local validation runs automatically on every commit

---

**Questions?** Check `.github/copilot-instructions.md` → "Local Validation" section
