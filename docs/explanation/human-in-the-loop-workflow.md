# Human-in-the-Loop Workflow Architecture

This document explains the architectural decisions and flow of the Human-in-the-Loop (HITL) investigation workflow. It provides a conceptual understanding of how the agents collaborate, how data is shared, and how the system interacts with the underlying Temporal workflow engine.

## The Handoff Flow: Conversational Swarm

The core of the system is a **Conversational Swarm**. Unlike a hierarchical chain where a manager blindly commands subordinates, this workflow treats the user as a key participant in the delegation process.

### The "Ask-First" Pattern

The workflow enforces a strict **"Ask-First"** protocol for delegation. This prevents the system from spiraling into "agent runaways," where multiple specialists are called in rapid succession without user oversight.

1.  **Proposal**: The Orchestrator (Investigation Agent) analyzes the user's request or alert data. If it identifies a need for domain expertise (e.g., a Ceph cluster error), it **proposes** a specialist: *"I see disk errors. Shall I consult the Storage Specialist?"*
2.  **Confirmation**: The workflow suspends execution, waiting for an explicit signal from the user via the CLI.
3.  **Delegation (Handoff)**: Once the user confirms (e.g., types "Yes"), the Orchestrator executes a **Handoff**. This transfers execution control to the specific Domain Specialist.
4.  **Investigation & Return**: The specialist performs its technical investigation using MCP tools and then **hands off back** to the Orchestrator. The Orchestrator then synthesizes the findings for the user.

This loop ensures that the user remains the ultimate decision-maker regarding the scope and depth of the investigation.

## Agent Roles

The swarm is composed of two distinct categories of agents, each with specific responsibilities and access levels.

### 1. The Orchestrator (Investigation Agent)
*   **Role**: Project Manager & User Interface.
*   **Access**: Has **NO** direct access to infrastructure tools (MCP).
*   **Responsibilities**:
    *   Maintains the conversation history and context.
    *   Synthesizes raw technical data into human-readable summaries.
    *   Manages the **Shared Context** (Blackboard).
    *   Decides *who* needs to be involved next.

### 2. Domain Specialists
*   **Role**: Technical Subject Matter Experts (SMEs).
*   **Access**: Have **exclusive** access to domain-specific MCP servers.
*   **Responsibilities**:
    *   **Compute Specialist**: Investigates Kubernetes nodes, pods, and container runtimes.
    *   **Storage Specialist**: Investigates Ceph clusters, OSDs, PVCs, and block devices.
    *   **Network Specialist**: Investigates DNS, Ingress, Services, and connectivity.
    *   **Focus**: Their primary goal is to discover facts and write them to the Shared Context. They do not engage in "small talk"; they report technical findings and return control.

## Available Tools & The Blackboard Pattern

To prevent information silos and avoid passing massive context objects between agents, the system employs a **Shared Context** (or Blackboard) pattern.

### The Blackboard Tools
*   **`update_shared_context`**: Used by Specialists to record observations.
    *   *Example*: "Found OSD.5 is down with I/O errors (Confidence: 0.95)."
*   **`get_shared_context`**: Used by all agents to see what has already been discovered. This prevents redundant work (e.g., the Network Specialist checking a node that the Compute Specialist already marked as 'NotReady').
*   **`group_findings`**: Used by the Orchestrator to perform **Semantic Grouping**. It links isolated findings into a coherent incident.
    *   *Example*: Grouping "OSD Down", "PVC Pending", and "Pod CrashLoop" into a single "Storage Cluster Failure" incident.
*   **`print_findings_report`**: Generates the final, structured Markdown report for the user.

## Temporal Integration: Signals vs. Updates

The workflow is built on **Temporal**, a durable execution platform. The interaction model between the CLI (Client) and the Workflow is a critical architectural detail.

### Why Signals?
In a modern Temporal setup, **Workflow Updates** are often preferred for interactive use cases because they provide a synchronous request/response mechanism (blocking the client until the workflow processes the input).

However, Workflow Updates require **Temporal Server v1.21.0+** and specific SDK support. Due to version constraints in our current deployment environment (or to maintain compatibility with older clusters), this project relies on the more universally supported **Workflow Signals**.

### The Signal-Query Pattern
1.  **Asynchronous Input**: When the user types a message, the CLI sends a `send_message` **Signal**. From the client's perspective, this is "fire-and-forget."
2.  **Event Queue**: The workflow receives the signal and places it into an internal event queue. This ensures that if the agent is busy (e.g., running a long query), the user's message is not lost; it is buffered.
3.  **Polling for Output**: Because the Signal does not return a value, the CLI must periodically **Query** the workflow state (`get_messages`) to see if the agent has responded.

This pattern, while slightly more complex to implement in the client, provides high durability. The user can disconnect their CLI, and the investigation state remains safe in the Temporal cluster, ready for them to reconnect and resume.
