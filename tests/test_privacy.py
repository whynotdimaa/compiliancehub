from app.privacy.masking import RegexPIIMasker

masker = RegexPIIMasker()


def test_masks_email():
    assert masker.mask("Contact john.doe+hr@acme.com now") == "Contact <EMAIL> now"


def test_masks_international_phone():
    assert masker.mask("Call +380 44 123 45 67 today") == "Call <PHONE> today"


def test_masks_valid_credit_card_luhn():
    # 4532015112830366 is Luhn-valid
    assert masker.mask("Card: 4532 0151 1283 0366.") == "Card: <CREDIT_CARD>."


def test_keeps_luhn_invalid_number():
    # same digits, last changed — Luhn fails, so it's a contract ID, not a card
    assert "4532 0151 1283 0367" in masker.mask("Contract 4532 0151 1283 0367")


def test_masks_iban():
    assert masker.mask("Pay to DE89 3704 0044 0532 0130 00 only") == "Pay to <IBAN> only"


def test_masks_ipv4():
    assert masker.mask("Server at 10.20.30.40 responded") == "Server at <IP_ADDRESS> responded"


def test_keeps_iso_dates_and_article_numbers():
    text = "Effective 2026-07-19, per Article 30 and Section 4.2"
    assert masker.mask(text) == text


def test_keeps_short_numbers():
    assert masker.mask("Retention is 5 years, see page 12") == "Retention is 5 years, see page 12"


def test_mixed_text():
    masked = masker.mask("Email dpo@corp.eu or call +49 30 901820 about GDPR")
    assert "<EMAIL>" in masked
    assert "<PHONE>" in masked
    assert "GDPR" in masked
