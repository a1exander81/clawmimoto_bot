# Code Review Guidelines — ClawForge

## Philosophy
ClawForge is a **risk-first trading bot**. Every line of code must prioritize capital protection over performance.

## Review Checklist

### 🔴 Critical (Blockers)
- [ ] **No API keys/Secrets** in code, config examples, or comments
- [ ] **No hardcoded amounts** (stake, risk) — must be configurable
- [ ] **No auto-trading** without explicit user permission flag
- [ ] **No bypass of stoploss/trailing** logic
- [ ] **No race conditions** in order execution

### 🟡 Important (Should Fix)
- [ ] Error handling for exchange API failures (retry logic)
- [ ] Rate limit awareness (BingX limits)
- [ ] Proper logging (structured, not just print)
- [ ] Type hints complete
- [ ] Unit tests cover new logic
- [ ] Backtest results included (if strategy change)

### 🟢 Minor (Nice to Have)
- [ ] Docstrings updated
- [ ] README examples updated
- [ ] No dead code
- [ ] No unnecessary imports

## Specific Review Areas

### Strategy Changes
- Verify RSI/MACD/EMA parameters are within sane ranges
- Check session filter logic (NY/Tokyo/London only)
- Ensure `max_open_trades=3` is respected
- Confirm trailing stop offsets are correct

### Telegram UI
- All buttons must have `callback_data` (no text input)
- No `/command` text commands (except `/start` and `/cmd`)
- Confirm menu hierarchy: MAIN → TRADE_MENU → sessions
- Check for button label consistency

### Integration Hooks
- StepFun calls must have timeout and fallback
- Meme generator must not crash on missing templates
- Subscription gate must not block if payment verification fails

### Config Changes
- New fields must have defaults
- Breaking changes must be documented
- Must validate on startup

## CodeRabbit AI Instructions
When reviewing PRs, CodeRabbit should:
1. Flag any removal of risk management checks
2. Warn about increased `max_open_trades` or `stake_amount`
3. Highlight new external dependencies
4. Note any changes to Telegram UX (button additions/removals)
5. Question hardcoded values

## PR Approval Rules
- **Rentardio** must approve all PRs touching:
  - `clawforge/strategy.py`
  - `clawforge/telegram.py`
  - `configs/config.json`
- **CI must pass** (tests, lint, type-check, security scan)
- **CodeRabbit review** required for all PRs (AI pre-screen)
- **Minimum 1 human review** before merge

## Merge Requirements
- [ ] CI green (all jobs pass)
- [ ] CodeRabbit approved
- [ ] At least 1 human approval
- [ ] No critical review comments unresolved
- [ ] Version bumped (if release)

## Post-Merge
- Auto-deploy to staging (if configured)
- Run smoke test: `freqtrade status`
- Notify #dev channel on Discord/Telegram

---

**Remember: We're building an institutional tool. Every trade decision must be defensible.**
