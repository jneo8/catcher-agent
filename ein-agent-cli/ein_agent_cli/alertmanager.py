"""Alertmanager integration and alert filtering."""

from typing import Any, Dict, List, Optional
import httpx

from ein_agent_cli import console
from ein_agent_cli.models import (
    AlertmanagerQueryParams,
    AlertFilterParams,
    AlertmanagerAlert,
    WorkflowAlert,
)


class AlertRegistry:
    """Simplified alert registry for CLI - only handles whitelist checking."""

    def __init__(self, alerts_whitelist: Optional[List[str]] = None):
        """Initialize alert registry.

        Args:
            alerts_whitelist: List of alert names or fingerprints to filter. If None, all alerts are accepted.
        """
        self.whitelist = set(alerts_whitelist) if alerts_whitelist else None

    def is_whitelisted(self, alert_name: str, fingerprint: str = "") -> bool:
        """Check if alert is whitelisted by name or fingerprint.

        Args:
            alert_name: Name of the alert
            fingerprint: Fingerprint of the alert (full fingerprint from API)

        Returns:
            True if alert is whitelisted (or no whitelist configured), False otherwise
        """
        if self.whitelist is None:
            return True

        # Check alert name
        if alert_name in self.whitelist:
            return True

        # Check fingerprint - support both full and partial (prefix) matching
        for item in self.whitelist:
            if fingerprint.startswith(item):
                return True

        return False


async def query_alertmanager(params: AlertmanagerQueryParams) -> List[AlertmanagerAlert]:
    """Query Alertmanager API for firing alerts.

    Args:
        params: Alertmanager query parameters

    Returns:
        List of AlertmanagerAlert instances

    Raises:
        httpx.HTTPError: If HTTP request fails
    """
    api_url = f"{params.url.rstrip('/')}/api/v2/alerts"
    console.print_dim(f"Querying Alertmanager API: {api_url}")

    async with httpx.AsyncClient(timeout=params.timeout) as client:
        response = await client.get(api_url)
        response.raise_for_status()
        alerts_data = response.json()

    # Parse into Pydantic models for validation
    alerts = [AlertmanagerAlert(**alert) for alert in alerts_data]

    console.print_success(f"Retrieved {len(alerts)} alerts from Alertmanager")
    return alerts


def convert_alertmanager_alert(am_alert: AlertmanagerAlert) -> Dict[str, Any]:
    """Convert Alertmanager alert to workflow format.

    Args:
        am_alert: AlertmanagerAlert instance

    Returns:
        Alert in workflow format as dictionary
    """
    workflow_alert = WorkflowAlert.from_alertmanager_alert(am_alert)
    return workflow_alert.model_dump()


def filter_alerts(params: AlertFilterParams) -> List[AlertmanagerAlert]:
    """Filter alerts by whitelist and status.

    Args:
        params: Alert filter parameters

    Returns:
        List of filtered AlertmanagerAlert instances
    """
    # Create alert registry for whitelist checking
    alert_registry = AlertRegistry(alerts_whitelist=params.whitelist)

    filtered = []

    for alert in params.alerts:
        # Extract alert name, fingerprint, and status from Pydantic model
        alert_name = alert.labels.get("alertname", "unknown")
        alert_status = alert.status.state
        fingerprint = alert.fingerprint

        # Apply status filter
        if params.status_filter and alert_status != params.status_filter:
            continue

        # Apply whitelist filter (checks both alert name and fingerprint)
        if not alert_registry.is_whitelisted(alert_name, fingerprint):
            continue

        filtered.append(alert)

    console.print_success(f"Filtered {len(filtered)}/{len(params.alerts)} alerts")
    return filtered
