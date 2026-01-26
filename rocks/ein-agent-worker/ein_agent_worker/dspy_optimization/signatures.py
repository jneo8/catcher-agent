"""DSPy signatures for ein-agent prompt optimization.

Each signature defines the input/output contract for an agent type,
enabling DSPy to optimize prompts through its teleprompters.
"""

import dspy


class InvestigationAgentSignature(dspy.Signature):
    """Orchestrate infrastructure investigation by delegating to domain specialists.

    As the lead orchestrator, you analyze the user's request and the current findings to 
    decide on the next logical step in the investigation.
    
    Your goals:
    1. Understand the core issue from the user's request.
    2. Identify which domain (Compute, Storage, Network) is most likely involved.
    3. Handoff to the appropriate specialist with clear instructions.
    4. Synthesize specialist findings to provide a clear answer or request more info.
    
    Focus on the investigation strategy and logical flow rather than specific resource IDs.
    """

    user_request: str = dspy.InputField(
        desc="The user's problem description or investigation query."
    )
    available_specialists: str = dspy.InputField(
        desc="List of available domain experts: ComputeSpecialist, StorageSpecialist, NetworkSpecialist."
    )
    current_findings: str = dspy.InputField(
        desc="Summary of findings collected so far in the shared context."
    )

    reasoning: str = dspy.OutputField(
        desc="Your step-by-step logic for choosing the next action based on available data."
    )
    action: str = dspy.OutputField(
        desc="Next step: 'respond' (answer user), 'handoff' (call specialist), or 'ask_user' (need more details)."
    )
    response: str = dspy.OutputField(
        desc="The actual message for the user or the specific instruction for the specialist handoff."
    )


class SpecialistSignature(dspy.Signature):
    """Perform deep-dive domain investigation using infrastructure tools.

    You are a specialist (Compute, Storage, or Network) tasked with identifying the 
    root cause within your domain. Use your tools to gather evidence and report back.
    
    Your goals:
    1. Translate high-level requests into specific tool queries (e.g., K8s logs, Prometheus metrics).
    2. Identify anomalies or errors that explain the observed symptoms.
    3. Determine if the issue is a definitive root cause or a secondary symptom.
    4. Provide clear evidence and a confidence score for your findings.
    """

    investigation_request: str = dspy.InputField(
        desc="The specific technical question or area to investigate."
    )
    domain: str = dspy.InputField(
        desc="The technical domain: 'compute', 'storage', or 'network'."
    )
    shared_context: str = dspy.InputField(
        desc="Existing findings from other agents that might provide context or clues."
    )

    findings: str = dspy.OutputField(
        desc="Detailed technical findings, including specific error messages, metric values, or state changes."
    )
    root_cause: str = dspy.OutputField(
        desc="A concise statement of the identified root cause, or 'Unknown' if not found."
    )
    confidence: float = dspy.OutputField(
        desc="Numerical confidence in the root cause (0.0 to 1.0). 0.9+ means confirmed."
    )
    context_update: str = dspy.OutputField(
        desc="A key finding to add to the shared context for other agents to use."
    )


class ProjectManagerSignature(dspy.Signature):
    """Synthesize investigation reports into a comprehensive incident analysis.

    As the Project Manager, you receive multiple investigation reports from different 
    specialists and investigators. Your goal is to:
    1. Identify patterns and correlations across different alerts and findings.
    2. Determine the primary root cause by looking for common failure points (e.g., node failure, resource exhaustion, application logic error).
    3. Construct a clear cascade chain showing how the root cause triggered subsequent alerts.
    4. Provide actionable, high-level recommendations that address both the immediate fix and long-term prevention.
    
    Avoid getting bogged down in specific instance IDs unless they are critical to the root cause. Focus on the 'why' and 'how' of the incident.
    """

    investigation_reports: str = dspy.InputField(
        desc="Concatenated reports from specialists and investigators containing their findings and conclusions."
    )
    shared_context: str = dspy.InputField(
        desc="The global blackboard of findings, including confidence scores and metadata."
    )
    alert_summary: str = dspy.InputField(
        desc="Summary of all firing alerts, including names, status, and affected components."
    )

    incident_summary: str = dspy.OutputField(
        desc="A high-level overview of the incident, identifying the scale and primary impact."
    )
    root_cause: str = dspy.OutputField(
        desc="The identified root cause(s) with supporting evidence from the reports. Categorize the cause (e.g., Infrastructure, Application, Configuration)."
    )
    cascade_chain: str = dspy.OutputField(
        desc="A step-by-step explanation of the failure sequence from root cause to observed alerts."
    )
    recommendations: str = dspy.OutputField(
        desc="Bullet points of immediate recovery steps and strategic improvements."
    )
