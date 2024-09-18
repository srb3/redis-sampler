# Makefile for go-echo-server project

# Variables
BINARY_NAME := redis-rla-sampler
DOCKER_IMAGE := $(DOCKER_REPO)/$(BINARY_NAME):latest
DOCKER_IMAGE_VERSION := $(DOCKER_REPO)/$(BINARY_NAME):$(IMAGE_VERSION)

# Default target
.PHONY: all
all: build

# Build Docker image
.PHONY: docker-build
docker-build:
	@echo "Building Docker image..."
	docker build -t $(DOCKER_IMAGE) .
	docker build -t $(DOCKER_IMAGE_VERSION) .

# Push Docker image to repository
.PHONY: docker-push
docker-push:
	@echo "Pushing Docker image..."
	docker push $(DOCKER_IMAGE)
	docker push $(DOCKER_IMAGE_VERSION)
