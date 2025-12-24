# Purpose

An interactive CLI for incident investigation with RCA workflows. Users work within a single CLI session, using slash commands to manage a local context that stores alerts, workflow outputs, and investigation history.

## How It Works

1. User starts the CLI: `ein-agent-cli human-in-loop`
2. Inside the session, user types slash commands (e.g., `/import-alerts`)
3. Each slash command opens an **interactive GUI** with menus, tables, and prompts
4. All filtering, selecting, and actions happen within the interactive interface
5. Context is automatically saved to `~/.ein-agent/investigations/`

## Slash Commands

### Basic

#### `/help`
Display all available slash commands with descriptions.

**Interactive Flow:**
```
You: /help

Available Commands
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
/help                     - Show this help message
/import-alerts           - Import alerts from AlertManager
/import-workflow         - Import Temporal workflows
/alerts                  - Manage alerts in context
/workflows               - Manage workflows in context
/context                 - Show context summary
...
```

### Import Context

#### `/import-alerts`
Interactive alert import from AlertManager.

**Interactive Flow:**
```
You: /import-alerts

Enter AlertManager URL [http://localhost:9093]: http://alertmanager:9093
Querying AlertManager...
OK Found 35 alerts

Alerts in Local Context (3 alerts already imported)
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Alert Name          ┃ Status ┃ Severity ┃ Fingerprint┃
┣━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━━━┫
┃ KubePodCrashLoop... ┃ firing ┃ critical ┃ abc123...  ┃
┃ HighMemoryUsage     ┃ firing ┃ warning  ┃ def456...  ┃
┃ DiskSpaceLow        ┃ firing ┃ warning  ┃ ghi789...  ┃
┗━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━━━━━┛

New Alerts from AlertManager (32 new)
┏━━━┳━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┓
┃   ┃ # ┃ Alert Name          ┃ Status ┃ Severity ┃ Fingerprint┃
┣━━━╋━━━╋━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━━━┫
┃   ┃ 1 ┃ KubePodNotReady     ┃ firing ┃ critical ┃ jkl012...  ┃
┃ x ┃ 2 ┃ NodeNotReady        ┃ firing ┃ critical ┃ mno345...  ┃
┃   ┃ 3 ┃ APIServerDown       ┃ firing ┃ critical ┃ pqr678...  ┃
┃ x ┃ 4 ┃ EtcdDown            ┃ firing ┃ critical ┃ stu901...  ┃
┃   ┃ 5 ┃ PVCPending          ┃ firing ┃ warning  ┃ vwx234...  ┃
┃   ┃...┃ ...                 ┃ ...    ┃ ...      ┃ ...        ┃
┗━━━┻━━━┻━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━━━━━┛

Actions: (s)elect, (i)mport selected, (a)ll, (f)ilter, (c)lear filter, (q)uit
Action: f
Enter filters (e.g., name=KubePod status=firing severity=critical):
Filters: status=firing severity=critical
Applying filters...

New Alerts from AlertManager (8 matching filters)
┏━━━┳━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┓
┃   ┃ # ┃ Alert Name          ┃ Status ┃ Severity ┃ Fingerprint┃
┣━━━╋━━━╋━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━━━┫
┃   ┃ 1 ┃ KubePodNotReady     ┃ firing ┃ critical ┃ jkl012...  ┃
┃   ┃ 2 ┃ NodeNotReady        ┃ firing ┃ critical ┃ mno345...  ┃
┃   ┃ 3 ┃ APIServerDown       ┃ firing ┃ critical ┃ pqr678...  ┃
┃   ┃ 4 ┃ EtcdDown            ┃ firing ┃ critical ┃ stu901...  ┃
┗━━━┻━━━┻━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━━━━━┛

Actions: (s)elect, (i)mport selected, (a)ll, (f)ilter, (c)lear filter, (q)uit
Action: s 1,2,4
Selected: #1, #2, #4

Actions: (s)elect, (i)mport selected, (a)ll, (f)ilter, (c)lear filter, (q)uit
Action: i
OK Imported 3 alert(s) to local context
Total alerts in local context: 6
```

**Features:**
- Shows alerts already in context (separate table)
- Filters out duplicates automatically
- Interactive filtering (f)
- Multi-select with ranges: `s 1,2,5-7`
- Import selected (i) or all (a)
- Toggle selection by typing same numbers again
- Press (q) to quit without importing

