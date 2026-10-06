from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(max_length=16384)]
Label = Annotated[str, Field(max_length=512)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(StrictModel):
    body: Text = ""
    sender: Label | None = None
    timestamp: int | None = Field(default=None, ge=0)


class Payload(StrictModel):
    title: Label | None = None
    text: Text | None = None
    big_text: Text | None = None
    text_lines: list[Text] = Field(default_factory=list, max_length=100)
    messages: list[Message] = Field(default_factory=list, max_length=100)
    is_group_summary: bool = False
    truncated: bool = False


class DatabaseRef(StrictModel):
    database_id: Annotated[str, Field(min_length=1, max_length=128)]
    log_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]
    chat_id: Annotated[str, Field(pattern=r"^-?[0-9]{1,20}$")]
    sender_id: Annotated[str, Field(pattern=r"^-?[0-9]{1,20}$")]
    message_type: Annotated[str, Field(max_length=32)]
    origin: Annotated[str, Field(max_length=128)] = ""
    is_mine: bool = False


class Observation(StrictModel):
    event_id: UUID
    device_id: Annotated[str, Field(min_length=1, max_length=128)]
    enrollment_epoch: UUID
    source_seq: int = Field(ge=1)
    source: Literal["notification", "iris_db"] = "notification"
    kind: Literal["posted", "snapshot", "removed", "db_row"]
    package_name: Literal["com.kakao.talk"]
    notification_key: Annotated[str, Field(min_length=1, max_length=2048)]
    observed_at: AwareDatetime
    notification_posted_at: int | None = Field(default=None, ge=0)
    payload: Payload
    database_ref: DatabaseRef | None = None

    @model_validator(mode="after")
    def source_shape(self):
        if self.source == "iris_db":
            if (
                self.database_ref is None
                or self.kind != "db_row"
                or self.source_seq != int(self.database_ref.log_id)
                or self.source_seq > 9223372036854775807
                or len(self.payload.messages) != 1
                or self.payload.is_group_summary
            ):
                raise ValueError("invalid iris row")
        elif self.database_ref is not None or self.kind == "db_row":
            raise ValueError("invalid notification")
        return self


class Batch(StrictModel):
    schema_version: Literal[1]
    events: list[dict] = Field(min_length=1, max_length=100)


class Heartbeat(StrictModel):
    supports_message_send: bool = False
    source: Literal["notification", "iris_db"] = "notification"
    database_id: Annotated[str, Field(max_length=128)] | None = None
    device_id: Annotated[str, Field(min_length=1, max_length=128)]
    enrollment_epoch: UUID
    listener_connected: bool
    secondary_login_confirmed: bool = False
    outbox_depth: int = Field(ge=0)
    last_source_seq: int = Field(ge=0)
    dropped_events: int = Field(default=0, ge=0)
    quarantine_depth: int = Field(default=0, ge=0)
    oldest_pending_at: AwareDatetime | None = None


class DeviceStatus(StrictModel):
    device_id: Annotated[str, Field(min_length=1, max_length=128)]
    state: Literal["offline", "booting", "needs_setup", "android_ready"]
    android_version: str | None = Field(default=None, max_length=64)
    kakao_installed: bool = False
    bridge_installed: bool = False


class DisplayIdentity(StrictModel):
    name: Label | None = None
    status: Literal["resolved", "not_found", "unavailable"]
    reason: Annotated[str, Field(max_length=80)] | None = None
    name_source: Annotated[str, Field(max_length=80)] | None = None

    @model_validator(mode="after")
    def resolved_name(self):
        if (self.status == "resolved") != bool(self.name and self.name.strip()):
            raise ValueError("name_status_mismatch")
        return self


class IdentityMetadata(StrictModel):
    chat_id: Annotated[str, Field(pattern=r"^-?[0-9]{1,20}$")]
    user_id: Annotated[str, Field(pattern=r"^-?[0-9]{1,20}$")]
    kind: Annotated[str, Field(max_length=80)] | None = None
    sender: DisplayIdentity
    conversation: DisplayIdentity


class MetadataBatch(StrictModel):
    device_id: Annotated[str, Field(min_length=1, max_length=128)]
    enrollment_epoch: UUID
    database_id: Annotated[str, Field(min_length=1, max_length=128)]
    items: list[IdentityMetadata] = Field(max_length=50)
