"""Tests for DeepgramSTTClient.

These tests validate SDK version compatibility, configuration building,
and protocol conformance *without* requiring a live Deepgram API key.
"""

from __future__ import annotations

import pytest

from app.transcription.providers import STTProviderClient
from app.transcription.providers.deepgram import DeepgramSTTClient


# ---------------------------------------------------------------------------
# SDK version-pin validation: the methods we depend on must exist
# ---------------------------------------------------------------------------


class TestDeepgramSDKMethodExistence:
    """Verify that the Deepgram SDK v6 exposes the methods we depend on."""

    def test_sdk_imports(self) -> None:
        """The SDK modules we use should be importable."""
        from deepgram import DeepgramClient  # noqa: F401
        from deepgram import AsyncDeepgramClient  # noqa: F401

    def test_listen_v1_client_accessible(self) -> None:
        """``client.listen.v1`` must be accessible."""
        from deepgram import DeepgramClient

        client = DeepgramClient(api_key="test-key")
        assert hasattr(client, "listen")
        assert hasattr(client.listen, "v1")

    def test_v1_has_connect(self) -> None:
        """``client.listen.v1.connect`` must exist."""
        from deepgram import DeepgramClient

        client = DeepgramClient(api_key="test-key")
        assert hasattr(client.listen.v1, "connect")
        assert callable(client.listen.v1.connect)

    def test_socket_client_has_send_media(self) -> None:
        """V1SocketClient must expose ``send_media``."""
        from deepgram.listen.v1.socket_client import V1SocketClient

        assert hasattr(V1SocketClient, "send_media"), "missing 'send_media'"

    def test_socket_client_has_send_keep_alive(self) -> None:
        from deepgram.listen.v1.socket_client import V1SocketClient

        assert hasattr(V1SocketClient, "send_keep_alive"), "missing 'send_keep_alive'"

    def test_socket_client_has_send_finalize(self) -> None:
        from deepgram.listen.v1.socket_client import V1SocketClient

        assert hasattr(V1SocketClient, "send_finalize"), "missing 'send_finalize'"

    def test_socket_client_has_send_close_stream(self) -> None:
        from deepgram.listen.v1.socket_client import V1SocketClient

        assert hasattr(V1SocketClient, "send_close_stream"), "missing 'send_close_stream'"

    def test_socket_client_has_recv(self) -> None:
        from deepgram.listen.v1.socket_client import V1SocketClient

        assert hasattr(V1SocketClient, "recv"), "missing 'recv'"

    def test_socket_client_has_on(self) -> None:
        from deepgram.listen.v1.socket_client import V1SocketClient

        assert hasattr(V1SocketClient, "on"), "missing 'on'"

    def test_event_type_exists(self) -> None:
        from deepgram.core.events import EventType

        assert hasattr(EventType, "MESSAGE")
        assert hasattr(EventType, "ERROR")
        assert hasattr(EventType, "CLOSE")


# ---------------------------------------------------------------------------
# Configuration building
# ---------------------------------------------------------------------------


class TestBuildConnectKwargs:
    """Validate that ``build_connect_kwargs`` produces the expected config."""

    def test_default_kwargs(self) -> None:
        client = DeepgramSTTClient(api_key="test-key")
        kwargs = client.build_connect_kwargs()

        assert kwargs["model"] == "nova-2"
        assert kwargs["language"] == "en"
        assert kwargs["sample_rate"] == "16000"
        assert kwargs["channels"] == "1"
        assert kwargs["encoding"] == "linear16"
        assert kwargs["punctuate"] == "true"
        assert kwargs["interim_results"] == "true"
        assert kwargs["smart_format"] == "true"
        assert kwargs["endpointing"] == "800"

    def test_mip_opt_out_included_when_enabled(self) -> None:
        client = DeepgramSTTClient(api_key="test-key", mip_opt_out=True)
        kwargs = client.build_connect_kwargs()
        assert kwargs.get("mip_opt_out") == "true"

    def test_mip_opt_out_excluded_when_disabled(self) -> None:
        client = DeepgramSTTClient(api_key="test-key", mip_opt_out=False)
        kwargs = client.build_connect_kwargs()
        assert "mip_opt_out" not in kwargs

    def test_custom_endpointing(self) -> None:
        client = DeepgramSTTClient(api_key="test-key", endpointing_ms=500)
        kwargs = client.build_connect_kwargs()
        assert kwargs["endpointing"] == "500"

    def test_custom_model_and_language(self) -> None:
        client = DeepgramSTTClient(api_key="test-key", model="nova-3", language="es")
        kwargs = client.build_connect_kwargs()
        assert kwargs["model"] == "nova-3"
        assert kwargs["language"] == "es"

    def test_all_values_are_strings(self) -> None:
        """SDK v6 ``connect()`` accepts all params as strings."""
        client = DeepgramSTTClient(api_key="test-key")
        kwargs = client.build_connect_kwargs()
        for key, value in kwargs.items():
            assert isinstance(value, str), f"{key} should be str, got {type(value)}"

    def test_enable_sentiment_does_not_send_unsupported_live_kwarg(self) -> None:
        """SDK v6 live ``connect()`` does not expose a ``sentiment`` kwarg."""
        client = DeepgramSTTClient(api_key="test-key", enable_sentiment=True, language="en")
        kwargs = client.build_connect_kwargs()
        assert "sentiment" not in kwargs
        assert "detect_entities" not in kwargs

    def test_unsupported_language_never_adds_sentiment_kwargs(self) -> None:
        client = DeepgramSTTClient(api_key="test-key", enable_sentiment=True, language="ja")
        kwargs = client.build_connect_kwargs()
        assert "sentiment" not in kwargs
        assert "detect_entities" not in kwargs


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """DeepgramSTTClient must satisfy the STTProviderClient protocol."""

    def test_implements_protocol(self) -> None:
        client = DeepgramSTTClient(api_key="test-key")
        assert isinstance(client, STTProviderClient)