#### `/import-workflow`
Interactive workflow import from Temporal.

**Interactive Flow:**
```
You: /import-workflow

Querying Temporal workflows...
OK Found 45 workflows

Filter Options:
  [1] All workflows
  [2] Running only
  [3] Completed only
  [4] Failed only
  [5] By workflow type
  [6] By time range
Select filter [1]: 3

Workflows (25 completed)
┏━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ # ┃ Workflow ID            ┃ Type          ┃ Status   ┃ Completed  ┃
┣━━━╋━━━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━━━┫
┃ 1 ┃ rca-alert-20250624...  ┃ RCA           ┃ Completed┃ 10 min ago ┃
┃ 2 ┃ rca-alert-20250624...  ┃ RCA           ┃ Completed┃ 15 min ago ┃
┃ 3 ┃ enrich-rca-20250624... ┃ EnrichmentRCA ┃ Completed┃ 5 min ago  ┃
┗━━━┻━━━━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━━━━━┛

Select workflows to import (comma-separated, ranges ok): 1-3
OK Imported 3 workflow(s) to local context
OK Linked workflows to associated alerts
```

### Context Management

#### `/new`
Create a new workflow and start conversation.

**Interactive Flow:**
```
You: /new

What would you like the agent to help you with?
Task: Investigate high memory usage in production

OK Creating new workflow...
OK Workflow started: human-in-loop-20250624-143022
Now on workflow: human-in-loop-20250624-143022

Agent is now working on your task...
```

#### `/context`
Show local context summary.

**Interactive Flow:**
```
You: /context

Local Context Summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Alerts:               6 (4 firing, 2 resolved)
Workflows:            8 total
  - RCA:              5 (3 completed, 2 running)
  - EnrichmentRCA:    3 (all completed)
Compact Outputs:      1 (CompactRCA)

Last Updated:         2025-06-24 15:45:10
```

#### `/alerts`
Manage alerts in local context **(ALREADY IMPLEMENTED)**.

**Interactive Flow:**
```
You: /alerts

Local Context Alerts (6 total)
┏━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ # ┃ Alert Name          ┃ Status ┃ Severity ┃ Imported At        ┃ Fingerprint┃
┣━━━╋━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━┫
┃ 1 ┃ KubePodCrashLoop... ┃ firing ┃ critical ┃ 2025-06-24 14:30..┃ abc123...  ┃
┃ 2 ┃ NodeNotReady        ┃ firing ┃ critical ┃ 2025-06-24 14:31..┃ def456...  ┃
┃ 3 ┃ HighMemoryUsage     ┃ firing ┃ warning  ┃ 2025-06-24 14:32..┃ ghi789...  ┃
┗━━━┻━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━┛

Select an alert by number or fingerprint (or 'q' to quit):
Select alert: 1

Alert Actions:
  [1] View Details
  [2] Remove from context
  [3] Start RCA workflow
  [4] Back to alert list
Select action: 3

Task: Perform RCA for this alert

Alert details:
{
  "alertname": "KubePodCrashLooping",
  "status": "firing",
  ...
}

OK Started RCA workflow: human-in-loop-20250624-160245
```

**Features (already working):**
- Tab-completion on fingerprints
- View full alert details (JSON)
- Remove alert from context
- Start RCA workflow with pre-filled prompt

#### `/workflows`
Manage workflows in local context (ALREADY IMPLEMENTED - needs enhancement).

