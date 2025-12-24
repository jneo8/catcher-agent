"""Session state storage utilities."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from ein_agent_cli.models import Context, LocalContext, SessionState


# Default storage location
DEFAULT_CONTEXT_DIR = Path.home() / ".ein-agent" / "context"
DEFAULT_SESSION_FILE = DEFAULT_CONTEXT_DIR / "session-state.json"


def ensure_context_dir() -> Path:
    """Ensure the context directory exists."""
    DEFAULT_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_CONTEXT_DIR


def generate_context_id() -> str:
    """Generate a unique context ID."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    short_uuid = str(uuid.uuid4())[:8]
    return f"context-{timestamp}-{short_uuid}"


def save_session_state(session: SessionState, file_path: Optional[Path] = None) -> None:
    """Save session state to JSON file.

    Args:
        session: SessionState to save
        file_path: Optional custom file path (defaults to DEFAULT_SESSION_FILE)
    """
    if file_path is None:
        file_path = DEFAULT_SESSION_FILE

    ensure_context_dir()

    # Serialize to JSON
    with open(file_path, 'w') as f:
        json.dump(session.model_dump(), f, indent=2)


def load_session_state(file_path: Optional[Path] = None) -> SessionState:
    """Load session state from JSON file.

    Args:
        file_path: Optional custom file path (defaults to DEFAULT_SESSION_FILE)

    Returns:
        SessionState loaded from file, or new SessionState with default context if file doesn't exist
    """
    if file_path is None:
        file_path = DEFAULT_SESSION_FILE

    if not file_path.exists():
        # Create new session state with a default context
        return _create_default_session_state()

    # Load from JSON
    with open(file_path, 'r') as f:
        data = json.load(f)

    # Check if this is old format (has local_context directly)
    if "local_context" in data and "contexts" not in data:
        # Migrate from old format to new format
        return _migrate_old_format(data)

    session = SessionState.model_validate(data)

    # Ensure at least one context exists
    if not session.contexts:
        default_context = Context(
            context_id=generate_context_id(),
            context_name="Default",
            local_context=LocalContext(),
        )
        session.add_context(default_context)

    return session


def _create_default_session_state() -> SessionState:
    """Create a new session state with a default context.

    Returns:
        New SessionState with one default context
    """
    default_context = Context(
        context_id=generate_context_id(),
        context_name="Default",
        local_context=LocalContext(),
    )

    session = SessionState()
    session.add_context(default_context)

    return session


def _migrate_old_format(old_data: dict) -> SessionState:
    """Migrate old session state format to new multi-context format.

    Args:
        old_data: Old format session state data

    Returns:
        Migrated SessionState with contexts
    """
    # Create a context from the old local_context
    context = Context(
        context_id=generate_context_id(),
        context_name="Migrated",
        local_context=LocalContext.model_validate(old_data.get("local_context", {})),
        current_workflow_id=old_data.get("current_workflow_id"),
    )

    session = SessionState()
    session.add_context(context)

    return session


def clear_session_state(file_path: Optional[Path] = None) -> None:
    """Clear session state file.

    Args:
        file_path: Optional custom file path (defaults to DEFAULT_SESSION_FILE)
    """
    if file_path is None:
        file_path = DEFAULT_SESSION_FILE

    if file_path.exists():
        file_path.unlink()
