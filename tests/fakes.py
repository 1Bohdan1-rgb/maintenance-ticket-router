"""Test doubles for the anthropic SDK, so AI-backed code paths (ticket
classification, technician selection, resume summarization) can be tested
without a real network call - tests control exactly what "Claude" replies.
"""


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeMessageResponse:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeMessages:
    def __init__(self, response_text):
        self._response_text = response_text

    def create(self, **kwargs):
        return _FakeMessageResponse(self._response_text)


class FakeAnthropicClient:
    """Drop-in replacement for anthropic.Anthropic(...) - messages.create()
    always returns `response_text` as the single text block, regardless of
    what was asked.
    """

    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)


def fake_anthropic_constructor(response_text):
    """Returns a callable with the same call signature as anthropic.Anthropic
    (accepts and ignores api_key/timeout/max_retries/etc. kwargs), for use
    with monkeypatch.setattr(some_module.anthropic, "Anthropic", ...).
    """

    def _constructor(*args, **kwargs):
        return FakeAnthropicClient(response_text)

    return _constructor
