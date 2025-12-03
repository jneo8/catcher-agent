# Ein Agent

A distributed AI-powered workflow orchestration system that uses intelligent agents to analyze and respond to events through a flexible API architecture.

## Overview

Ein Agent is composed of two main components that work together to receive, process, and handle events using AI-powered workflows:

1. **API Operator** - A FastAPI service that receives webhooks and triggers workflows
2. **Worker** - A Temporal-based worker that executes AI-powered troubleshooting workflows

## Architecture

```
Event Source → API (Webhook) → Temporal Server → Worker (AI Agent) ↔ MCP Services
                                                                       ├─ Kubernetes API
                                                                       ├─ OpenStack API
                                                                       ├─ Monitoring Systems
                                                                       └─ Infrastructure Tools
```

The system uses Temporal workflows to ensure reliable, distributed processing with AI-powered analysis. When an event is received (e.g., Prometheus Alertmanager webhook), the AI agent communicates with various MCP (Model Context Protocol) services to gather information, diagnose issues, and perform troubleshooting actions on the infrastructure.

## Components

### ein-agent-api-operator

A Juju charm that provides an API service to receive webhooks and trigger workflows. Built with:
- FastAPI for the webhook API
- Juju Operator Framework for deployment and lifecycle management
- Triggers Temporal workflows when events are received

### ein-agent-worker

A Temporal worker that executes AI-powered workflows. Built with:
- Temporal workflow engine for reliable distributed execution
- OpenAI Agents for AI-powered analysis
- LiteLLM for flexible LLM provider support (supports Gemini and other models)

## Development

Both components are Python-based projects using:
- Python 3.12+
- uv for dependency management
- Rockcraft for container image building
- Juju for Kubernetes deployment
