# iCloud Cleanup Daemon Makefile
# Usage: make [target]

SHELL := /bin/bash
.PHONY: help install uninstall start stop restart status logs dry-run scan once config test lint typecheck clean

# Configuration
PROJECT_DIR := $(shell pwd)
VENV_PYTHON := $(PROJECT_DIR)/.venv/bin/python
PLIST_NAME := com.cloud.icloud-cleanup
PLIST_SRC := $(PROJECT_DIR)/launchd/$(PLIST_NAME).plist
PLIST_DEST := $(HOME)/Library/LaunchAgents/$(PLIST_NAME).plist
LOG_DIR := $(HOME)/Library/Logs
LOG_FILE := $(LOG_DIR)/icloud-cleanup-daemon.log
STDOUT_LOG := $(LOG_DIR)/icloud-cleanup-daemon-stdout.log
STDERR_LOG := $(LOG_DIR)/icloud-cleanup-daemon-stderr.log

# Colors
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m

help: ## Show this help
	@printf "iCloud Cleanup Daemon\n\n"
	@printf "Usage: make [target]\n\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(NC) %s\n", $$1, $$2}'

# ============================================================================
# Development Commands
# ============================================================================

dry-run: ## Preview what would be deleted (no changes)
	@printf "$(YELLOW)Running dry-run...$(NC)\n"
	uv run icloud-cleanup run --dry-run

scan: ## Scan for conflict files without deleting
	@printf "$(YELLOW)Scanning for conflicts...$(NC)\n"
	uv run icloud-cleanup scan

once: ## Run cleanup once and exit
	@printf "$(YELLOW)Running single cleanup pass...$(NC)\n"
	uv run icloud-cleanup run --once

run: ## Run daemon in foreground (Ctrl+C to stop)
	@printf "$(YELLOW)Starting daemon in foreground...$(NC)\n"
	uv run icloud-cleanup run

config: ## Show current configuration
	uv run icloud-cleanup config --show

config-init: ## Create default configuration file
	uv run icloud-cleanup config --init

recovery-list: ## List recoverable files
	uv run icloud-cleanup recovery --list

# ============================================================================
# launchd Service Management
# ============================================================================

install: ## Install as launchd service (auto-start on login)
	@printf "$(YELLOW)Installing launchd service...$(NC)\n"
	@mkdir -p $(HOME)/Library/LaunchAgents
	@sed -e 's|/Users/cloud/Developer/icloud-cleanup-daemon|$(PROJECT_DIR)|g' \
	     -e 's|/Users/cloud/Library/Logs|$(LOG_DIR)|g' \
	     $(PLIST_SRC) > $(PLIST_DEST)
	@printf "$(GREEN)Installed: $(PLIST_DEST)$(NC)\n\n"
	@printf "To start the service now, run: make start\n"
	@printf "The service will auto-start on login.\n"

uninstall: stop ## Uninstall launchd service
	@printf "$(YELLOW)Uninstalling launchd service...$(NC)\n"
	@rm -f $(PLIST_DEST)
	@printf "$(GREEN)Removed: $(PLIST_DEST)$(NC)\n"

start: ## Start the launchd service
	@if [ ! -f $(PLIST_DEST) ]; then \
		printf "$(RED)Service not installed. Run 'make install' first.$(NC)\n"; \
		exit 1; \
	fi
	@printf "$(YELLOW)Starting service...$(NC)\n"
	launchctl load $(PLIST_DEST) 2>/dev/null || true
	@sleep 1
	@make status

stop: ## Stop the launchd service
	@printf "$(YELLOW)Stopping service...$(NC)\n"
	-launchctl unload $(PLIST_DEST) 2>/dev/null || true
	@printf "$(GREEN)Service stopped$(NC)\n"

restart: stop start ## Restart the launchd service

status: ## Show service status
	@printf "$(YELLOW)Service status:$(NC)\n"
	@if launchctl list | grep -q $(PLIST_NAME); then \
		printf "$(GREEN)● Running$(NC)\n"; \
		launchctl list | grep $(PLIST_NAME); \
	else \
		printf "$(RED)○ Not running$(NC)\n"; \
	fi
	@printf "\n$(YELLOW)Installed:$(NC) $(shell [ -f $(PLIST_DEST) ] && echo 'Yes' || echo 'No')\n"

logs: ## Tail daemon logs (Ctrl+C to stop)
	@printf "$(YELLOW)Tailing logs... (Ctrl+C to stop)$(NC)\n"
	@tail -f $(LOG_FILE) $(STDOUT_LOG) $(STDERR_LOG) 2>/dev/null || \
		printf "$(RED)No log files found. Is the daemon running?$(NC)\n"

logs-error: ## Show recent errors
	@printf "$(YELLOW)Recent errors:$(NC)\n"
	@tail -50 $(STDERR_LOG) 2>/dev/null || printf "No errors found\n"

# ============================================================================
# Testing & Quality
# ============================================================================

test: ## Run tests
	uv run pytest -v

lint: ## Run linter
	uv run ruff check src/ tests/

typecheck: ## Run type checker
	uv run ty check src/

check: lint typecheck test ## Run all checks (lint, typecheck, test)

# ============================================================================
# Setup & Cleanup
# ============================================================================

setup: ## Install dependencies
	uv sync

clean: ## Clean up cache files
	rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