**Interactive Flow:**
```
You: /workflows

Workflows in Local Context (15 total)
┏━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ # ┃ Workflow ID         ┃ Type                ┃ Alert        ┃ Status    ┃
┣━━━╋━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━╋━━━━━━━━━━━┫
┃ 1 ┃ rca-abc123-001      ┃ RCA                 ┃ KubePodCr... ┃ completed ┃
┃ 2 ┃ rca-def456-001      ┃ RCA                 ┃ NodeNotRe... ┃ running   ┃
┃ 3 ┃ enrich-abc123-001   ┃ EnrichmentRCA       ┃ KubePodCr... ┃ completed ┃
┃ 4 ┃ enrich-def456-001   ┃ EnrichmentRCA       ┃ NodeNotRe... ┃ running   ┃
┃ 5 ┃ compact-enrich-001  ┃ CompactEnrichmentRCA┃ -            ┃ completed ┃
┗━━━┻━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━┻━━━━━━━━━━━┛

Actions: (s)elect, (f)ilter, (c)lear filter, (q)uit
Action: f
Enter filters (e.g., type=RCA status=completed):
Filters: type=RCA status=completed
Applying filters...

Workflows in Local Context (5 matching filters)
┏━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ # ┃ Workflow ID         ┃ Type                ┃ Alert        ┃ Status    ┃
┣━━━╋━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━╋━━━━━━━━━━━┫
┃ 1 ┃ rca-abc123-001      ┃ RCA                 ┃ KubePodCr... ┃ completed ┃
┃ 2 ┃ rca-def456-001      ┃ RCA                 ┃ NodeNotRe... ┃ completed ┃
┃ 3 ┃ rca-ghi789-001      ┃ RCA                 ┃ HighMemor... ┃ completed ┃
┗━━━┻━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━┻━━━━━━━━━━━┛

Actions: (s)elect, (f)ilter, (c)lear filter, (q)uit
Action: s
Select workflow by number or ID: 1

Workflow Details:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Workflow ID:       rca-abc123-001
Type:              RCA
Alert:             KubePodCrashLooping (abc123def456)
Status:            completed

Result:
{
  "findings": [
    "Pod is OOMKilled repeatedly",
    "Memory limit set to 128Mi",
    "Application requires 256Mi"
  ],
  "root_cause": "Memory limit too low for application requirements",
  "remediation": "Increase memory limit to 256Mi in deployment spec"
}

Workflow Actions:
  [1] View full result (formatted JSON)
  [2] Start enrichment RCA workflow (requires compact RCA)
  [3] Remove workflow from context
  [4] Back to workflow list
Select action [4]: 2

Checking requirements...
ERROR Compact RCA not found in context

You need to:
  1. Run /compact-rca to create compact RCA from all RCA workflows
  2. Wait for compact workflow to complete
  3. Then retry starting enrichment RCA

Go back to workflow list? [y/n]: y

---

(If compact RCA exists:)

Workflow Actions:
  [1] View full result (formatted JSON)
  [2] Start enrichment RCA workflow (requires compact RCA)
  [3] Remove workflow from context
  [4] Back to workflow list
Select action [4]: 2

Checking requirements...
OK Found compact RCA: compact-rca-001 (completed)

Starting enrichment RCA for alert: KubePodCrashLooping (abc123def456)

Preparing enrichment context...
- Alert: KubePodCrashLooping (abc123def456)
- Compact RCA output: compact-rca-001
- Source RCA workflows: 5 RCAs

Task: Perform enrichment RCA for this alert using compact RCA context

Alert details:
{
  "alertname": "KubePodCrashLooping",
  ...
}

Enrichment context (from compact RCA):
{
  "compact_rca_id": "compact-rca-001",
  "compact_summary": "Memory pressure across cluster...",
  "source_workflows": ["rca-abc123-001", "rca-def456-001", ...]
}

OK Started enrichment RCA workflow: enrich-abc123-001
```

**Features:**
- Display all workflows from local context (RCA, Enrichment RCA, Compact, etc.)
- Interactive filtering (f) by type, status, alert
- Select workflow (s) to view details
- View workflow result if completed
- **For RCA workflows:** Start enrichment RCA with context
- **For Enrichment RCA workflows:** View enrichment context used
- Actions: view result, start enrichment RCA (if RCA type), remove, back

### Start Workflows (Future Commands)

#### `/start-rca-workflows`
Batch start RCA workflows for all alerts.

**Interactive Flow:**
```
You: /start-rca-workflows

Found 6 alerts in context
3 already have RCA workflows

Start RCA workflows for 3 remaining alerts?
  [1] Yes, start all
  [2] Let me select
  [3] Cancel
Select [1]: 1

Max parallel workflows [5]: 3

Starting RCA workflows...
OK Started human-in-loop-rca-20250624-160301 for alert abc123... (1/3)
OK Started human-in-loop-rca-20250624-160302 for alert def456... (2/3)
OK Started human-in-loop-rca-20250624-160303 for alert ghi789... (3/3)

All workflows started. Use /workflows to monitor progress.
```

