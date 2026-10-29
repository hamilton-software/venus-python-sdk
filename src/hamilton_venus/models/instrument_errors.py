"""Instrument error models for the Hamilton VENUS Python SDK."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Help(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    context_id: str | None = Field(None, alias="contextId")
    location: str | None = None


class Option(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    index: int
    value: str


class Rule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str
    parameter: str
    value: str | None = None


class Input(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    index: int
    default_value: str = Field("", alias="defaultValue")
    pattern: str | None = None
    value_type: str = Field("", alias="valueType")
    options: list[Option] | None = None
    rules: list[Rule] | None = None

    # VENUS sends null for inputs with no default (e.g. the manual "Barcode" entry
    # of a barcode error); keep these as "" so one null can't fail the whole event.
    @field_validator("default_value", "value_type", mode="before")
    @classmethod
    def _none_to_empty(cls, value: object) -> object:
        return "" if value is None else value


class Attribute(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    value: str | None = None


class RecoveryActionDescriptor(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    index: int
    description: str | None = None
    help: Help | None = None
    inputs: list[Input] | None = None
    iterations: int | None = None


class Action(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    index: int
    description: str | None = None
    group: str | None = None
    help: Help | None = None
    inputs: list[Input] | None = None


class DetailedError(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uuid: str
    index: int
    code: str | None = None
    date: str | None = None
    message: str | None = None
    default_recovery_action_id: int = Field(0, alias="defaultRecoveryActionId")
    actions: list[Action] = Field(default_factory=list)
    attributes: list[Attribute] | None = None
    help: Help | None = None
    recovery_actions: list[RecoveryActionDescriptor] | None = Field(None, alias="recoveryActions")

    @field_validator("actions", mode="before")
    @classmethod
    def _normalize_actions(cls, value: object) -> object:
        if value is None:
            return []
        return value


class ErrorData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uuid: str
    device_id: int = Field(0, alias="deviceId")
    code: str | None = None
    date: str | None = None
    message: str | None = None
    title: str | None = None
    timeout: int = -1
    default_recovery_action_id: int = Field(0, alias="defaultRecoveryActionId")
    actions: list[Action] | None = None
    detailed_errors: list[DetailedError] | None = Field(None, alias="detailedErrors")
    help: Help | None = None
    notification_sound: str | None = Field(None, alias="notificationSound")
    recovery_actions: list[RecoveryActionDescriptor] = Field(default_factory=list, alias="recoveryActions")

    @field_validator("actions", mode="before")
    @classmethod
    def _normalize_actions(cls, value: object) -> object:
        if value is None:
            return []
        return value


class ErrorDataResponseModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[ErrorData] = Field(default_factory=list)
    message: str | None = None
    success: bool = True


class InputValue(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    value: str


class DetailedErrorRecovery(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    date: str
    uuid: str
    inputs: list[InputValue] = Field(default_factory=list)
    selected_action_id: int = Field(-1, alias="selectedActionId")


class ErrorRecovery(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    date: str
    uuid: str
    detailed_error_recoveries: list[DetailedErrorRecovery] | None = Field(None, alias="detailedErrorRecoveries")
    inputs: list[InputValue] | None = None
    selected_action_id: int = Field(-1, alias="selectedActionId")
    selected_action_is_recovery: bool = Field(False, alias="selectedActionIsRecovery")
    error_handling_key: str = Field("", alias="errorHandlingKey")


class InstrumentErrorHandled(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uuid: str
    recovery_action: str = Field("", alias="recoveryAction")


class ErrorHandlingResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: str | None = None
    message: str | None = None
    success: bool = True
