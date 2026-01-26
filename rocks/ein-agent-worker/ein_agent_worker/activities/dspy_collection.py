from temporalio import activity
from ein_agent_worker.dspy_optimization.data_collector import AgentInteraction, InteractionCollector

@activity.defn
async def record_interaction_activity(interaction_data: dict) -> None:
    """Record agent interaction to storage.
    
    This activity handles the file I/O for saving interaction data,
    which cannot be done directly in the workflow sandbox.
    """
    try:
        # Re-validate data
        interaction = AgentInteraction.model_validate(interaction_data)
        
        # Use Collector logic which handles paths and structure
        collector = InteractionCollector()
        if collector.enabled:
            collector.record_interaction(interaction)
            activity.logger.info(f"Recorded interaction for {interaction.agent_name} at {collector.storage_path}")
        else:
            activity.logger.debug("Data collection disabled, skipping record_interaction")
        
    except Exception as e:
        activity.logger.error(f"Failed to record interaction: {e}")
        # We don't want to fail the workflow if data collection fails
        return
