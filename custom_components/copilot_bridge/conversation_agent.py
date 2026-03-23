from __future__ import annotations

from typing import Literal

from homeassistant.components.conversation import (
    AbstractConversationAgent,
    ConversationInput,
    ConversationResult,
)
from homeassistant.helpers import intent

from .api import CopilotBridgeApiClient, CopilotBridgeApiError


class CopilotBridgeConversationAgent(AbstractConversationAgent):
    """Route Home Assistant Assist chat and voice requests to the bridge."""

    def __init__(self, *, client: CopilotBridgeApiClient) -> None:
        self._client = client

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return supported languages."""
        return "*"

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        """Process both Assistant text chat and voice transcripts."""
        try:
            result = await self._client.async_ask(
                prompt=user_input.text,
                session_id=user_input.conversation_id,
                user_id=user_input.context.user_id,
                conversation_id=user_input.conversation_id,
                language=user_input.language,
                device_id=user_input.device_id,
                satellite_id=user_input.satellite_id,
                source="assist",
            )
            speech = str(result.get("response", "")).strip() or (
                "Copilot Bridge returned an empty response."
            )
            conversation_id = result.get("session_id") or user_input.conversation_id
        except CopilotBridgeApiError as err:
            speech = f"Copilot Bridge error: {err}"
            conversation_id = user_input.conversation_id

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(speech)
        return ConversationResult(
            response=response,
            conversation_id=conversation_id,
            continue_conversation=True,
        )
