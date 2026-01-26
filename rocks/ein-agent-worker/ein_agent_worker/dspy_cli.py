import json
import os
import shutil
from pathlib import Path
from typing import Optional

import dspy
import typer
from rich.console import Console

from ein_agent_worker.dspy_optimization import (
    AGENT_METRICS,
    AGENT_MODULES,
    InteractionCollector,
    PromptOptimizer,
)

console = Console()
app = typer.Typer(help="DSPy optimization CLI for ein-agent worker.")

AVAILABLE_AGENTS = [
    "investigation_agent",
    "compute_specialist",
    "storage_specialist",
    "network_specialist",
    "project_manager",
]

@app.command()
def export(
    agent: str = typer.Option(
        ...,
        "--agent",
        "-a",
        help=f"Agent to export data for. Options: {', '.join(AVAILABLE_AGENTS)}",
    ),
    output: Path = typer.Option(
        Path("./training_data/datasets"),
        "--output",
        "-o",
        help="Output directory for exported data",
    ),
    outcome: str = typer.Option(
        "success",
        "--outcome",
        help="Filter by outcome (success, failure, all)",
    ),
):
    """Export collected training data for DSPy optimization."""
    if agent not in AVAILABLE_AGENTS:
        console.print(f"[red]Unknown agent: {agent}[/red]")
        console.print(f"Available agents: {', '.join(AVAILABLE_AGENTS)}")
        raise typer.Exit(1)

    # Map user-friendly names to internal directory names
    agent_map = {
        "project_manager": "InvestigationProjectManager",
        "compute_specialist": "ComputeSpecialist",
        "storage_specialist": "StorageSpecialist",
        "network_specialist": "NetworkSpecialist",
        "investigation_agent": "investigation_agent",
    }
    search_agent_name = agent_map.get(agent, agent)

    collector = InteractionCollector()
    outcome_filter = None if outcome == "all" else outcome
    examples = collector.export_for_dspy(search_agent_name, outcome_filter=outcome_filter)

    if not examples:
        console.print(f"[yellow]No interactions found for {agent}[/yellow]")
        console.print("Make sure EIN_COLLECT_TRAINING_DATA=true when running workflows")
        raise typer.Exit(1)

    # Save to JSON file
    output.mkdir(parents=True, exist_ok=True)
    output_file = output / f"{agent}.json"

    data = [
        {
            "inputs": dict(ex.inputs()),
            "labels": dict(ex.labels()),
        }
        for ex in examples
    ]

    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)

    console.print(f"[green]Exported {len(examples)} examples to {output_file}[/green]")

@app.command()
def compile(
    agent: str = typer.Option(
        ...,
        "--agent",
        "-a",
        help=f"Agent to optimize. Options: {', '.join(AVAILABLE_AGENTS)}",
    ),
    trainset: Path = typer.Option(
        ...,
        "--trainset",
        "-t",
        help="Path to training data JSON file",
    ),
    valset: Optional[Path] = typer.Option(
        None,
        "--valset",
        "-v",
        help="Path to validation data JSON file (defaults to trainset)",
    ),
    output: Path = typer.Option(
        Path("./optimized_prompts"),
        "--output",
        "-o",
        help="Output directory for optimized prompts",
    ),
    version: str = typer.Option(
        "v1",
        "--version",
        help="Version identifier for the optimized prompt",
    ),
    max_demos: int = typer.Option(
        4,
        "--max-demos",
        help="Maximum bootstrapped demonstrations",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="LLM model for optimization (default: gemini/gemini-2.0-flash-exp)",
    ),
):
    """Compile agent prompts using DSPy BootstrapFewShot."""
    if agent not in AVAILABLE_AGENTS:
        console.print(f"[red]Unknown agent: {agent}[/red]")
        raise typer.Exit(1)

    if not trainset.exists():
        console.print(f"[red]Training data not found: {trainset}[/red]")
        raise typer.Exit(1)

    # Load training data
    with open(trainset) as f:
        train_data = json.load(f)

    trainset_examples = [
        dspy.Example(**item["inputs"], **item["labels"]).with_inputs(*item["inputs"].keys())
        for item in train_data
    ]

    # Load validation data if provided
    valset_examples = None
    if valset and valset.exists():
        with open(valset) as f:
            val_data = json.load(f)
        valset_examples = [
            dspy.Example(**item["inputs"], **item["labels"]).with_inputs(*item["inputs"].keys())
            for item in val_data
        ]

    console.print(f"[blue]Compiling {agent} with {len(trainset_examples)} training examples...[/blue]")

    optimizer = PromptOptimizer(task_model=model)
    optimized_prompt, score = optimizer.optimize_agent(
        agent_name=agent,
        trainset=trainset_examples,
        valset=valset_examples,
        max_bootstrapped_demos=max_demos,
    )

    # Save optimized prompt
    output_path = optimizer.save_optimized_prompt(
        agent_name=agent,
        prompt=optimized_prompt,
        version=version,
        base_path=str(output),
    )

    console.print(f"[green]Compilation complete![/green]")
    console.print(f"  Score: {score:.3f}")
    console.print(f"  Saved to: {output_path}")