#### `/compact-rca`
Compact all completed RCA workflows into summary.

**Interactive Flow:**
```
You: /compact-rca

Checking RCA workflows...
Found 5 completed RCA workflows:
- rca-abc123-001 (KubePodCrashLooping)
- rca-def456-001 (NodeNotReady)
- rca-ghi789-001 (HighMemoryUsage)
- rca-jkl012-001 (DiskSpaceLow)
- rca-mno345-001 (APIServerDown)

Create compact RCA from 5 workflows? [y/n]: y

Starting compact RCA workflow...
OK Workflow started: compact-rca-001

This workflow will:
- Analyze all 5 RCA outputs
- Identify common patterns
- Create compact summary
- Store result in local context

Use /workflows to monitor progress.
Once completed, you can run /start-enrichment-rca-workflows
```

#### `/compact-enrichment-rca`
Compact all completed enrichment RCA workflows into summary.

**Interactive Flow:**
```
You: /compact-enrichment-rca

Checking enrichment RCA workflows...
Found 5 completed enrichment RCA workflows:
- enrich-abc123-001 (KubePodCrashLooping)
- enrich-def456-001 (NodeNotReady)
- enrich-ghi789-001 (HighMemoryUsage)
- enrich-jkl012-001 (DiskSpaceLow)
- enrich-mno345-001 (APIServerDown)

Create compact enrichment RCA from 5 workflows? [y/n]: y

Starting compact enrichment RCA workflow...
OK Workflow started: compact-enrich-001

This workflow will:
- Analyze all 5 enrichment RCA outputs
- Identify correlations and patterns
- Create compact enriched summary
- Store result in local context

Use /workflows to monitor progress.
Once completed, you can run /start-incident-summary
```

#### `/start-enrichment-rca-workflows`
Batch start enrichment RCA workflows (requires compact RCA).

**Interactive Flow:**
```
You: /start-enrichment-rca-workflows

Checking requirements...
ERROR Compact RCA not found in context

You need to:
  1. Run /compact-rca to create compact RCA from all RCA workflows
  2. Wait for compact workflow to complete
  3. Then retry /start-enrichment-rca-workflows

---

(If compact RCA exists:)

You: /start-enrichment-rca-workflows

Checking requirements...
OK Found compact RCA: compact-rca-001 (completed)

Found 6 alerts in context with completed RCA workflows
3 already have enrichment RCA workflows

Start enrichment RCA for 3 remaining alerts? [y/n]: y

Starting enrichment RCA workflows with compact RCA context...
OK Started enrich-abc123-001 for alert KubePodCrashLooping (1/3)
OK Started enrich-def456-001 for alert NodeNotReady (2/3)
OK Started enrich-ghi789-001 for alert HighMemoryUsage (3/3)

All workflows started with compact RCA: compact-rca-001
```

#### `/start-incident-summary`
Generate final incident report (requires compact enrichment RCA).

**Interactive Flow:**
```
You: /start-incident-summary

Checking requirements...
ERROR Compact enrichment RCA not found in context

You need to:
  1. Run /compact-enrichment-rca to create compact from enrichment RCAs
  2. Wait for compact workflow to complete
  3. Then retry /start-incident-summary

---

(If compact enrichment RCA exists:)

You: /start-incident-summary

Checking requirements...
OK Found compact enrichment RCA: compact-enrich-001 (completed)

Preparing incident summary context...
- Compact enrichment RCA: compact-enrich-001
- Source enrichment RCAs: 5 workflows
- Alerts in context: 5 alerts

Starting incident summary workflow...
OK Workflow started: incident-summary-001

The workflow will generate final incident report using:
- Compact enrichment RCA analysis
- All alert details
- Timeline and correlation findings
```

### Workflow Management (Existing Commands)

#### `/switch`
Switch between running workflows **(ALREADY IMPLEMENTED)**.

#### `/complete`
Complete current workflow without exiting CLI **(ALREADY IMPLEMENTED)**.

#### `/refresh`
Get latest workflow status **(ALREADY IMPLEMENTED)**.

#### `/end`
Exit the CLI **(ALREADY IMPLEMENTED)**.

## Strategy

### Workflow Types

**5 Workflow Types:**

