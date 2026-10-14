from core.models import AssistantMessage


class SessionManager:
    """Manages conversation history keyed by session_id in PostgreSQL AssistantMessage model."""

    MAX_HISTORY_TURNS = 10

    @classmethod
    def get_history(cls, session_id: str) -> list[dict]:
        qs = AssistantMessage.objects.filter(session_id=session_id).order_by("created_at", "id")
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "metadata": msg.metadata,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in qs
        ]

    @classmethod
    def get_workflow_state(cls, session_id: str) -> dict:
        msg = AssistantMessage.objects.filter(session_id=session_id).order_by("-created_at", "-id").first()
        if msg and isinstance(msg.metadata, dict):
            return dict(msg.metadata.get("workflow_state", {}))
        return {}

    @classmethod
    def update_workflow_state(cls, session_id: str, state: dict):
        msg = AssistantMessage.objects.filter(session_id=session_id).order_by("-created_at", "-id").first()
        if msg:
            if not isinstance(msg.metadata, dict):
                msg.metadata = {}
            msg.metadata["workflow_state"] = state
            msg.save(update_fields=["metadata"])

    @classmethod
    def get_session_dealer_id(cls, session_id: str) -> int | None:
        """Returns the dealer_id associated with this session, if any turn has one recorded."""
        for msg in AssistantMessage.objects.filter(session_id=session_id).order_by("created_at", "id"):
            if isinstance(msg.metadata, dict) and msg.metadata.get("dealer_id") is not None:
                return msg.metadata.get("dealer_id")
        return None

    @classmethod
    def add_turn(
        cls,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list = None,
        tool_results: list = None,
        workflow_state: dict = None,
        dealer_id: int = None,
    ):
        metadata = {}
        if tool_calls:
            metadata["tool_calls"] = tool_calls
        if tool_results:
            metadata["tool_results"] = tool_results
        if workflow_state is not None:
            metadata["workflow_state"] = workflow_state
        if dealer_id is not None:
            metadata["dealer_id"] = dealer_id

        AssistantMessage.objects.create(
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata,
        )

    @classmethod
    def clear(cls, session_id: str = None):
        if session_id:
            AssistantMessage.objects.filter(session_id=session_id).delete()
        else:
            AssistantMessage.objects.all().delete()
