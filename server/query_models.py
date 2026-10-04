"""Documented MCP result shapes, independent of event cursor wire formats."""

from typing import Literal

from pydantic import BaseModel, Field


class IdentityView(BaseModel):
    ref: str | None
    name: str | None = Field(
        description="Latest locally resolved display name. Null means lookup is pending or failed; never use ref as a name."
    )
    name_status: Literal["resolved", "pending", "not_found", "unavailable"]
    name_reason: str | None
    name_source: str | None
    updated_at: str | None


class RoomView(IdentityView):
    kind: str | None


class SenderView(IdentityView):
    name: str | None = Field(
        description="Latest local profile name, or the last recorded system-event nickname when name_status is historical. Never infer a name from ref."
    )
    name_status: Literal["resolved", "historical", "pending", "not_found", "unavailable"]
    name_observed_at: str | None = Field(
        description="For historical names: UTC source time of the join/leave event recording this nickname, not collection/lookup time or proof of the current name. Null for current profiles."
    )
    name_evidence_message_id: int | None = Field(
        description="Retained system-event message ID supporting a historical nickname; null for current profiles."
    )


class MessageView(BaseModel):
    message_id: int = Field(
        description="Opaque collector message ID, suitable for get_conversation_context."
    )
    conversation: RoomView
    sender: SenderView
    is_mine: bool | None
    sent_at: str | None = Field(
        description="Message source timestamp in ISO 8601 UTC. Null means unknown; do not substitute collected_at."
    )
    collected_at: str = Field(
        description="Time the server stored this row, not the message send time."
    )
    body: str
    message_type: str | None = Field(
        description="Raw KakaoTalk type code; attachments are not downloaded by this API."
    )
    source: str
    truncated: bool


class MessagePage(BaseModel):
    items: list[MessageView]
    next_cursor: str | None = Field(
        description="Opaque query cursor; reuse with identical filters for older messages. Never pass it to event acknowledgment."
    )
    has_more: bool
    order: Literal["sent_at_desc"]
    unknown_times: Literal["last"]
    time_range: Literal["since_inclusive_until_exclusive"]
    coverage: dict


class ConversationView(RoomView):
    last_message_at: str | None
    last_message_id: int
    message_count: int = Field(
        description="Messages retained by this collector, not the total number in KakaoTalk."
    )


class ConversationPage(BaseModel):
    items: list[ConversationView]
    next_cursor: str | None
    has_more: bool
    order: Literal["last_message_at_desc"]
    scope: Literal["retained_collected_messages"]
    coverage: dict


class ContextPage(BaseModel):
    target_message_id: int
    items: list[MessageView]
    has_more_before: bool
    has_more_after: bool
    order: Literal["sent_at_asc"]
    coverage: dict