1. **RCA Workflow** - Root cause analysis for single alert
   - Input: Single alert data
   - Output: RCA findings, root cause, remediation
   - Chattable: Yes (human-in-the-loop)

2. **Enrichment RCA Workflow** - RCA with context from other alerts/workflows
   - Input: Alert + other alerts + RCA outputs from context
   - Output: Enriched RCA with correlation analysis
   - Chattable: Yes (human-in-the-loop)

3. **Compact RCA Workflow** - Summarize multiple RCA outputs
   - Input: List of RCA workflow outputs
   - Output: Compact summary of all RCAs
   - Chattable: No (automated summarization)

4. **Compact Enrichment RCA Workflow** - Summarize enrichment RCA outputs
   - Input: List of enrichment RCA outputs
   - Output: Compact enriched summary
   - Chattable: No (automated summarization)

5. **Incident Summary Workflow** - Final incident report
   - Input: Compact enrichment RCA + all alert data
   - Output: Complete incident report with timeline, impact, resolution
   - Chattable: Yes (human-in-the-loop for final review)

**Workflow Pipeline:**
```
Alerts (n)
  ├─> RCA Workflows (n) ────────> Compact RCA (1)
  │
  └─> Enrichment RCA Workflows (n)
      (using context: other alerts + RCA outputs)
        │
        └─> Compact Enrichment RCA (1)
              │
              └─> Incident Summary (1)
```

### Context Data Storage

**Structure:**
- Location: `~/.ein-agent/context/session-state.json`
- Single file stores all context data
- Auto-saved after each modification
- Format: JSON

**Context Contains:**

1. **Alerts** (fingerprint → alert data)
   - Alert details from AlertManager

2. **RCA Workflows** (workflow_id → metadata + result)
   - Which alert it's for (`alert_fingerprint`)
   - Workflow status
   - Workflow result (findings, root cause, remediation)

3. **Enrichment RCA Workflows** (workflow_id → metadata + result)
   - Which alert it's for (`alert_fingerprint`)
   - What context was included (`enrichment_context`)
   - Workflow status
   - Workflow result (correlation analysis, combined findings)

4. **Compact RCA** (optional, single entry)
   - Which RCA workflows were compacted (`source_workflow_ids`)
   - Workflow status
   - Workflow result (compact summary)

5. **Compact Enrichment RCA** (optional, single entry)
   - Which Enrichment RCA workflows were compacted (`source_workflow_ids`)
   - Workflow status
   - Workflow result (enriched compact summary)

6. **Incident Summary** (optional, single entry)
   - Final incident report workflow
   - Workflow status
   - Workflow result (final incident report)

**Relationships:**
- 1 Local Context → N Alerts
- 1 Alert → 0-1 RCA Workflow
- 1 Alert → 0-1 Enrichment RCA Workflow
- N RCA Workflows → 0-1 Compact RCA Workflow
- N Enrichment RCA Workflows → 0-1 Compact Enrichment RCA
- 1 Compact Enrichment RCA → 0-1 Incident Summary

**Key Design:**
- Workflow results stored in local context
- Results available for use in subsequent workflows (e.g., enrichment RCA uses RCA results)
- No need to query Temporal for completed workflow outputs

### Context Management

**User Actions:**

1. **Via `/alerts` command:**
   - View all alerts in interactive table
   - View detailed alert JSON
   - Remove alert from context
   - Start RCA workflow for alert (creates new human-in-loop workflow)

2. **Via `/workflows` command:**
   - View running/completed workflows
   - Filter by status (Running/Completed/Failed)
   - Monitor workflow progress

3. **Via `/context` command:**
   - View summary of all context data
   - See counts of alerts and workflows

## Complete End-to-End Flow

### Investigation Flow Example

