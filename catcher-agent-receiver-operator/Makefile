SHELL := /bin/bash
ROCK_NAME := catcher-agent-receiver-operator
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

.PHONY: rock-all
rock-all: rock-build rock-load rock-tag  ## Build, load, and tag rock image

##@ Charm Build

.PHONY: charm-build
charm-build:  ## Build the charm
	charmcraft pack

##@ Deployment

.PHONY: deploy
deploy:  ## Deploy charm with pre-uploaded image
	juju deploy ./$(ROCK_NAME)_amd64.charm --resource app-image=$(REGISTRY)/$(ROCK_NAME):$(VERSION)

.PHONY: update-image
update-image: rock-load  ## Update running charm with new local image
	./.dev-scripts/update-image.sh

.PHONY: port-forward
port-forward:  ## Run kubectl port-forward to access receiver service
	kubectl port-forward -n temporal svc/$(ROCK_NAME) 8080:8080

##@ Help

.PHONY: help
help:  ## Display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
