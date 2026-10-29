"""Unit tests for hamilton_venus.models."""

from hamilton_venus.models import (
    CmdResult,
    CommandRequest,
    CommandResponse,
    ErrorData,
    ExecutorEvent,
    ProgressChangedEvent,
    RunMessageQueuedEvent,
    RunState,
    RuntimeStatusEvent,
)


class TestRunState:
    def test_values(self):
        assert RunState.NOT_INITIALIZED.value == 0
        assert RunState.RUNNING.value == 2
        assert RunState.PAUSING.value == 6

    def test_from_int(self):
        assert RunState(4) == RunState.ABORTED


class TestExecutorEvent:
    def test_from_int(self):
        assert ExecutorEvent.from_api_value(6) == ExecutorEvent.RUNNING

    def test_from_string(self):
        assert ExecutorEvent.from_api_value("Running") == ExecutorEvent.RUNNING

    def test_from_string_case_insensitive(self):
        assert ExecutorEvent.from_api_value("PAUSED") == ExecutorEvent.PAUSED

    def test_from_string_aborted(self):
        assert ExecutorEvent.from_api_value("Aborted") == ExecutorEvent.ABORTED

    def test_unknown_int_returns_undefined(self):
        assert ExecutorEvent.from_api_value(99) == ExecutorEvent.UNDEFINED

    def test_unknown_string_returns_undefined(self):
        assert ExecutorEvent.from_api_value("bogus") == ExecutorEvent.UNDEFINED


class TestRuntimeStatusEvent:
    def test_from_int(self):
        evt = RuntimeStatusEvent(executor_event=6, message="ok")
        assert evt.event == ExecutorEvent.RUNNING
        assert evt.message == "ok"

    def test_from_string(self):
        evt = RuntimeStatusEvent(executor_event="Running", message="")
        assert evt.executor_event == 6
        assert evt.event == ExecutorEvent.RUNNING

    def test_from_string_case_insensitive(self):
        evt = RuntimeStatusEvent(executor_event="TERMINATED")
        assert evt.executor_event == 3

    def test_from_alias(self):
        evt = RuntimeStatusEvent.model_validate({"executorEvent": 6, "message": "ok"})
        assert evt.executor_event == 6
        assert evt.event == ExecutorEvent.RUNNING


class TestCmdResult:
    def test_success(self):
        r = CmdResult(result=True, message="done")
        assert r.result is True
        assert r.reset_run_executor is False

    def test_from_dict(self):
        r = CmdResult.model_validate({"result": False, "message": "err", "resetRunExecutor": True})
        assert r.result is False
        assert r.reset_run_executor is True


class TestProgressChangedEvent:
    def test_defaults(self):
        e = ProgressChangedEvent()
        assert e.method_name == ""
        assert e.progress_percentage == 0.0

    def test_extra_fields(self):
        e = ProgressChangedEvent(method_name="test.hsl", progress_percentage=50.0, extra="ok")
        assert e.method_name == "test.hsl"


class TestRunMessageQueuedEvent:
    def test_defaults(self):
        event = RunMessageQueuedEvent()
        assert event.channel == ""
        assert event.message_id == ""
        assert event.timestamp is None
        assert event.queue_depth == 0

    def test_from_aliases(self):
        event = RunMessageQueuedEvent.model_validate(
            {
                "channel": "action-response",
                "messageId": "msg-1",
                "timestamp": "2025-01-01T00:00:00Z",
                "queueDepth": 2,
            }
        )
        assert event.channel == "action-response"
        assert event.message_id == "msg-1"
        assert event.timestamp is not None
        assert event.queue_depth == 2


class TestInstrumentErrorsModels:
    def test_detailed_error_actions_accepts_none(self):
        error = ErrorData.model_validate(
            {
                "uuid": "err-1",
                "deviceId": 1,
                "detailedErrors": [
                    {
                        "uuid": "detail-1",
                        "index": 0,
                        "actions": None,
                        "recoveryActions": [{"id": 1, "name": "Exclude", "index": 0}],
                    }
                ],
            }
        )

        assert error.detailed_errors is not None
        assert len(error.detailed_errors) == 1
        assert error.detailed_errors[0].actions == []

    def test_error_data_actions_accepts_none(self):
        error = ErrorData.model_validate(
            {
                "uuid": "err-1",
                "deviceId": 1,
                "actions": None,
            }
        )

        assert error.actions == []


class TestCommandRequest:
    def test_defaults(self):
        req = CommandRequest(category="System", action_name="instrument.isConnected")
        assert req.id
        assert req.category == "System"
        assert req.action_name == "instrument.isConnected"
        assert req.parameters == {}

    def test_with_parameters(self):
        req = CommandRequest(category="Channels", action_name="tip.pick", parameters={"count": 8})
        assert req.parameters == {"count": 8}

    def test_dump_by_alias(self):
        req = CommandRequest(category="System", action_name="instrument.isConnected")
        data = req.model_dump(by_alias=True)
        assert "id" in data
        assert "actionName" in data
        assert data["actionName"] == "instrument.isConnected"

    def test_from_alias(self):
        req = CommandRequest.model_validate({"id": "abc", "category": "System", "actionName": "test.cmd"})
        assert req.id == "abc"
        assert req.action_name == "test.cmd"


class TestCommandResponse:
    def test_success(self):
        resp = CommandResponse(return_status="Success", return_code=0)
        assert resp.success is True

    def test_failure(self):
        resp = CommandResponse(return_status="Error", return_code=1)
        assert resp.success is False

    def test_failure_wrong_status(self):
        resp = CommandResponse(return_status="Error", return_code=0)
        assert resp.success is False

    def test_failure_wrong_code(self):
        resp = CommandResponse(return_status="Success", return_code=1)
        assert resp.success is False

    def test_defaults(self):
        resp = CommandResponse()
        assert resp.id == ""
        assert resp.category == ""
        assert resp.action_name == ""
        assert resp.return_code == 0
        assert resp.return_status == ""
        assert resp.return_parameters == {}
        assert resp.created_at is None

    def test_from_documented_aliases(self):
        resp = CommandResponse.model_validate(
            {
                "id": "resp-1",
                "actionName": "instrument.isConnected",
                "returnStatus": "Success",
                "returnCode": 0,
                "returnParameters": {"isConnected": True},
                "createdAt": "2025-01-01T00:00:00",
            }
        )
        assert resp.id == "resp-1"
        assert resp.action_name == "instrument.isConnected"
        assert resp.return_status == "Success"
        assert resp.return_parameters == {"isConnected": True}
        assert resp.created_at is not None

    def test_preserves_extra_response_fields(self):
        resp = CommandResponse.model_validate(
            {
                "returnStatus": "Success",
                "returnCode": 0,
                "serverVersion": "1.2.3",
                "diagnostics": {"traceId": "trace-1"},
            }
        )
        assert resp.model_extra == {
            "serverVersion": "1.2.3",
            "diagnostics": {"traceId": "trace-1"},
        }
        data = resp.model_dump(by_alias=True)
        assert data["serverVersion"] == "1.2.3"
        assert data["diagnostics"] == {"traceId": "trace-1"}
