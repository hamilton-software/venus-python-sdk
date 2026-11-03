"""Offline analysis of a finalized SdkRunLog.json, for the Log Viewer (and anything else
that wants the same views without a live run).

Pure Python on top of the parsed log dict -- the same input ``run_summary.summarize_run``
takes -- and, like it, defensive: a truncated or crash-recovered log degrades to less
output, never an exception.

- :func:`build_trace` -- the log (plus an optional VENUS ``.trc``) as categorized trace lines.
- :func:`analyze_errors` -- the run outcome and one incident per failure, with context.
- :func:`build_sample_tracking` -- the Sample Tracking payloads, from the Script Manager's own
  events when the log has them, otherwise rebuilt from the logged aspirate/dispense commands.
- :func:`build_command_list` / :func:`build_command_detail` -- every SDK command, and one command's
  request, response, status messages, errors and trace lines.
"""

from hamilton_workflow_framework.run_log.commands import build_command_detail, build_command_list
from hamilton_workflow_framework.run_log.errors import analyze_errors
from hamilton_workflow_framework.run_log.samples import build_sample_tracking
from hamilton_workflow_framework.run_log.trace import build_trace, parse_venus_trace

__all__ = [
    "analyze_errors",
    "build_command_detail",
    "build_command_list",
    "build_sample_tracking",
    "build_trace",
    "parse_venus_trace",
]
