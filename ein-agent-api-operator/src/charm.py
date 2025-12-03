#!/usr/bin/env python3
# Copyright 2025 jneo8
# See LICENSE file for licensing details.

"""FastAPI Charm entrypoint."""

import logging
import typing

import ops
import paas_charm.fastapi
from paas_charm.fastapi.charm import FastAPIConfig
from pydantic import Field

logger = logging.getLogger(__name__)


class Config(FastAPIConfig):
    """Extended FastAPI configuration with Ein Agent specific options.

    Attrs:
        alert_prompts: YAML string containing alert-to-prompt mappings
        temporal_host: Temporal server host and port
        temporal_namespace: Temporal namespace for workflow execution
        temporal_queue: Temporal task queue name for workflow submission
    """

    alert_prompts: str = Field(
        alias="alert-prompts",
        default="",
        description="YAML string content containing alert-to-prompt mappings",
    )
    temporal_host: str = Field(
        alias="temporal-host",
        default="localhost:7233",
        description="Temporal server host and port",
    )
    temporal_namespace: str = Field(
        alias="temporal-namespace",
        default="default",
        description="Temporal namespace",
    )
    temporal_queue: str = Field(
        alias="temporal-queue",
        default="ein-agent-queue",
        description="Temporal task queue name",
    )


class EinAgentAPIOperatorCharm(paas_charm.fastapi.Charm):
    """FastAPI Charm service."""

    # Override to use our extended config class
    framework_config_class = Config

    def __init__(self, *args: typing.Any) -> None:
        """Initialize the instance.

        Args:
            args: passthrough to CharmBase.
        """
        super().__init__(*args)


if __name__ == "__main__":
    ops.main(EinAgentAPIOperatorCharm)
