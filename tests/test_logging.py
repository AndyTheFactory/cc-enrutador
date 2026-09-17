from __future__ import annotations

from cc_enrutador.logging import redact_value


def test_redacts_sensitive_mapping_values() -> None:
    value = {
        "Authorization": "Bearer abc.def",
        "api_key": "secret-value",
        "nested": {"token": "1234", "safe": "visible"},
    }

    redacted = redact_value(value)

    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == "visible"


def test_redacts_inline_bearer_and_secret() -> None:
    text = "Authorization: Bearer abc.def token=supersecret"

    redacted = redact_value(text)

    assert "abc.def" not in redacted
    assert "supersecret" not in redacted
    assert "[REDACTED]" in redacted
