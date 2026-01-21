"""Console output utilities with color formatting."""

from typing import Optional
from rich.console import Console
from rich.panel import Panel

# Global console instance
_console = Console()


def print_message(message: str, color: Optional[str] = None, style: Optional[str] = None) -> None:
    """Print a message with optional color and style.

    Args:
        message: The message to print
        color: Color name (e.g., "green", "red", "yellow", "cyan")
        style: Style modifier (e.g., "bold", "dim")
    """
    if color or style:
        parts = []
        if style:
            parts.append(style)
        if color:
            parts.append(color)
        markup = " ".join(parts)
        _console.print(f"[{markup}]{message}[/{markup}]")
    else:
        _console.print(message)


def print_panel(content: str, title: Optional[str] = None, border_style: str = "blue") -> None:
    """Print a panel with content.

    Args:
        content: The content to display inside the panel.
        title: Optional title for the panel.
        border_style: Style for the panel border (default: "blue").
    """
    _console.print(Panel(content, title=title, border_style=border_style))


def print_dim(message: str) -> None:
    """Print a dim/debug message."""
    _console.print(f"[dim]{message}[/dim]")


def print_success(message: str) -> None:
    """Print a success message in green."""
    _console.print(f"[green]{message}[/green]")


def print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    _console.print(f"[yellow]{message}[/yellow]")


def print_error(message: str) -> None:
    """Print an error message in red."""
    _console.print(f"[red]{message}[/red]")


def print_info(message: str) -> None:
    """Print an info message in cyan."""
    _console.print(f"[cyan]{message}[/cyan]")


def print_header(message: str) -> None:
    """Print a header message in bold cyan."""
    _console.print(f"[bold cyan]{message}[/bold cyan]")


def print_bold_success(message: str) -> None:
    """Print a bold success message in bold green."""
    _console.print(f"[bold green]{message}[/bold green]")


def print_table(table) -> None:
    """Print a Rich table.

    Args:
        table: A Rich Table object to print
    """
    _console.print(table)


def print_newline() -> None:
    """Print a blank line."""
    _console.print()