```
$ ein-agent-cli human-in-loop

You: /import-alerts

Enter AlertManager URL [http://localhost:9093]:
Querying AlertManager...
OK Found 15 alerts

[Interactive alert table shown]
Actions: (s)elect, (i)mport selected, (a)ll, (f)ilter, (c)lear filter, (q)uit
Action: f
Filters: status=firing severity=critical
Applying filters...
[Filtered to 5 critical alerts]
Action: a
OK Imported 5 alert(s) to local context

You: /alerts

[Alert table shown]
Select alert: 1

Alert Actions:
  [1] View Details
  [2] Remove from context
  [3] Start RCA workflow
Select action: 3

OK Started RCA workflow: human-in-loop-20250624-160245

Agent: I've started investigating the KubePodCrashLooping alert...
Agent: Let me check the pod logs using the kubernetes MCP server...
Agent: I found that the pod is failing due to OOMKilled...

[Interactive conversation continues...]

You: The memory limit is set to 128Mi but the app needs 256Mi

Agent: Thank you. I'll include that in the RCA report...
Agent: Here's my complete analysis:
[Shows RCA findings]

You: /complete
OK RCA workflow completed
OK Output saved to Temporal workflow result

You: /alerts

[Shows updated alert table]
Select alert: 2

Select action: 3
OK Started RCA workflow: human-in-loop-20250624-160530

[Repeat for all 5 alerts...]

You: /start-enrichment-rca-workflows

Found 5 alerts in context
5 have completed RCA workflows

Include enrichment context:
  [1] Other alerts only
  [2] RCA outputs only
  [3] All context (alerts + RCA outputs)
Select [3]: 3

OK Started enrichment-rca-20250624-160601 for alert abc123... (1/5)
...

[Each enrichment RCA is chattable, agent correlates findings]

You: /start-incident-summary

Checking requirements...
OK Found 5 enrichment RCA outputs

Running compact-enrichment-rca first...
OK Compact completed in 30s

Starting incident summary workflow...
OK Workflow started: incident-summary-20250624-170000

Agent: I've analyzed all the enriched RCA outputs...
Agent: The root cause appears to be a memory leak in version 2.3.1...
[Interactive discussion to refine final report]

You: /complete
OK Incident summary completed

Final report saved to Temporal workflow result.
```

## Data Models

### LocalContext (SessionState)

**SessionState (updated):**
```python
class SessionState(BaseModel):
    """State for managing workflow session."""

    current_workflow_id: Optional[str] = Field(
        default=None,
        description="Currently active workflow ID"
    )
    local_context: LocalContext = Field(
        default_factory=LocalContext,
        description="Local investigation context"
    )
```

**Enhanced LocalContext structure:**
```python
class WorkflowMetadata(BaseModel):
    """Metadata for workflows tracked in local context."""
    workflow_id: str
    alert_fingerprint: Optional[str] = None  # Which alert this is for
    status: str  # pending/running/completed/failed
    result: Optional[Dict[str, Any]] = None  # Workflow result/output


class EnrichmentRCAMetadata(WorkflowMetadata):
    """Enrichment RCA with context info."""
    enrichment_context: Dict[str, Any] = Field(default_factory=dict)


class CompactMetadata(BaseModel):
    """Compact workflow metadata."""
    workflow_id: str
    source_workflow_ids: List[str]  # Which workflows were compacted
    status: str
    result: Optional[Dict[str, Any]] = None  # Compact result/output


class LocalContext(BaseModel):
    """Local context store for investigation data."""

    # Alerts
    items: Dict[str, ContextItem] = Field(
        default_factory=dict,
        description="Alerts indexed by fingerprint"
    )

    # RCA Workflows (separate)
    rca_workflows: Dict[str, WorkflowMetadata] = Field(
        default_factory=dict,
        description="RCA workflows indexed by workflow_id"
    )

    # Enrichment RCA Workflows (separate)
    enrichment_rca_workflows: Dict[str, EnrichmentRCAMetadata] = Field(
        default_factory=dict,
        description="Enrichment RCA workflows indexed by workflow_id"
    )

    # Compact workflows (single entries)
    compact_rca: Optional[CompactMetadata] = None
    compact_enrichment_rca: Optional[CompactMetadata] = None
    incident_summary: Optional[WorkflowMetadata] = None

    # Methods:
    # - add_item(item: ContextItem)  # Add alert
    # - remove_item(item_id: str) -> bool  # Remove alert
    # - get_alerts() -> List[Dict[str, Any]]
    # - add_rca_workflow(workflow: WorkflowMetadata)
    # - get_rca_for_alert(fingerprint: str) -> Optional[WorkflowMetadata]
    # - get_alerts_without_rca() -> List[str]  # Fingerprints
    # - add_enrichment_rca(workflow: EnrichmentRCAMetadata)
```

