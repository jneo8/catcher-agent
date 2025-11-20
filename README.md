# Catcher Agent

A distributed alert processing system that uses AI agents to analyze and respond to alerts through a webhook-based architecture.

## Overview

Catcher Agent is composed of two main components that work together to receive, process, and handle alerts using AI-powered workflows:

1. **Receiver Operator** - A webhook service that receives alert notifications
2. **Worker** - A Temporal-based worker that processes the trouble shooting using AI agents

## Architecture

```
Alert Source → Receiver Operator (Webhook) → Temporal Server → Worker (AI Agent) ↔ MCP Services
                                                                                      ├─ Kubernetes API
                                                                                      ├─ OpenStack API
                                                                                      ├─ Monitoring Systems
                                                                                      └─ Infrastructure Tools
```

The system uses Temporal workflows to ensure reliable, distributed processing of alerts with AI-powered analysis. When an alert is received, the AI agent communicates with various MCP (Model Context Protocol) services to gather information, diagnose issues, and perform troubleshooting actions on the infrastructure.

## Components

### catcher-agent-receiver-operator

A Juju charm that provides a webhook endpoint to receive alert notifications. Built with:
- FastAPI for the webhook API
- Juju Operator Framework for deployment and lifecycle management
- Triggers Temporal workflows when alerts are received

### catcher-agent-worker

A Temporal worker that executes AI-powered workflows to process alerts. Built with:
- Temporal workflow engine for reliable distributed execution
- OpenAI Agents for AI-powered alert analysis
- LiteLLM for flexible LLM provider support (supports Gemini and other models)

## Development

Both components are Python-based projects using:
- Python 3.12+
- uv for dependency management
- Rockcraft for container image building
- Juju for Kubernetes deployment
