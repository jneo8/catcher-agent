# Ein Agent

## Overview

Ein Agent is a distributed AI-powered workflow orchestration system designed to analyze and respond to operation events. It is composed of two main components:

1.  **CLI** - A command-line interface to trigger and manage workflows.
2.  **Worker** - A Temporal-based worker that executes AI-powered troubleshooting workflows.

## Architecture

```
                                      +-----------------+
                                      | Temporal Server |
     +-------------------+            +--------+--------+
     | Prometheus Alert  |                     ^
     |      Manager      |                     |
     +---------+---------+                     | (3) Pick up task
               ^                               |
               . (1) Pick alerts               v
               .                     +----------------------------------------------------------+
        /-------------\              | Agent System                                             |
       /               \             |                                                          |
      <  Ein Agent CLI  > - - (2) - ->  +-----------------------+                               |
       \               / Trigger WF  |  | Temporal Worker       |                               |
        \-------------/              |  |                       |      (4) Inference loop       |
               |                     |  |      [Ein Agent] < - - - - - - - - - - - - - - ->  /-----\
               |                     |  |           |           |                           <  LLM  >
               | (7) Check           |  +-----------+-----------+                            \-----/
               |                     |              |       \                                   |
               |                     |              |        \ (5) Search                       |
               v                     |              | (4)     - - - -> [ RAGs ]                 |
       +---------------+             |              | List/                                     |
       | Output Target | < - (6) - - +              | Call                                      |
       +---------------+  Send Output|              v                                           |
                                     |      [ UTCP Tools ]                                      |
                                     |              |                                           |
                                     +--------------|-------------------------------------------+
                                                    |
                                                    | Read-only calls
                                                    v
                                          +---------------------+
                                          |   Cloud Deployment  |
                                          |   (k8s, openstack,  |
                                          |    ceph, ovn,       |
                                          |    monitoring, ..)  |
                                          +---------------------+
```


The system uses Temporal workflows to ensure reliable, distributed processing with AI-powered analysis. When a workflow is triggered via the CLI, the AI agent uses UTCP (Universal Tool Calling Protocol) tools generated from OpenAPI specifications to gather information, diagnose issues, and perform troubleshooting actions on the infrastructure.

## Components

### ein-agent-cli

A command-line interface to trigger and manage workflows. It allows users to:
- Start interactive human-in-the-loop investigation sessions.
- Connect to existing investigation workflows.

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
