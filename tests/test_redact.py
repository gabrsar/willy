from willy.redact import REDACTED, redact_json_text


def test_redact_json_text_removes_sensitive_nested_fields() -> None:
    text = """
    {
      "name": "Printer",
      "print_host": "10.0.0.8",
      "dev_id": "printer-device-id",
      "serial_number": "printer-serial",
      "printer_settings_id": "keep-profile-id",
      "nested": {
        "access_token": "abc",
        "profiles": [{"password": "pw"}, {"material": "ABS"}]
      }
    }
    """

    redacted = redact_json_text(text)

    assert REDACTED in redacted
    assert "10.0.0.8" not in redacted
    assert "printer-device-id" not in redacted
    assert "printer-serial" not in redacted
    assert "keep-profile-id" in redacted
    assert "abc" not in redacted
    assert "pw" not in redacted
    assert "ABS" in redacted


def test_redact_json_text_leaves_invalid_json_unchanged() -> None:
    assert redact_json_text("{not json") == "{not json"
