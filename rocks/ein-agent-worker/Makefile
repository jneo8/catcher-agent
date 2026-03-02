SHELL := /bin/bash
ROCK_NAME := ein-agent-worker
VERSION := 0.1.0
REGISTRY ?= ghcr.io/jneo8

##@ ROCK Build

.PHONY: rock-clean
rock-clean:  ## Clean rockcraft build artifacts
	rockcraft clean

.PHONY: rock-build
rock-build:  ## Build ROCK image
	rockcraft pack

.PHONY: rock-load
rock-load:  ## Load ROCK into Docker
	skopeo --insecure-policy copy oci-archive:$(ROCK_NAME)_$(VERSION)_amd64.rock docker-daemon:$(ROCK_NAME):$(VERSION)

.PHONY: rock-tag
rock-tag:  ## Tag ROCK image for registry
	docker tag $(ROCK_NAME):$(VERSION) $(REGISTRY)/$(ROCK_NAME):$(VERSION)
	docker tag $(ROCK_NAME):$(VERSION) $(REGISTRY)/$(ROCK_NAME):latest

.PHONY: rock-all
rock-all: rock-build rock-load rock-tag  ## Build, load, and tag rock image

##@ Deployment

.PHONY: deploy
deploy:  ## Deploy worker with Juju (requires TEMPORAL_HOST)
	juju deploy temporal-worker-k8s catcher-agent-worker --channel stable \
		--resource temporal-worker-image=$(REGISTRY)/$(ROCK_NAME):$(VERSION) \
		--config host=$(TEMPORAL_HOST) \
		--config namespace=default \
		--config queue=catcher-agent-queue \
		--config log-level=info

.PHONY: port-forward-temporal-ui
port-forward-temporal-ui:  ## Run kubectl port-forward to access temporal ui
	kubectl port-forward -n temporal pod/temporal-ui-k8s-0 8080:8080

.PHONY: port-forward-temporal-server
port-forward-temporal-server:  ## Run kubectl port-forward to access temporal ui
	kubectl port-forward -n temporal svc/temporal-k8s 7233:7233

.PHONY: temporal-create-default-namespace
create-default-namespace:  ## Create default namespace on temporal
	 juju run temporal-admin-k8s/0 cli args="operator namespace create --namespace default --retention 3d" --wait 1m

##@ OpenAPI Specs

SPECS_DIR := specs

# Default versions (can be overridden: make download-k8s-spec K8S_VERSION=1.34)
K8S_VERSION ?= 1.35
CEPH_VERSION ?= tentacle
GRAFANA_VERSION ?= 12

# Source URL templates
K8S_OPENAPI_URL = https://raw.githubusercontent.com/kubernetes/kubernetes/release-$(K8S_VERSION)/api/openapi-spec/swagger.json
CEPH_OPENAPI_URL = https://raw.githubusercontent.com/ceph/ceph/$(CEPH_VERSION)/src/pybind/mgr/dashboard/openapi.yaml
GRAFANA_OPENAPI_URL = https://raw.githubusercontent.com/grafana/grafana/v$(GRAFANA_VERSION).0.0/public/api-merged.json

.PHONY: download-openapi-specs
download-openapi-specs: download-k8s-spec download-ceph-spec download-grafana-spec  ## Download all OpenAPI specs
	@echo "All OpenAPI specs downloaded to $(SPECS_DIR)/"

.PHONY: download-k8s-spec
download-k8s-spec:  ## Download Kubernetes OpenAPI spec (K8S_VERSION=1.35)
	@mkdir -p $(SPECS_DIR)/kubernetes
	@echo "Downloading Kubernetes $(K8S_VERSION) OpenAPI spec..."
	curl -L -o $(SPECS_DIR)/kubernetes/$(K8S_VERSION).json $(K8S_OPENAPI_URL)

.PHONY: download-ceph-spec
download-ceph-spec:  ## Download Ceph OpenAPI spec (CEPH_VERSION=tentacle)
	@mkdir -p $(SPECS_DIR)/ceph
	@echo "Downloading Ceph $(CEPH_VERSION) OpenAPI spec..."
	curl -L -o $(SPECS_DIR)/ceph/$(CEPH_VERSION).yaml $(CEPH_OPENAPI_URL)

.PHONY: download-grafana-spec
download-grafana-spec:  ## Download Grafana OpenAPI spec (GRAFANA_VERSION=12)
	@mkdir -p $(SPECS_DIR)/grafana
	@echo "Downloading Grafana v$(GRAFANA_VERSION) OpenAPI spec..."
	curl -L -o $(SPECS_DIR)/grafana/$(GRAFANA_VERSION).json $(GRAFANA_OPENAPI_URL)

##@ Help

.PHONY: help
help:  ## Display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
