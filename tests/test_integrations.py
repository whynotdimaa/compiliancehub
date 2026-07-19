import httpx

from app.core.config import settings
from app.integrations import slack
from app.integrations.drive import filename_from_headers, normalize_url

# --- Slack -------------------------------------------------------------------


def test_slack_skipped_without_webhook():
    assert slack.send_slack_message("hello") is False


def test_slack_posts_when_configured(monkeypatch):
    sent: list[tuple[str, dict]] = []

    def fake_post(url, json=None, timeout=None):
        sent.append((url, json))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(settings, "slack_webhook_url", "https://hooks.slack.test/T/B/x")
    monkeypatch.setattr(slack.httpx, "post", fake_post)

    assert slack.send_slack_message("document ready") is True
    assert sent == [("https://hooks.slack.test/T/B/x", {"text": "document ready"})]


def test_slack_swallows_http_errors(monkeypatch):
    def failing_post(url, json=None, timeout=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(settings, "slack_webhook_url", "https://hooks.slack.test/T/B/x")
    monkeypatch.setattr(slack.httpx, "post", failing_post)

    assert slack.send_slack_message("text") is False


# --- Google Drive URL normalization -----------------------------------------


def test_drive_file_link_normalized():
    url = "https://drive.google.com/file/d/1AbC-xyz_123/view?usp=sharing"
    assert normalize_url(url) == "https://drive.google.com/uc?export=download&id=1AbC-xyz_123"


def test_drive_open_link_normalized():
    url = "https://drive.google.com/open?id=1AbC-xyz_123"
    assert normalize_url(url) == "https://drive.google.com/uc?export=download&id=1AbC-xyz_123"


def test_drive_uc_link_normalized():
    url = "https://drive.google.com/uc?export=view&id=1AbC-xyz_123"
    assert normalize_url(url) == "https://drive.google.com/uc?export=download&id=1AbC-xyz_123"


def test_non_drive_url_untouched():
    url = "https://example.com/files/policy.pdf"
    assert normalize_url(url) == url


def test_filename_from_content_disposition():
    headers = httpx.Headers({"content-disposition": 'attachment; filename="policy.pdf"'})
    assert filename_from_headers(headers) == "policy.pdf"
    assert filename_from_headers(httpx.Headers({})) is None
