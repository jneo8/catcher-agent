"""Ein Agent CLI commands."""

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table
from temporalio.client import Client as TemporalClient

app = typer.Typer(help="Ein Agent CLI - Incident investigation and correlation")
console = Console()

# Default blacklist - alerts to exclude by default
DEFAULT_BLACKLIST = ["Watchdog"]


class AlertRegistry:
    """Simplified alert registry for CLI - only handles whitelist checking."""

    def __init__(self, alerts_whitelist: Optional[List[str]] = None):
        """Initialize alert registry.

        Args:
            alerts_whitelist: List of alert names to filter. If None, all alerts are accepted.
        """
        self.whitelist = set(alerts_whitelist) if alerts_whitelist else None

    def is_whitelisted(self, alert_name: str) -> bool:
        """Check if alert is whitelisted.

        Args:
            alert_name: Name of the alert

        Returns:
            True if alert is whitelisted (or no whitelist configured), False otherwise
        """
        if self.whitelist is None:
            return True
        return alert_name in self.whitelist


async def query_alertmanager(alertmanager_url: str, timeout: int = 10) -> List[Dict[str, Any]]:
    """Query Alertmanager API for firing alerts.

    Args:
        alertmanager_url: Base URL of Alertmanager (e.g., http://localhost:9093)
        timeout: HTTP timeout in seconds

    Returns:
        List of alert dictionaries

    Raises:
        httpx.HTTPError: If HTTP request fails
    """
    api_url = f"{alertmanager_url.rstrip('/')}/api/v2/alerts"
    console.print(f"[dim]Querying Alertmanager API: {api_url}[/dim]")

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(api_url)
        response.raise_for_status()
        alerts_data = response.json()

    console.print(f"[green]Retrieved {len(alerts_data)} alerts from Alertmanager[/green]")
    return alerts_data


