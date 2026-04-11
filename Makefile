# ══════════════════════════════════════════════════════════════════════
# JARVIS Robot — Convenience Commands
# Usage: make <target>
# ══════════════════════════════════════════════════════════════════════

.PHONY: install start stop restart logs status health hw-test test update clean help

JARVIS_DIR := $(shell pwd)
VENV := $(JARVIS_DIR)/venv/bin
PI_DIR := $(JARVIS_DIR)/pi

# ── Installation ──────────────────────────────────────────────────────

install: ## Full installation (system deps + Python + models + systemd)
	@bash scripts/install_pi.sh

install-quick: ## Reinstall without re-downloading models
	@bash scripts/install_pi.sh --skip-models

# ── Service Control ───────────────────────────────────────────────────

start: ## Start JARVIS service
	@sudo systemctl start jarvis
	@echo "JARVIS started. View logs: make logs"

stop: ## Stop JARVIS service
	@sudo systemctl stop jarvis
	@echo "JARVIS stopped."

restart: ## Restart JARVIS service
	@sudo systemctl restart jarvis
	@echo "JARVIS restarted. View logs: make logs"

# ── Monitoring ────────────────────────────────────────────────────────

logs: ## Follow live JARVIS logs
	@journalctl -u jarvis -f --no-hostname

logs-today: ## Show today's logs
	@journalctl -u jarvis --since today --no-hostname

logs-errors: ## Show only errors from today
	@journalctl -u jarvis --since today -p err --no-hostname

status: ## Show JARVIS service status
	@sudo systemctl status jarvis --no-pager -l

health: ## Run full health check
	@bash scripts/health_check.sh

# ── Testing ───────────────────────────────────────────────────────────

hw-test: ## Run hardware diagnostic
	@$(VENV)/python scripts/test_hardware.py

test: ## Run pytest suite
	@cd $(JARVIS_DIR) && $(VENV)/pytest tests/ -v

run: ## Run JARVIS manually (foreground, Ctrl+C to stop)
	@cd $(PI_DIR) && $(VENV)/python -m jarvis.main

# ── Updates ───────────────────────────────────────────────────────────

update: ## Pull latest code + update deps + restart (with rollback)
	@bash scripts/update_pi.sh

deps: ## Update Python dependencies only
	@$(VENV)/pip install -r $(PI_DIR)/requirements.txt -q
	@echo "Dependencies updated."

# ── Configuration ─────────────────────────────────────────────────────

config: ## Edit .env configuration
	@$${EDITOR:-nano} $(PI_DIR)/.env

config-show: ## Show current configuration (secrets masked)
	@cat $(PI_DIR)/.env | sed 's/\(API_KEY=\).*/\1***/' | sed 's/\(TOKEN=\).*/\1***/' | sed 's/\(PASSWORD=\).*/\1***/'

# ── Cleanup ───────────────────────────────────────────────────────────

clean: ## Remove Python cache files
	@find $(JARVIS_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find $(JARVIS_DIR) -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cache cleaned."

clean-data: ## Remove conversation database (WARNING: deletes memory)
	@rm -f $(PI_DIR)/data/jarvis.db
	@echo "Conversation database deleted."

# ── Help ──────────────────────────────────────────────────────────────

help: ## Show this help
	@echo ""
	@echo "JARVIS Robot — Available Commands"
	@echo "══════════════════════════════════════════"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'
	@echo ""

.DEFAULT_GOAL := help
