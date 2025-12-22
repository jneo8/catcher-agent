"""Orchestrates incident workflow execution."""

import typer
from rich.table import Table

from ein_agent_cli import console
from ein_agent_cli.alertmanager import query_alertmanager, filter_alerts
from ein_agent_cli.temporal import trigger_incident_workflow
from ein_agent_cli.models import (
    IncidentWorkflowConfig,
    AlertmanagerQueryParams,
    AlertFilterParams,
    TemporalWorkflowParams,
)


async def run_incident_workflow(config: IncidentWorkflowConfig) -> None:
    """Orchestrate incident correlation workflow execution.

    Args:
        config: Workflow configuration

    Raises:
        typer.Exit: On error or early exit
    """
    try:
        console.print_header("Ein Agent - Incident Workflow Trigger\n")

        # Display filter configuration
        if config.filters.include:
            console.print_info(f"Including only alerts (by name or fingerprint): {config.filters.include}")
        else:
            console.print_warning("No whitelist provided - accepting all alerts (except blacklisted)")

        # Query Alertmanager
        try:
            query_params = AlertmanagerQueryParams(url=config.alertmanager_url)
            alerts = await query_alertmanager(query_params)
        except Exception as e:
            console.print_error(f"✗ Failed to query Alertmanager: {e}")
            raise typer.Exit(1)

        if not alerts:
            console.print_warning("No alerts found in Alertmanager")
            raise typer.Exit(0)

        # Get blacklist from config (already validated)
        alert_blacklist = config.filters.blacklist

        if alert_blacklist:
            console.print_info(f"Blacklisting alerts: {alert_blacklist}")

        # Filter alerts
        status_filter = None if config.filters.status == "all" else config.filters.status
        filter_params = AlertFilterParams(
            alerts=alerts,
            whitelist=config.filters.include,
            blacklist=alert_blacklist,
            status_filter=status_filter,
        )
        filtered_alerts = filter_alerts(filter_params)

        if not filtered_alerts:
            console.print_warning("No alerts matched filters")
            console.print_dim(f"Total alerts: {len(alerts)}")
            console.print_dim(f"Status filter: {config.filters.status}")
            console.print_dim(f"Blacklist: {alert_blacklist if alert_blacklist else 'disabled'}")
            console.print_dim(f"Whitelist: {config.filters.include if config.filters.include else 'disabled'}")
            raise typer.Exit(0)

        # Display filtered alerts in a table
        console.print_message("\n[bold]Filtered Alerts:[/bold]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Alert Name")
        table.add_column("Status")
        table.add_column("Severity")
        table.add_column("Namespace", style="dim")
        table.add_column("Fingerprint", style="cyan")
        if config.show_labels:
            table.add_column("Labels", style="dim")

        for idx, alert in enumerate(filtered_alerts, 1):
            # Extract from Pydantic model
            alert_name = alert.labels.get("alertname", "unknown")
            alert_status = alert.status.state
            severity = alert.labels.get("severity", "unknown")
            namespace = alert.labels.get("namespace", "-")
            fingerprint = alert.fingerprint if alert.fingerprint else "-"

            status_color = "red" if alert_status == "firing" else "green"
            row_data = [
                str(idx),
                alert_name,
                f"[{status_color}]{alert_status}[/{status_color}]",
                severity,
                namespace,
                fingerprint,
            ]

            if config.show_labels:
                # Format labels as key=value pairs
                labels_str = ", ".join([f"{k}={v}" for k, v in sorted(alert.labels.items())])
                row_data.append(labels_str)

            table.add_row(*row_data)

        console.print_table(table)
        console.print_newline()

        if config.dry_run:
            console.print_warning("DRY RUN - Not triggering workflow")
            console.print_dim(f"Would trigger workflow with {len(filtered_alerts)} alerts")
            console.print_dim(f"MCP servers: {config.mcp_servers}")
            console.print_dim(f"Temporal: {config.temporal.host}/{config.temporal.namespace}/{config.temporal.queue}")
            return

        # Ask for confirmation before triggering workflow (unless --no-prompt is set)
        console.print_dim(f"MCP servers: {config.mcp_servers}")
        console.print_dim(f"Temporal: {config.temporal.host}/{config.temporal.namespace}/{config.temporal.queue}")
        console.print_newline()

        if not config.no_prompt:
            confirmed = typer.confirm(
                f"Do you want to trigger the workflow with {len(filtered_alerts)} alert(s)?",
                default=False
            )

            if not confirmed:
                console.print_warning("Workflow trigger cancelled by user")
                raise typer.Exit(0)

        # Trigger workflow
        workflow_params = TemporalWorkflowParams(
            alerts=filtered_alerts,
            config=config.temporal,
            mcp_servers=config.mcp_servers,
            workflow_id=config.workflow_id,
        )
        wf_id = await trigger_incident_workflow(workflow_params)

        console.print_newline()
        console.print_bold_success("✓ Workflow triggered successfully!")
        console.print_info(f"Workflow ID: {wf_id}")
        ui_host = config.temporal.host.split(':')[0]
        console.print_dim(f"View in Temporal UI: http://{ui_host}:8080/namespaces/{config.temporal.namespace}/workflows/{wf_id}")

    except typer.Exit:
        raise
    except Exception as e:
        console.print_error(f"✗ Error: {e}")
        raise typer.Exit(1)