# ---------------------------------------------------------------------------
# Error handling without connection
# ---------------------------------------------------------------------------


class TestNotConnectedErrors:
    """Methods should raise when called before ``connect()``."""

    @pytest.mark.asyncio
    async def test_send_audio_raises(self) -> None:
        client = DeepgramSTTClient(api_key="test-key")
        with pytest.raises(RuntimeError, match="not connected"):
            await client.send_audio(b"\x00" * 320)

    @pytest.mark.asyncio
    async def test_send_keep_alive_raises(self) -> None:
        client = DeepgramSTTClient(api_key="test-key")
        with pytest.raises(RuntimeError, match="not connected"):
            await client.send_keep_alive()

    @pytest.mark.asyncio
    async def test_send_finalize_raises(self) -> None:
        client = DeepgramSTTClient(api_key="test-key")
        with pytest.raises(RuntimeError, match="not connected"):
            await client.send_finalize()

    @pytest.mark.asyncio
    async def test_send_close_stream_raises(self) -> None:
        client = DeepgramSTTClient(api_key="test-key")
        with pytest.raises(RuntimeError, match="not connected"):
            await client.send_close_stream()

    @pytest.mark.asyncio
    async def test_double_connect_raises(self) -> None:
        client = DeepgramSTTClient(api_key="test-key")
        # Simulate already-connected state
        client._connected = True
        with pytest.raises(RuntimeError, match="already connected"):
            await client.connect()
        client._connected = False  # cleanup


# ---------------------------------------------------------------------------
# Result mapping
# ---------------------------------------------------------------------------


class TestMapResult:
    """Unit tests for the static ``_map_result`` helper."""

    def _make_fake_result(
        self,
        transcript: str = "hello world",
        confidence: float = 0.95,
        is_final: bool = True,
        speech_final: bool = False,
        words: list | None = None,
        result_type: str = "Results",
    ) -> object:
        """Build a minimal mock of a Deepgram ListenV1Results."""

        class FakeWord:
            def __init__(self, word: str, start: float, end: float, conf: float):
                self.word = word
                self.punctuated_word = word
                self.start = start
                self.end = end
                self.confidence = conf
                self.language = None
                self.speaker = None

        class FakeAlternative:
            def __init__(self) -> None:
                self.transcript = transcript
                self.confidence = confidence
                self.languages = ["en"]
                self.words = words if words is not None else [
                    FakeWord("hello", 0.0, 0.3, 0.97),
                    FakeWord("world", 0.4, 0.7, 0.93),
                ]

        class FakeChannel:
            def __init__(self) -> None:
                self.alternatives = [FakeAlternative()]

        class FakeResult:
            def __init__(self) -> None:
                self.type = result_type
                self.channel = FakeChannel()
                self.channel_index = [0]
                self.is_final = is_final
                self.speech_final = speech_final
                self.start = 0.0
                self.duration = 1.0
                self.metadata = None

        return FakeResult()

    def test_basic_mapping(self) -> None:
        result = self._make_fake_result()
        resp = DeepgramSTTClient._map_result(result)
        assert resp is not None
        assert resp.text == "hello world"
        assert resp.is_final is True
        assert resp.speech_final is False
        assert len(resp.words) == 2
        assert resp.words[0].word == "hello"
        assert resp.confidence == 0.95

    def test_empty_transcript_returns_none(self) -> None:
        result = self._make_fake_result(transcript="", words=[])
        resp = DeepgramSTTClient._map_result(result)
        assert resp is None

    def test_no_channel_returns_none(self) -> None:
        class NoChannel:
            type = "Results"
            channel = None

        resp = DeepgramSTTClient._map_result(NoChannel())
        assert resp is None

    def test_speech_final_flag(self) -> None:
        result = self._make_fake_result(is_final=False, speech_final=True)
        resp = DeepgramSTTClient._map_result(result)
        assert resp is not None
        assert resp.is_final is False
        assert resp.speech_final is True

    def test_non_results_type_returns_none(self) -> None:
        """Non-transcript messages (Metadata, UtteranceEnd) are skipped."""
        result = self._make_fake_result(result_type="Metadata")
        resp = DeepgramSTTClient._map_result(result)
        assert resp is None

    def test_uses_punctuated_word(self) -> None:
        """Should prefer ``punctuated_word`` over ``word``."""

        class FakeWord:
            def __init__(self) -> None:
                self.word = "hello"
                self.punctuated_word = "Hello,"
                self.start = 0.0
                self.end = 0.3
                self.confidence = 0.99
                self.language = None
                self.speaker = None

        result = self._make_fake_result(words=[FakeWord()])
        resp = DeepgramSTTClient._map_result(result)
        assert resp is not None
        assert resp.words[0].word == "Hello,"

    def test_language_from_alternatives(self) -> None:
        result = self._make_fake_result()
        resp = DeepgramSTTClient._map_result(result)
        assert resp is not None
        assert resp.language == "en"
