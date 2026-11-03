"""MCP hub that fans tool calls out to networked ``hamilton_venus_mcp`` spokes (one per
instrument PC, each running its own VENUS + hamilton_venus SDK install) and compiles their
results. Never touches hamilton_venus/hamilton_workflow_framework directly -- every call is
relayed over MCP to a spoke, which does the actual instrument work.
"""

from __future__ import annotations

__all__: list[str] = []
