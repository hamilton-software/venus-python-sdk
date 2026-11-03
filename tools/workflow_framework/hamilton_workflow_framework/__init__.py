"""Reusable WebSocket/session/execution-engine backend for purpose-built Hamilton
STAR workflow UIs, extracted from the hamilton-star-demo-app.

Public surface:

- ``registry``: ParamSpec, RegistryEntry, CommandRegistry -- the command-catalog types.
- ``ws_protocol``: generic client/server WS message shapes + union-building helpers.
- ``execution_engine``: Step, ExecutionEngine, StepObserver -- the step queue/dispatcher.
- ``session``: WorkflowSession -- one StarClient lifecycle per WS connection.
- ``routes_ws`` / ``routes_http`` / ``app_factory``: FastAPI wiring.
- ``config``: WorkflowBackendConfig base dataclass.
- ``consumables`` / ``monitoring``: tip/reagent/sample/TADM tracking, as StepObserver plugins.
"""

from __future__ import annotations

from hamilton_workflow_framework.config import WorkflowBackendConfig
from hamilton_workflow_framework.execution_engine import ExecutionEngine, Step, StepObserver
from hamilton_workflow_framework.registry import CommandRegistry, ParamSpec, RegistryEntry
from hamilton_workflow_framework.session import WorkflowSession

__all__ = [
    "WorkflowBackendConfig",
    "ExecutionEngine",
    "Step",
    "StepObserver",
    "CommandRegistry",
    "ParamSpec",
    "RegistryEntry",
    "WorkflowSession",
]
