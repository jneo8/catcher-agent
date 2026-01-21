# Incident Correlation Workflow Architecture

This document explains the high-level architecture of the Incident Correlation Workflow, a multi-agent system designed to investigate and correlate Prometheus alerts.

## Overview

The Incident Correlation Workflow orchestrates a swarm of AI agents to investigate alerts in parallel, identify root causes, and determine if multiple alerts are related (e.g., a storage failure causing an application crash).

It uses a **Router-Assisted** pattern where a deterministic "Router" guides the investigation path, ensuring that the correct domain specialists are consulted based on the alert content.

## Architecture

The workflow follows a hierarchical structure designed for extensibility. New specialists can be added simply by registering their Model Context Protocol (MCP) server; the orchestration logic remains unchanged.

```text
                          +-------------------------+
                          |   User / AlertManager   | <=======================+
                          +------------+------------+                         ||
                                       | (1) Trigger                          || (8) Final
                                       v                                      ||     Report
                          +------------+------------+                         ||
                          |    MultiAlertLeader     | ========================+
                          +------------+------------+                         |
                                       | (2) Delegate                         |
                                       v                                      | (7) Single
                          +------------+------------+                         |     RCA
                          |    SingleAlertLeader    | ------------------------+
                          +--+-------^--------+--^--+
                             |       |        |  |
                  (3) Ask    |       | (4)    |  |
                  Router     |       | Plan   |  |
                             v       |        |  |
                       +-----+-------+        |  |
                       | RouterAgent |        |  |
                       +-------------+        |  |
                                              |  |
                    (5) Loop: Call Specialist |  | (6) Loop: Return Findings
                       +----------------------+  |
                       |                         |
           +-----------+                         +---------------------------+
           |           |                                                     |
           v           v                                                     |
     +----------+ +----------+                                               |
     | Spec A   | | Spec B   |  ... (Sequential) ...                         |
     +-----+----+ +-----+----+                                               |
           |            |                                                    |
           +------------+----------------------------------------------------+
```

## Components

### 1. MultiAlertLeader (The Coordinator)
*   **Role:** Project Manager.
*   **Responsibility:** Receives the list of firing alerts, delegates each alert to a `SingleAlertLeader` for investigation, and synthesizes the final Incident Report.
*   **Output:** A consolidated report identifying the primary root cause and any cascading symptoms.

### 2. SingleAlertLeader (The Investigator)
*   **Role:** Lead Detective for a specific alert.
*   **Responsibility:** Investigates *one* alert in depth. It does not guess which expert to call; instead, it relies on the `RouterAgent`.
*   **Goal:** Produce a Root Cause Analysis (RCA) for its assigned alert.

### 3. RouterAgent (The Dispatcher)
*   **Role:** Deterministic Routing Logic.
*   **Responsibility:** Analyzes the alert text for keywords (e.g., "rbd", "pvc", "CrashLoopBackOff", "mysql") and maps them to a specific list of Specialists.
*   **Mechanism:** Uses a hard-coded keyword mapping to ensure 100% coverage. 
    *   *Example:* Keyword "rbd" $\rightarrow$ Trigger `CephSpecialist`.
    *   *Example:* Keyword "innodb" $\rightarrow$ Trigger `MySQLSpecialist` (future).

### 4. Domain Specialists (The Experts)
*   **Role:** Subject Matter Experts.
*   **Responsibility:** Use Model Context Protocol (MCP) tools to query the actual infrastructure.
*   **Extensibility:** This layer is dynamic. The workflow automatically creates a specialist agent for every enabled MCP server in the configuration.
*   **Current Implementations:**
    *   **KubernetesSpecialist:** Checks Pod logs, events, and resource status.
    *   **CephSpecialist:** Checks OSD status, PG health, and storage capacity.
    *   **GrafanaSpecialist:** Checks dashboards and metrics.
*   **Future Possibilities:** `PostgresSpecialist`, `AwsSpecialist`, `NetworkSpecialist`, etc.

## Step-by-Step Execution

The investigation follows a strict sequence of events as numbered in the architecture diagram:

1.  **Trigger:** The User or AlertManager triggers the workflow by providing a list of firing alerts to the `MultiAlertLeader`.
2.  **Delegate:** The `MultiAlertLeader` analyzes the alert list and delegates each unique alert (or group of highly related alerts) to a `SingleAlertLeader`.
3.  **Ask Router:** The `SingleAlertLeader` begins its investigation by sending the alert description to the `RouterAgent`.
4.  **Plan:** The `RouterAgent` performs a deterministic keyword analysis and returns a list of specialists that MUST be consulted (e.g., "Consult KubernetesSpecialist and CephSpecialist").
5.  **Call Specialist (Loop):** The `SingleAlertLeader` calls the first specialist on the list.
6.  **Return Findings (Loop):** The Specialist performs the investigation using MCP tools and returns its findings to the `SingleAlertLeader`. 
    *Steps 5 and 6 repeat sequentially for every specialist suggested by the Router.*
7.  **Single RCA:** Once all specialists have been consulted, the `SingleAlertLeader` synthesizes the evidence and sends a Root Cause Analysis (RCA) report back to the `MultiAlertLeader`.
8.  **Final Report:** After receiving RCA reports for all alerts, the `MultiAlertLeader` correlates the findings into a final Incident Report and delivers it to the User.

## Design Principles

*   **Deterministic Routing:** We avoid letting the LLM "guess" which expert is relevant. If a keyword exists, the expert is called. This prevents missed investigations.
*   **Shared Context:** By executing sequentially, later specialists can see the findings of earlier ones (passed via the Leader's context), allowing for smarter deductions.
*   **Specialization:** Leaders manage the process; Specialists manage the tools. This separation of concerns reduces hallucination and improves reliability.
