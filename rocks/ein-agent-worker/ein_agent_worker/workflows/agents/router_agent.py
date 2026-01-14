"""Routing agent for specialist selection based on keywords.

This agent acts as a deterministic directory service. It analyzes text and
maps keywords to specific specialist agents using a hard-coded ruleset.
"""

from typing import Dict, Set
from agents import Agent, function_tool

# Mapping of Specialist Agent names to their trigger keywords.
# A keyword can appear in multiple agents' lists.
KEYWORD_MAPPINGS: Dict[str, Set[str]] = {
    "KubernetesSpecialist": {
        "pod", "deployment", "replicaset", "daemonset", "statefulset", 
        "service", "ingress", "configmap", "namespace", "kubelet", 
        "container", "node", "event", "schedule", "pvc", "persistentvolumeclaim" 
    },
    "CephSpecialist": {
        "ceph", "rbd", "pvc", "persistentvolume", "persistentvolumeclaim", 
        "storageclass", "csi", "rook", "objectstore", "block", "filesystem", 
        "osd", "mon", "mgr", "rgw", "mds", "crush", "placement group", "pg"
    },
    "GrafanaSpecialist": {
        "grafana", "dashboard", "datasource", "panel", "loki", 
        "prometheus", "alertmanager", "query", "metric", "log", "trace", 
        "tempo", "mimir", "alerting"
    }
}

ROUTER_INSTRUCTIONS = """You are the Specialist Routing Expert.

Your ONLY job is to analyze the provided text (alert description, investigation findings, etc.) and identifying which Domain Specialists should be consulted.

You have a hard-coded internal mapping of keywords to specialists.

**Instructions:**
1. Read the user's input text carefully.
2. Identify ALL relevant keywords.
3. Return a list of suggested Specialists to consult.
4. Briefly explain WHY each specialist was selected (e.g., "Matched keyword 'rbd'").
5. ALWAYS handoff back to the `SingleAlertLeader` with your recommendations.

**Example Output:**
"Based on the input 'PVC bound to rbd', I recommend:
1. KubernetesSpecialist (baseline)
2. CephSpecialist (matched keyword 'rbd')"
"""

@function_tool
def suggest_specialists_tool(context: str) -> str:
    """Analyze context text and return suggested specialists based on keywords.
    
    Args:
        context: The text to analyze (alert description, logs, etc.)
    """
    context_lower = context.lower()
    suggestions = {} # Map name -> reason
    
    # Always include Kubernetes as baseline for any infrastructure alert
    if "KubernetesSpecialist" not in suggestions:
        suggestions["KubernetesSpecialist"] = "Baseline for infrastructure alerts"
    
    for specialist, keywords in KEYWORD_MAPPINGS.items():
        matched_keywords = []
        for keyword in keywords:
            # Simple substring match. Could be improved with regex word boundaries if needed.
            if keyword in context_lower:
                matched_keywords.append(keyword)
        
        if matched_keywords:
            reason = f"Matched keywords: {', '.join(matched_keywords)}"
            if specialist in suggestions:
                # If already added (e.g. K8s baseline), append reason
                suggestions[specialist] += f"; {reason}"
            else:
                suggestions[specialist] = reason
    
    # Format output
    output = ["Suggested Specialists:"]
    for name, reason in suggestions.items():
        output.append(f"- {name}: {reason}")
        
    return "\n".join(output)

def new_router_agent(model: str) -> Agent:
    """Create a new Router Agent."""
    return Agent(
        name="RouterAgent",
        instructions=ROUTER_INSTRUCTIONS,
        model=model,
        tools=[suggest_specialists_tool]
    )
