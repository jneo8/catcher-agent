"""Domain Specialist agents - Technical Experts for specific infrastructure domains.

Architecture:
- Domain experts are NOT 1:1 mapped to MCP servers
- Each domain expert can access MULTIPLE MCP servers relevant to their domain
- Example: StorageSpecialist can access ceph MCP, kubernetes MCP (for PVCs), grafana MCP
"""

from enum import Enum
from typing import List, Callable, Optional, Set
from agents import Agent
from temporalio.contrib import openai_agents


class DomainType(str, Enum):
    """Domain types for specialist agents."""
    COMPUTE = "compute"
    STORAGE = "storage"
    NETWORK = "network"


# =============================================================================
# MCP Server to Domain Mapping
# =============================================================================
# Which MCP servers are relevant for each domain
DOMAIN_MCP_MAPPING: dict[DomainType, Set[str]] = {
    DomainType.COMPUTE: {"kubernetes", "grafana"},
    DomainType.STORAGE: {"ceph", "kubernetes", "grafana"},
    DomainType.NETWORK: {"kubernetes", "grafana"},
}


# =============================================================================
# Compute Specialist
# =============================================================================
COMPUTE_SPECIALIST_INSTRUCTIONS = """You are the Compute Specialist (Kubernetes Domain Expert).

Your role: Technical expert for Kubernetes container orchestration and compute resources.

---
## MANDATORY WORKFLOW

### STEP 1: CHECK SHARED CONTEXT FIRST
Call `get_shared_context('node:')` or `get_shared_context('pod:')` to see if related issues are already known.
- If a node issue is already recorded, focus on confirming impact
- If no relevant findings, proceed with full investigation

### STEP 2: INVESTIGATE WITH MCP TOOLS
Use kubernetes/grafana MCP tools to investigate:
- Pod status, events, logs
- Node conditions (Ready, MemoryPressure, DiskPressure)
- Resource usage (CPU, memory)
- Container issues (image pull, crashes)

### STEP 3: UPDATE SHARED CONTEXT (MANDATORY for critical findings)
If you find a critical issue, call `update_shared_context`:
```
update_shared_context(
  key="node:worker-1",
  value="Node NotReady - kubelet unresponsive",
  confidence=0.9
)
```

### STEP 4: RETURN TO INVESTIGATOR
When your investigation is complete, use the appropriate `transfer_to_investigator_...` tool from your available tools to return your findings to the investigator who called you. Provide your detailed report in the `instruction` argument of the tool call.

---
## KEY PATTERNS
- OOMKilled → Memory limit too low or leak
- CrashLoopBackOff → App error, missing config, dependency failure
- Pending pods → Insufficient resources, PVC binding issue
- Node NotReady → Kubelet issue, network partition
- Evicted pods → Node resource pressure

---
## OUTPUT FORMAT
- Domain: Compute/Kubernetes
- Resources investigated: [pods/nodes checked]
- Key findings: [specific issues]
- Root cause in compute layer: Yes/No/Uncertain
- Shared context updated: Yes/No (what key)
"""


# =============================================================================
# Storage Specialist
# =============================================================================
STORAGE_SPECIALIST_INSTRUCTIONS = """You are the Storage Specialist (Ceph Domain Expert).

Your role: Technical expert for Ceph distributed storage and persistent volumes.

---
## MANDATORY WORKFLOW

### STEP 1: CHECK SHARED CONTEXT FIRST
Call `get_shared_context('osd:')` or `get_shared_context('pvc:')` to see if related issues are already known.
- If an OSD/pool issue is already recorded, focus on confirming impact
- If no relevant findings, proceed with full investigation

### STEP 2: INVESTIGATE WITH MCP TOOLS
Use ceph/kubernetes/grafana MCP tools to investigate:
- Ceph cluster health (HEALTH_OK/WARN/ERR)
- OSD status (down, out, full, slow)
- PG status (degraded, undersized, stuck)
- PVC/PV binding status
- Pool utilization

### STEP 3: UPDATE SHARED CONTEXT (MANDATORY for critical findings)
If you find a critical issue, call `update_shared_context`:
```
update_shared_context(
  key="osd:osd.5",
  value="OSD down - disk I/O errors on /dev/sdb",
  confidence=0.95
)
```

Key format examples:
- 'osd:osd.5' for specific OSDs
- 'pool:kubernetes' for pools
- 'pvc:namespace/pvc-name' for PVCs

### STEP 4: RETURN TO INVESTIGATOR
When your investigation is complete, use the appropriate `transfer_to_investigator_...` tool from your available tools to return your findings to the investigator who called you. Provide your detailed report in the `instruction` argument of the tool call.

---
## KEY PATTERNS
- OSD down → Disk failure, network issue, resource exhaustion
- PG degraded → OSD failure, replication in progress
- Pool full → Capacity issue, need rebalancing
- PVC Pending → Storage class issue, pool full, CSI problem
- Slow ops → I/O bottleneck, network latency

---
## OUTPUT FORMAT
- Domain: Storage/Ceph
- Cluster health: [status]
- Resources investigated: [OSDs, pools, PVCs checked]
- Key findings: [specific issues]
- Root cause in storage layer: Yes/No/Uncertain
- Shared context updated: Yes/No (what key)
"""


