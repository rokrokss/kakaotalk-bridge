"""Owner-controlled conversation allowlist, shared by OAuth and tunnel workers."""

from pydantic import BaseModel, ConfigDict, Field

KIND = "event_conversation"


class ConversationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    conversation_ref: str = Field(min_length=1, max_length=256)
    enabled: bool


class EventDecision(ConversationDecision):
    cursor_epoch: str | None = Field(default=None, min_length=1, max_length=100)
    after_cursor: int | None = Field(default=None, ge=0)


def enabled(policy, epoch):
    return bool(policy and policy["enabled"] and policy["cursor_epoch"] == epoch)


def allows(state, conversation_ref, epoch, message_id, *, db=None):
    policy = state.get(KIND, conversation_ref, db=db)
    return enabled(policy, epoch) and message_id > policy["after_cursor"]


def decide(state, body):
    if body.enabled and (body.cursor_epoch is None or body.after_cursor is None):
        raise ValueError("An enabling decision requires the current collection checkpoint")
    with state.transaction() as db:
        db.execute("BEGIN IMMEDIATE")
        current = state.get(KIND, body.conversation_ref, db=db)
        # Saving an already-enabled room must not drop unprocessed messages.
        if body.enabled and enabled(current, body.cursor_epoch):
            return
        state.put(KIND, body.conversation_ref, body.model_dump(exclude={"conversation_ref"}), db=db)
        # Drop retries too. A sender already in flight may still complete.
        for identity, delivery in state.all("delivery", db=db):
            if delivery["event"]["data"]["conversation_ref"] == body.conversation_ref:
                state.delete("delivery", identity, db=db)