def convert_alertmanager_alert(am_alert: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Alertmanager API alert format to workflow format.

    Args:
        am_alert: Alert from Alertmanager API

    Returns:
        Alert in workflow format
    """
    labels = am_alert.get("labels", {})
    annotations = am_alert.get("annotations", {})

    return {
        "alertname": labels.get("alertname", "unknown"),
        "status": am_alert.get("status", {}).get("state", "unknown"),
        "labels": labels,
        "annotations": annotations,
        "starts_at": am_alert.get("startsAt", ""),
        "ends_at": am_alert.get("endsAt", ""),
        "fingerprint": am_alert.get("fingerprint", ""),
        "generator_url": am_alert.get("generatorURL", ""),
    }


def filter_alerts(
    alerts: List[Dict[str, Any]],
    alert_registry: AlertRegistry,
    status_filter: Optional[str] = "firing",
    blacklist: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Filter alerts by blacklist, whitelist and status.

    Args:
        alerts: List of alerts from Alertmanager
        alert_registry: AlertRegistry for whitelist checking
        status_filter: Filter by status (e.g., "firing", "resolved"). None = no filter
        blacklist: List of alert names to exclude. None = no blacklist

    Returns:
        List of filtered alerts
    """
    filtered = []
    blacklisted_count = 0

    for alert in alerts:
        alert_name = alert.get("labels", {}).get("alertname", "unknown")
        alert_status = alert.get("status", {}).get("state", "unknown")

        # Apply blacklist filter first
        if blacklist and alert_name in blacklist:
            blacklisted_count += 1
            continue

        # Apply status filter
        if status_filter and alert_status != status_filter:
            continue

        # Apply whitelist filter
        if not alert_registry.is_whitelisted(alert_name):
            continue

        filtered.append(alert)

    if blacklisted_count > 0:
        console.print(f"[dim]Blacklisted {blacklisted_count} alerts: {blacklist}[/dim]")
    console.print(f"[green]Filtered {len(filtered)}/{len(alerts)} alerts[/green]")
    return filtered


async def trigger_incident_workflow(
    alerts: List[Dict[str, Any]],
    temporal_host: str,
    temporal_namespace: str,
    temporal_queue: str,
    mcp_servers: List[str],
    workflow_id: Optional[str] = None,
) -> str:
    """Trigger IncidentCorrelationWorkflow in Temporal.

    Args:
        alerts: List of alerts to investigate
        temporal_host: Temporal server host:port
        temporal_namespace: Temporal namespace
        temporal_queue: Temporal task queue name
        mcp_servers: List of MCP server names
        workflow_id: Optional custom workflow ID

    Returns:
        Workflow ID

    Raises:
        Exception: If workflow trigger fails
    """
    console.print(f"[dim]Connecting to Temporal: {temporal_host}, namespace={temporal_namespace}[/dim]")

    client = await TemporalClient.connect(
        temporal_host,
        namespace=temporal_namespace,
    )

    # Convert alerts to workflow format
    workflow_alerts = [convert_alertmanager_alert(alert) for alert in alerts]

    # Generate workflow ID if not provided
    if not workflow_id:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        workflow_id = f"incident-correlation-{timestamp}"

    console.print(f"[cyan]Starting workflow: {workflow_id}[/cyan]")
    console.print(f"[dim]Alerts: {len(workflow_alerts)}[/dim]")
    console.print(f"[dim]MCP servers: {mcp_servers}[/dim]")

    # Start workflow
    handle = await client.start_workflow(
        "IncidentCorrelationWorkflow",
        workflow_alerts,
        id=workflow_id,
        task_queue=temporal_queue,
        memo={"mcp_servers": mcp_servers},
    )

    console.print(f"[green]✓ Workflow started: {workflow_id}[/green]")
    return workflow_id


@app.command()
def run_incident_workflow(
    alertmanager_url: str = typer.Option(
        "http://localhost:9093",
        "--alertmanager-url",
        "-a",
        help="Alertmanager URL",
    ),
    include: Optional[List[str]] = typer.Option(
        None,
        "--include",
        "-i",
        help="Alert names to include (whitelist). If not specified, all alerts are included.",
    ),
    mcp_servers: List[str] = typer.Option(
        ["kubernetes", "grafana"],
        "--mcp-server",
        "-m",
        help="MCP server names to use",
    ),
    temporal_host: str = typer.Option(
        None,
        "--temporal-host",
        help="Temporal server host:port",
    ),
    temporal_namespace: str = typer.Option(
        None,
        "--temporal-namespace",
        help="Temporal namespace",
    ),
    temporal_queue: str = typer.Option(
        None,
        "--temporal-queue",
        help="Temporal task queue",
    ),
    workflow_id: Optional[str] = typer.Option(
        None,
        "--workflow-id",
        help="Custom workflow ID",
    ),
    status: str = typer.Option(
        "firing",
        "--status",
        help="Filter alerts by status (firing/resolved/all)",
    ),
    blacklist: Optional[List[str]] = typer.Option(
        None,
        "--blacklist",
        "-b",
        help="Alert names to exclude (default: Watchdog). Use --blacklist '' to disable",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Query and filter alerts but don't trigger workflow",
    ),
):
    """Query Alertmanager and trigger incident correlation workflow.

    This command will:
    1. Query Alertmanager API for alerts
    2. Filter alerts by blacklist (default: Watchdog)
    3. Filter alerts by whitelist (if --include specified)
    4. Filter alerts by status (firing/resolved/all)
    5. Trigger IncidentCorrelationWorkflow in Temporal

    Examples:

      # Run with default settings (blacklists Watchdog, includes all others)
      ein-agent-cli run-incident-workflow

      # Include only specific alerts
      ein-agent-cli run-incident-workflow -i KubePodNotReady -i KubePodCrashLooping

      # Custom blacklist (exclude TargetDown and Watchdog)
      ein-agent-cli run-incident-workflow -b TargetDown -b Watchdog

      # Disable blacklist
      ein-agent-cli run-incident-workflow -b ''

      # Query remote Alertmanager
      ein-agent-cli run-incident-workflow -a http://alertmanager.example.com:9093

      # Dry run to see what would be triggered
      ein-agent-cli run-incident-workflow --dry-run
    """
    async def _run():
        try:
            console.print("[bold cyan]Ein Agent - Incident Workflow Trigger[/bold cyan]\n")

            # Get Temporal config from env or options
            t_host = temporal_host or os.getenv("TEMPORAL_HOST", "localhost:7233")
            t_namespace = temporal_namespace or os.getenv("TEMPORAL_NAMESPACE", "default")
            t_queue = temporal_queue or os.getenv("TEMPORAL_QUEUE", "ein-agent-queue")

            # Create alert registry for whitelist filtering
            if include:
                console.print(f"[cyan]Including only alerts: {include}[/cyan]")
                alert_registry = AlertRegistry(alerts_whitelist=include)
            else:
                console.print("[yellow]No whitelist provided - accepting all alerts (except blacklisted)[/yellow]")
                alert_registry = AlertRegistry(alerts_whitelist=None)

            # Query Alertmanager
            try:
                alerts = await query_alertmanager(alertmanager_url)
            except Exception as e:
                console.print(f"[red]✗ Failed to query Alertmanager: {e}[/red]")
                raise typer.Exit(1)

            if not alerts:
                console.print("[yellow]No alerts found in Alertmanager[/yellow]")
                raise typer.Exit(0)

            # Determine blacklist: use default if not specified, or user-provided list
            alert_blacklist = blacklist if blacklist is not None else DEFAULT_BLACKLIST
            # Handle explicit disable: if empty list or contains empty string, disable blacklist
            if alert_blacklist is not None and (len(alert_blacklist) == 0 or "" in alert_blacklist):
                alert_blacklist = None

            if alert_blacklist:
                console.print(f"[cyan]Blacklisting alerts: {alert_blacklist}[/cyan]")

            # Filter alerts
            status_filter = None if status == "all" else status
            filtered_alerts = filter_alerts(alerts, alert_registry, status_filter=status_filter, blacklist=alert_blacklist)

            if not filtered_alerts:
                console.print("[yellow]No alerts matched filters[/yellow]")
                console.print(f"[dim]Total alerts: {len(alerts)}[/dim]")
                console.print(f"[dim]Status filter: {status}[/dim]")
                console.print(f"[dim]Blacklist: {alert_blacklist if alert_blacklist else 'disabled'}[/dim]")
                console.print(f"[dim]Whitelist: {include if include else 'disabled'}[/dim]")
                raise typer.Exit(0)

            # Display filtered alerts in a table
            console.print("\n[bold]Filtered Alerts:[/bold]")
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("#", style="dim", width=4)
            table.add_column("Alert Name")
            table.add_column("Status")
            table.add_column("Severity")
            table.add_column("Namespace", style="dim")

            for idx, alert in enumerate(filtered_alerts, 1):
                alert_name = alert.get("labels", {}).get("alertname", "unknown")
                alert_status = alert.get("status", {}).get("state", "unknown")
                severity = alert.get("labels", {}).get("severity", "unknown")
                namespace = alert.get("labels", {}).get("namespace", "-")

                status_color = "red" if alert_status == "firing" else "green"
                table.add_row(
                    str(idx),
                    alert_name,
                    f"[{status_color}]{alert_status}[/{status_color}]",
                    severity,
                    namespace,
                )

            console.print(table)
            console.print()

            if dry_run:
                console.print("[yellow]DRY RUN - Not triggering workflow[/yellow]")
                console.print(f"[dim]Would trigger workflow with {len(filtered_alerts)} alerts[/dim]")
                console.print(f"[dim]MCP servers: {mcp_servers}[/dim]")
                console.print(f"[dim]Temporal: {t_host}/{t_namespace}/{t_queue}[/dim]")
                return

            # Trigger workflow
            wf_id = await trigger_incident_workflow(
                alerts=filtered_alerts,
                temporal_host=t_host,
                temporal_namespace=t_namespace,
                temporal_queue=t_queue,
                mcp_servers=mcp_servers,
                workflow_id=workflow_id,
            )

            console.print()
            console.print(f"[bold green]✓ Workflow triggered successfully![/bold green]")
            console.print(f"[cyan]Workflow ID: {wf_id}[/cyan]")
            ui_host = t_host.split(':')[0]
            console.print(f"[dim]View in Temporal UI: http://{ui_host}:8080/namespaces/{t_namespace}/workflows/{wf_id}[/dim]")

        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")
            raise typer.Exit(1)

    asyncio.run(_run())
