"""Pydantic models for Prometheus Alertmanager webhook payload."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Alert(BaseModel):
    """Individual alert within an Alertmanager notification."""

    model_config = ConfigDict(populate_by_name=True)

    status: str
    labels: Dict[str, str]
    annotations: Dict[str, str]
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime = Field(alias="endsAt")
    generator_url: str = Field(alias="generatorURL")
    fingerprint: Optional[str] = None


class AlertmanagerWebhook(BaseModel):
    """Alertmanager webhook payload structure."""

    model_config = ConfigDict(populate_by_name=True)

    version: str = Field(default="4")
    group_key: str = Field(alias="groupKey")
    truncated_alerts: int = Field(default=0, alias="truncatedAlerts")
    status: str
    receiver: str
    group_labels: Dict[str, str] = Field(alias="groupLabels")
    common_labels: Dict[str, str] = Field(alias="commonLabels")
    common_annotations: Dict[str, str] = Field(alias="commonAnnotations")
    external_url: str = Field(alias="externalURL")
    alerts: List[Alert]