@app.command()
def evaluate(
    agent: str = typer.Option(
        ...,
        "--agent",
        "-a",
        help=f"Agent to evaluate. Options: {', '.join(AVAILABLE_AGENTS)}",
    ),
    testset: Path = typer.Option(
        ...,
        "--testset",
        "-t",
        help="Path to test data JSON file",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="LLM model for evaluation (default: gemini/gemini-2.0-flash-exp)",
    ),
):
    """Evaluate agent module on a test set using DSPy."""
    if agent not in AVAILABLE_AGENTS:
        console.print(f"[red]Unknown agent: {agent}[/red]")
        raise typer.Exit(1)

    if not testset.exists():
        console.print(f"[red]Test data not found: {testset}[/red]")
        raise typer.Exit(1)

    # Configure DSPy
    task_model = model or "gemini/gemini-2.0-flash-exp"
    dspy.configure(lm=dspy.LM(task_model))

    # Load test data
    with open(testset) as f:
        test_data = json.load(f)

    test_examples = [
        dspy.Example(**item["inputs"], **item["labels"]).with_inputs(*item["inputs"].keys())
        for item in test_data
    ]

    module = AGENT_MODULES[agent]()
    metric = AGENT_METRICS[agent]

    console.print(f"[blue]Evaluating {agent} on {len(test_examples)} test examples...[/blue]")

    evaluator = dspy.Evaluate(devset=test_examples, metric=metric)
    result = evaluator(module)

    console.print(f"[green]Evaluation complete![/green]")
    console.print(f"  Score: {result.score:.3f}")

@app.command()
def deploy(
    agent: str = typer.Option(
        ...,
        "--agent",
        "-a",
        help=f"Agent to deploy prompt for. Options: {', '.join(AVAILABLE_AGENTS)}",
    ),
    prompt_path: Path = typer.Option(
        ...,
        "--prompt",
        "-p",
        help="Path to optimized prompt file",
    ),
    version: str = typer.Option(
        ...,
        "--version",
        help="Version identifier (e.g., v1, v2)",
    ),
    store_path: Optional[Path] = typer.Option(
        None,
        "--store-path",
        help="Prompt store path (default: EIN_PROMPT_STORE_PATH or /app/prompts)",
    ),
):
    """Deploy a DSPy-optimized prompt to the prompt store."""
    if agent not in AVAILABLE_AGENTS:
        console.print(f"[red]Unknown agent: {agent}[/red]")
        raise typer.Exit(1)

    if not prompt_path.exists():
        console.print(f"[red]Prompt file not found: {prompt_path}[/red]")
        raise typer.Exit(1)

    # Determine store path
    base_path = Path(
        str(store_path) if store_path else os.getenv("EIN_PROMPT_STORE_PATH", "/app/prompts")
    )
    version_dir = base_path / version
    version_dir.mkdir(parents=True, exist_ok=True)

    dest_path = version_dir / f"{agent}.txt"
    shutil.copy(prompt_path, dest_path)

    console.print(f"[green]Deployed {agent} prompt to {dest_path}[/green]")
    console.print(f"Set EIN_PROMPT_VERSION={version} to use this prompt at runtime")

if __name__ == "__main__":
    app()
