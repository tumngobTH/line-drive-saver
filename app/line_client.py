from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError  # noqa: F401 (re-exported)
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    PushMessageRequest,
    TextMessage,
)


def source_id_of(source) -> str:
    """The stable id we key folders by: group > room > user."""
    if source.type == "group":
        return source.group_id
    if source.type == "room":
        return source.room_id
    return source.user_id


class LineClient:
    def __init__(self, channel_secret: str, channel_access_token: str):
        self._parser = WebhookParser(channel_secret)
        self._config = Configuration(access_token=channel_access_token)

    def parse(self, body: str, signature: str):
        """Verify signature and return events. Raises InvalidSignatureError."""
        return self._parser.parse(body, signature)

    def group_id_of(self, source) -> str | None:
        if source.type == "group":
            return source.group_id
        return None

    def _blob_api(self):
        return MessagingApiBlob(ApiClient(self._config))

    def _messaging_api(self):
        return MessagingApi(ApiClient(self._config))

    def download_content(self, message_id: str) -> bytes:
        return self._blob_api().get_message_content(message_id)

    def get_group_summary_name(self, group_id: str) -> str | None:
        try:
            summary = self._messaging_api().get_group_summary(group_id)
            return summary.group_name
        except Exception:
            return None

    def push_text(self, to: str, text: str) -> None:
        self._messaging_api().push_message(
            PushMessageRequest(to=to, messages=[TextMessage(text=text)])
        )
