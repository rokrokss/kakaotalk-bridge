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
    messages: list[Message] = Field(default_factory=list, max_length=1)
    truncated: bool = False


# A row Iris could read but not decode. It advances the cursor without becoming a message.
SkipReason = Literal["decrypt_failed", "metadata_unreadable", "invalid_row", "unreadable"]


class DatabaseRef(StrictModel):
    database_id: Annotated[str, Field(min_length=1, max_length=128)]
    log_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]
    chat_id: Annotated[str, Field(pattern=r"^-?[0-9]{1,20}$")]
    sender_id: Annotated[str, Field(pattern=r"^-?[0-9]{1,20}$")]
    message_type: Annotated[str, Field(max_length=32)]
    origin: Annotated[str, Field(max_length=128)] = ""
    is_mine: bool = False
    skip_reason: SkipReason | None = None


class Observation(StrictModel):
    event_id: UUID
    device_id: Annotated[str, Field(min_length=1, max_length=128)]
    enrollment_epoch: UUID
    source_seq: int = Field(ge=1, le=9223372036854775807)
    source: Literal["iris_db"]
    kind: Literal["db_row", "db_row_skipped"]
    package_name: Literal["com.kakao.talk"]
    notification_key: Annotated[str, Field(min_length=1, max_length=2048)]
    observed_at: AwareDatetime
    payload: Payload
    database_ref: DatabaseRef

    @model_validator(mode="after")
    def row_shape(self):
        skipped = self.kind == "db_row_skipped"
        if (
            self.source_seq != int(self.database_ref.log_id)
            or len(self.payload.messages) != (0 if skipped else 1)
            or (self.database_ref.skip_reason is not None) != skipped
        ):
            raise ValueError("invalid iris row")
        return self


class Batch(StrictModel):
    schema_version: Literal[1]
    events: list[dict] = Field(min_length=1, max_length=100)


class Heartbeat(StrictModel):
    source: Literal["iris_db"] = "iris_db"
    database_id: Annotated[str, Field(max_length=128)] | None = None
    device_id: Annotated[str, Field(min_length=1, max_length=128)]
    enrollment_epoch: UUID
    listener_connected: bool
    secondary_login_confirmed: bool = False
    last_source_seq: int = Field(ge=0)
    kakao_version: int | None = Field(default=None, ge=0)


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
    self_identity_source: Literal["local_account", "sent_message", "unavailable"] | None = None