**ContextItem (simplified):**
```python
class ContextItem(BaseModel):
    """A single item in the local context."""
    item_id: str  # Alert fingerprint
    item_type: ContextItemType  # ALERT
    data: Dict[str, Any]  # Alert data
```

## Implementation Status

###  Implemented Commands
- `/help` - Show available commands
- `/new` - Create new workflow
- `/switch` - Switch between workflows
- `/workflows` - List workflows (with status filter)
- `/alerts` - Manage alerts (import, view, remove, start RCA)
- `/import-alerts` - Interactive alert import
- `/complete` - Complete current workflow
- `/refresh` - Refresh workflow status
- `/end` - Exit CLI

###  To Implement
- `/context` - Show context summary
- `/import-workflow` - Import workflow results to context
- `/start-rca-workflows` - Batch start RCA for all alerts
- `/start-enrichment-rca-workflows` - Batch start enrichment RCA
- `/compact-rca` - Compact RCA outputs
- `/compact-enrichment-rca` - Compact enrichment RCA outputs
- `/start-incident-summary` - Generate final incident report

## File Storage

```
~/.ein-agent/
└── context/
    └── session-state.json    # Current session state
```

**session-state.json structure:**
```json
{
  "current_workflow_id": "human-in-loop-20250624-143022",
  "local_context": {
    "items": {
      "abc123def456": {
        "item_id": "abc123def456",
        "item_type": "alert",
        "data": {
          "alertname": "KubePodCrashLooping",
          "status": "firing",
          "severity": "critical",
          "labels": {...},
          "annotations": {...},
          "fingerprint": "abc123def456"
        }
      },
      "def456ghi789": {
        "item_id": "def456ghi789",
        "item_type": "alert",
        "data": {
          "alertname": "NodeNotReady",
          "status": "firing",
          "severity": "critical",
          "labels": {...},
          "annotations": {...},
          "fingerprint": "def456ghi789"
        }
      }
    },
    "rca_workflows": {
      "rca-abc123-001": {
        "workflow_id": "rca-abc123-001",
        "alert_fingerprint": "abc123def456",
        "status": "completed",
        "result": {
          "findings": [
            "Pod is OOMKilled repeatedly",
            "Memory limit set to 128Mi",
            "Application requires 256Mi"
          ],
          "root_cause": "Memory limit too low for application requirements",
          "remediation": "Increase memory limit to 256Mi in deployment spec"
        }
      },
      "rca-def456-001": {
        "workflow_id": "rca-def456-001",
        "alert_fingerprint": "def456ghi789",
        "status": "running",
        "result": null
      }
    },
    "enrichment_rca_workflows": {
      "enrich-abc123-001": {
        "workflow_id": "enrich-abc123-001",
        "alert_fingerprint": "abc123def456",
        "status": "completed",
        "enrichment_context": {
          "other_alerts": ["def456ghi789"],
          "rca_outputs": ["rca-abc123-001"]
        },
        "result": {
          "correlation": "Pod crashes caused by node memory pressure",
          "combined_findings": [...],
          "recommended_actions": [...]
        }
      }
    },
    "compact_rca": null,
    "compact_enrichment_rca": {
      "workflow_id": "compact-enrich-001",
      "source_workflow_ids": ["enrich-abc123-001"],
      "status": "completed",
      "result": {
        "summary": "Memory pressure across cluster",
        "key_findings": [...],
        "recommendations": [...]
      }
    },
    "incident_summary": {
      "workflow_id": "incident-summary-001",
      "alert_fingerprint": null,
      "status": "running",
      "result": null
    }
  }
}
```

**Key features:**
-  No `connected_workflows` (removed)
-  **Workflow results** stored in `result` field
  - `null` when workflow is pending/running
  - Contains actual output when completed
- **Alerts** in `items` (fingerprint → alert data)
- **RCA workflows** in `rca_workflows` (workflow_id → metadata + result)
  - Each RCA linked to alert via `alert_fingerprint`
- **Enrichment RCA** in `enrichment_rca_workflows` (workflow_id → metadata + result)
  - Includes `enrichment_context` showing which alerts/RCAs were used
- **Compact workflows** as single entries (nullable) with results
- Easy to use results from completed workflows in subsequent workflows
