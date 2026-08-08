# ═════════════════════════════════════════════════════════════════════
#  Traffic Violation Detection System — Makefile
#
#  Fully automated flow — models + videos are pulled from S3 on first
#  boot, nothing is stored in Git and nothing is downloaded manually.
#
#  Quick start:
#    make reset          # wipe ALL images/volumes + rebuild + start
#    make up             # docker compose up (builds if needed)
#    make clean          # one-click wipe: containers, volumes, images, cache
#
#  Requirements: Docker + AWS CLI configured (aws configure)
# ═════════════════════════════════════════════════════════════════════

SHELL := /bin/bash

.PHONY: help up up-build build clean clean-all reset logs ps stop down

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Start services (build images if missing) — auto-pulls models from S3
	docker compose up -d

up-build: ## Force rebuild all images, then start — auto-pulls models from S3
	docker compose up -d --build

build: ## Build all 3 images (worker / api / dashboard)
	docker compose build

clean: ## ONE-CLICK WIPE — remove ALL traffic containers, volumes, images + build cache (works even from another clone/folder)
	@echo "Wiping all Traffic Detection Docker state (containers, volumes, images, cache)..."
	docker compose down -v --rmi all 2>/dev/null || true
	docker rm -f traffic-worker traffic-api traffic-dashboard 2>/dev/null || true
	docker rmi -f traffic-worker:latest traffic-api:latest traffic-dashboard:latest 2>/dev/null || true
	@docker volume ls -q | grep -i traffic | xargs docker volume rm -f 2>/dev/null || true
	docker builder prune -f 2>/dev/null || true
	@echo "Done. Next 'docker compose up' auto-pulls models + videos from S3 again."

clean-all: ## NUCLEAR wipe — everything traffic-related + ALL unused Docker images/volumes/cache on the host
	make clean
	docker system prune -af --volumes

reset: clean up-build ## Full reset: wipe everything, rebuild, start (auto-pull)

logs: ## Tail all service logs
	docker compose logs -f

logs-worker: ## Tail worker logs (see the S3 pull / model load)
	docker compose logs -f worker

ps: ## Show container status
	docker compose ps

stop: ## Stop services (keep volumes/data)
	docker compose stop

down: ## Stop services and remove containers (keep named volumes)
	docker compose down
