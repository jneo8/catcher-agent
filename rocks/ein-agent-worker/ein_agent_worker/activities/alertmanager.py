"""Alertmanager activities."""

from typing import List, Optional
import httpx
from temporalio import activity
from pydantic import BaseModel, Field


class AlertmanagerAlert(BaseModel):
    """Simplified Alertmanager alert model for activity."""

    labels: dict = Field(default_factory=dict)
    annotations: dict = Field(default_factory=dict)
    fingerprint: str


class FetchAlertsParams(BaseModel):
    """Parameters for fetch_alerts activity."""

    alertmanager_url: Optional[str] = None
    status: str = "firing"
    alertname: str | None = None


def create_fetch_alerts_activity(default_alertmanager_url: Optional[str] = None):
    """Factory to create fetch_alerts activity with injected default URL."""

    @activity.defn(name="fetch_alerts_activity")
    async def fetch_alerts_activity(params: FetchAlertsParams) -> List[dict]:
        """Activity to fetch alerts from Alertmanager."""
        alertmanager_url = params.alertmanager_url or default_alertmanager_url
        
        if not alertmanager_url:
            raise ValueError("alertmanager_url is required (params or default)")

        api_url = f"{alertmanager_url.rstrip('/')}/api/v2/alerts"
        activity.logger.info(f"Querying Alertmanager API: {api_url}")

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(api_url)
                response.raise_for_status()
                alerts_data = response.json()
            except httpx.HTTPStatusError as e:
                activity.logger.error(f"HTTP error querying Alertmanager: {e}")
                raise
            except httpx.RequestError as e:
                activity.logger.error(f"Request error querying Alertmanager: {e}")
                raise

        alerts = [AlertmanagerAlert(**alert) for alert in alerts_data]
        activity.logger.info(f"Retrieved {len(alerts)} total alerts from Alertmanager")

        filtered_alerts = []
        for alert in alerts:
            alert_status = alert.labels.get("state", "firing") # fallback for older versions
            if hasattr(alert, 'status') and hasattr(alert.status, 'state'):
                 alert_status = alert.status.state

            # Apply status filter
            if params.status != "all" and alert_status != params.status:
                continue

            # Apply alertname filter
            if params.alertname and alert.labels.get("alertname") != params.alertname:
                continue

            filtered_alerts.append(alert.model_dump())

        activity.logger.info(f"Returning {len(filtered_alerts)} filtered alerts")
        return filtered_alerts

    return fetch_alerts_activity
