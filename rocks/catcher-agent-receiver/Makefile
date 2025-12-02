SHELL := /bin/bash
ROCK_NAME := catcher-agent-receiver
VERSION := 0.1
REGISTRY ?= ghcr.io/jneo8

##@ Requirements

.PHONY: requirements
requirements:  ## Generate requirements.txt from pyproject.toml using uv
	uv pip compile pyproject.toml -o requirements.txt

##@ ROCK Build

.PHONY: rock-clean
rock-clean:  ## Clean rockcraft build artifacts
	rockcraft clean

.PHONY: rock-build
rock-build: requirements  ## Build ROCK image (generates requirements.txt first)
	ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=True rockcraft pack

.PHONY: rock-load
rock-load:  ## Load ROCK into Docker
	skopeo --insecure-policy copy oci-archive:$(ROCK_NAME)_$(VERSION)_amd64.rock docker-daemon:$(ROCK_NAME):$(VERSION)

.PHONY: rock-tag
rock-tag:  ## Tag ROCK image for registry
	docker tag $(ROCK_NAME):$(VERSION) $(REGISTRY)/$(ROCK_NAME):$(VERSION)
	docker tag $(ROCK_NAME):$(VERSION) $(REGISTRY)/$(ROCK_NAME):latest

.PHONY: rock-push
rock-push:  ## Push ROCK image to registry
	docker push $(REGISTRY)/$(ROCK_NAME):$(VERSION)
	docker push $(REGISTRY)/$(ROCK_NAME):latest

.PHONY: rock-all
rock-all: rock-build rock-load rock-tag  ## Build, load, and tag rock image

##@ Development

.PHONY: run-local
run-local:  ## Run the FastAPI app locally (requires dependencies installed)
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8080

.PHONY: test
test:  ## Run tests (placeholder)
	@echo "No tests configured yet"

##@ Help

.PHONY: help
help:  ## Display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
