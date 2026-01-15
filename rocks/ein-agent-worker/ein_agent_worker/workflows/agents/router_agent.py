"""Routing agent for specialist selection based on keywords.

This agent acts as a deterministic directory service. It analyzes text and
maps keywords to specific specialist agents using a hard-coded ruleset.
"""

from typing import Dict, Set, List
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

def new_router_agent(model: str, available_specialists: List[str]) -> Agent:
    """Create a new Router Agent with awareness of available specialists.
    
    Args:
        model: The LLM model to use.
        available_specialists: List of names of registered specialist agents.
    """
    
    # Normalize available specialists for case-insensitive matching
    available_set = {s.lower() for s in available_specialists}

    @function_tool
    def suggest_specialists_tool(context: str) -> str:
        """Analyze context text and return suggested specialists based on keywords.
        
        Args:
            context: The text to analyze (alert description, logs, etc.)
        """
        context_lower = context.lower()
        suggestions = {} # Map name -> reason
        
        # Always include Kubernetes as baseline IF it is available
        if "kubernetesspecialist" in available_set:
            suggestions["KubernetesSpecialist"] = "Baseline for infrastructure alerts"
        
        for specialist_name, keywords in KEYWORD_MAPPINGS.items():
            # SKIP specialists that are not enabled/available
            if specialist_name.lower() not in available_set:
                continue

            matched_keywords = []
            for keyword in keywords:
                # Simple substring match
                if keyword in context_lower:
                    matched_keywords.append(keyword)
            
            if matched_keywords:
                reason = f"Matched keywords: {', '.join(matched_keywords)}"
                if specialist_name in suggestions:
                    # If already added (e.g. K8s baseline), append reason
                    suggestions[specialist_name] += f"; {reason}"
                else:
                    suggestions[specialist_name] = reason
        
        # Format output
        if not suggestions:
            return "No specific specialists matched the keywords. Suggest manual investigation."

        output = ["Suggested Specialists:"]
        for name, reason in suggestions.items():
            output.append(f"- {name}: {reason}")
            
        return "\n".join(output)

    return Agent(
        name="RouterAgent",
        instructions=ROUTER_INSTRUCTIONS,
        model=model,
        tools=[suggest_specialists_tool]
    )