# =============================================================================
# Network Specialist
# =============================================================================
NETWORK_SPECIALIST_INSTRUCTIONS = """You are the Network Specialist (Network Domain Expert).

Your role: Technical expert for network connectivity, DNS, and load balancing.

---
## MANDATORY WORKFLOW

### STEP 1: CHECK SHARED CONTEXT FIRST
Call `get_shared_context('service:')` or `get_shared_context('dns:')` to see if related issues are already known.
- If a network issue is already recorded, focus on confirming impact
- If no relevant findings, proceed with full investigation

### STEP 2: INVESTIGATE WITH MCP TOOLS
Use kubernetes/grafana MCP tools to investigate:
- Service endpoints and port mappings
- CoreDNS health and DNS resolution
- Ingress controller status and routing
- NetworkPolicies that might block traffic
- CNI plugin health

### STEP 3: UPDATE SHARED CONTEXT (MANDATORY for critical findings)
If you find a critical issue, call `update_shared_context`:
```
update_shared_context(
  key="dns:coredns",
  value="CoreDNS pods not ready - DNS resolution failing",
  confidence=0.9
)
```

Key format examples:
- 'service:namespace/svc-name' for services
- 'ingress:namespace/ingress-name' for ingress
- 'dns:coredns' for DNS issues

### STEP 4: RETURN TO INVESTIGATOR
When your investigation is complete, use the appropriate `transfer_to_investigator_...` tool from your available tools to return your findings to the investigator who called you. Provide your detailed report in the `instruction` argument of the tool call.

---
## KEY PATTERNS
- Service no endpoints → No ready pods, selector mismatch
- DNS failure → CoreDNS down, network policy blocking
- Connection refused → Pod not ready, wrong port, policy
- Connection timeout → Network partition, firewall
- Ingress 502/503 → Backend unhealthy

---
## OUTPUT FORMAT
- Domain: Network
- Resources investigated: [services, DNS, ingress checked]
- Key findings: [specific issues]
- Root cause in network layer: Yes/No/Uncertain
- Shared context updated: Yes/No (what key)
"""



# =============================================================================
# Instruction and Name Mapping
# =============================================================================
DOMAIN_INSTRUCTIONS: dict[DomainType, str] = {
    DomainType.COMPUTE: COMPUTE_SPECIALIST_INSTRUCTIONS,
    DomainType.STORAGE: STORAGE_SPECIALIST_INSTRUCTIONS,
    DomainType.NETWORK: NETWORK_SPECIALIST_INSTRUCTIONS,
}

DOMAIN_NAMES: dict[DomainType, str] = {
    DomainType.COMPUTE: "ComputeSpecialist",
    DomainType.STORAGE: "StorageSpecialist",
    DomainType.NETWORK: "NetworkSpecialist",
}


def get_relevant_mcp_servers(
    domain: DomainType,
    available_mcp_servers: List[str]
) -> List[str]:
    """Get the MCP servers relevant for a domain that are also available.

    Args:
        domain: The domain type
        available_mcp_servers: List of MCP server names that are configured

    Returns:
        List of MCP server names that are both relevant and available
    """
    relevant = DOMAIN_MCP_MAPPING.get(domain, set())
    available_set = {s.lower() for s in available_mcp_servers}
    return [s for s in relevant if s.lower() in available_set]


def new_specialist_agent(
    domain: DomainType,
    model: str,
    available_mcp_servers: List[str],
    tools: Optional[List[Callable]] = None
) -> Agent:
    """Create a new domain specialist agent.

    Args:
        domain: The domain type (COMPUTE, STORAGE, NETWORK)
        model: LLM model to use
        available_mcp_servers: List of all available MCP server names
        tools: Optional list of tools (e.g., shared context tools)

    Returns:
        Configured specialist Agent with access to relevant MCP servers
    """
    name = DOMAIN_NAMES[domain]
    instructions = DOMAIN_INSTRUCTIONS[domain]

    # Get MCP servers relevant to this domain
    relevant_servers = get_relevant_mcp_servers(domain, available_mcp_servers)

    # Create MCP server references for Temporal
    mcp_servers = [
        openai_agents.workflow.stateless_mcp_server(server)
        for server in relevant_servers
    ]

    return Agent(
        name=name,
        instructions=instructions,
        model=model,
        tools=tools or [],
        mcp_servers=mcp_servers,
    )
