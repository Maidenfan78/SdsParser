from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sds_parser import extract_fields, parse_date, compute_risk_rating, extract_text_from_pdf

FIXTURE_DIR = Path(__file__).parent / "fixtures"

with open(FIXTURE_DIR / "sample_text.txt", "r", encoding="utf-8") as f:
    SAMPLE_TEXT = f.read()


def test_parse_date_formats():
    assert parse_date("12/04/2023") == "12/04/2023"
    assert parse_date("12-04-23") == "12/04/2023"
    assert parse_date("04/12/2023") == "04/12/2023"
    assert parse_date(None) is None
    # Invalid date returns input
    assert parse_date("31/04/2023") == "31/04/2023"


def test_compute_risk_rating():
    assert compute_risk_rating("insignificant", "rare") == "Low (1)"
    assert compute_risk_rating("moderate", "likely") == "High (12)"
    assert compute_risk_rating("severe", "almost certain") == "Extreme (25)"
    assert compute_risk_rating("unknown", "rare") is None
    assert compute_risk_rating(None, None) is None


def test_extract_fields_from_text():
    record = extract_fields(SAMPLE_TEXT)
    assert record.product_name == "Fancy Stuff"
    assert record.vendor == "ExampleCorp"
    assert record.cas_number == "64-17-5"
    assert record.issue_date == "12/04/2024"
    assert record.hazardous_substance == "Yes"
    assert record.dangerous_good == "No"
    assert record.dangerous_goods_class == "3"


def test_extract_fields_from_pdf():
    pdf_path = FIXTURE_DIR / "sample.pdf"
    with open(pdf_path, "rb") as f:
        data = f.read()
    text = extract_text_from_pdf(data)
    record = extract_fields(text)
    assert record.product_name == "Fancy Stuff"
    assert record.vendor == "ExampleCorp"
    assert record.issue_date == "12/04/2024"

