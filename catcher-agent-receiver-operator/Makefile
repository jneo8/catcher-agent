SHELL := /bin/bash
CHARM_NAME := catcher-agent-receiver
VERSION := 0.1
REGISTRY ?= ghcr.io/jneo8

##@ Requirements

.PHONY: requirements
requirements:  ## Generate requirements.txt from pyproject.toml using uv
	uv pip compile pyproject.toml -o requirements.txt

##@ Charm Build

.PHONY: charm-build
charm-build: requirements  ## Build the charm (generates requirements.txt first)
	charmcraft pack

##@ Deployment

.PHONY: deploy
deploy:  ## Deploy charm with pre-uploaded image
	juju deploy ./$(CHARM_NAME)_amd64.charm --resource app-image=$(REGISTRY)/$(CHARM_NAME):$(VERSION)

##@ Help

.PHONY: help
help:  ## Display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
