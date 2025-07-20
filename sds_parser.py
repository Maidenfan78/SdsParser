"""SDS Parsing Utility

Goal: Upload an SDS (PDF) and extract a normalized record suitable for a chemical register CSV.

This module provides:
  * FastAPI app with /parse-sds endpoint (multipart/form-data PDF upload)
  * Text extraction (pdfplumber -> fallback OCR via pytesseract for scanned PDFs)
  * Heuristic field extraction using configurable regex patterns & keyword windows
  * Risk matrix helper (Consequence, Likelihood, Risk Rating) placeholders
  * CSV append (creates file with headers if not existing)
  * /health/ocr endpoint to report OCR status & version

NOTES / DISCLAIMER:
SDS document formats vary widely. You WILL need to tune patterns for each supplier.
Start with a small corpus of PDFs, log unmatched lines, then iteratively refine patterns.

Dependencies (baseline):
  pip install fastapi uvicorn[standard] pdfplumber pydantic python-multipart pytesseract pillow regex python-dateutil rich
  (Install Tesseract executable separately on Windows.)

Run dev server:
  uvicorn sds_parser:app --reload

Example request (curl):
  curl -X POST -F "file=@SampleSDS.pdf" http://localhost:8000/parse-sds

CSV output default: data/chemical_register.csv
"""

from __future__ import annotations

import io
import os
import re
import csv
import json
import hashlib
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
import pdfplumber

# Optional OCR imports (guarded)
try:  # pragma: no cover
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore
    OCR_AVAILABLE = True
except Exception:  # pragma: no cover
    pytesseract = None  # type: ignore
    Image = None  # type: ignore
    OCR_AVAILABLE = False

# --------------------------------------------------
# LOGGING
# --------------------------------------------------
logger = logging.getLogger("chemfetch")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------
REGISTER_HEADERS = [
    "Product Name",
    "Vendor / Manufacturer",
    "Quantity",
    "Location",
    "CAS Number",
    "SDS Available",
    "Issue Date (DD/MM/YYYY)",
    "Hazardous Substance",
    "Dangerous Good",
    "Dangerous Goods Class",
    "Description",
    "Packing group",
    "Subsidiary Risk(s)",
    "Consequence",
    "Likelihood",
    "Risk Rating",
    "Safe Work Procedure (SWP) Requirement",
    "Comments/SWP",
    "Barcode",
]

OUTPUT_CSV = os.getenv("CHEMFETCH_REGISTER_CSV", "data/chemical_register.csv")
_output_dir = os.path.dirname(os.path.abspath(OUTPUT_CSV))
if _output_dir:
    os.makedirs(_output_dir, exist_ok=True)

# Regex pattern definitions; each field may have multiple alternatives.
PATTERNS: Dict[str, List[re.Pattern]] = {
    "product_name": [
        re.compile(r"Product Identifier\s*[:\-]?\s*(.+)", re.I),
        re.compile(r"^\s*Product Name\s*[:\-]?\s*(.+)$", re.I | re.M),
        re.compile(r"^\s*Trade Name\s*[:\-]?\s*(.+)$", re.I | re.M),
    ],
    "vendor": [
        re.compile(r"Manufacturer(?:/Supplier)?\s*[:\-]?\s*(.+)", re.I),
        re.compile(r"Company Name\s*[:\-]?\s*(.+)", re.I),
        re.compile(r"Supplier\s*[:\-]?\s*(.+)", re.I),
    ],
    "issue_date": [
        re.compile(r"(Revision|Issue|Date of issue|Version date)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.I),
        re.compile(r"(Prepared|Last revised)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.I),
    ],
    "dangerous_goods_class": [
        re.compile(r"\b(?:Dangerous\s+Goods\s*)?Class(?:/Division)?\s*[:\-]?\s*([0-9A-Za-z\.]+)\b", re.I),
    ],
    "un_number": [
        re.compile(r"\bUN\s*(\d{3,4})\b", re.I),
    ],
    "packing_group": [
        re.compile(r"Packing\s+Group\s*[:\-]?\s*(I{1,3}|II|III)\b", re.I),
    ],
    "subsidiary_risks": [
        re.compile(r"Subsidiary Risk[s]?\s*[:\-]?\s*(.+)", re.I),
    ],
    "cas_number": [
        re.compile(r"\bCAS(?: No\.| Number)?\s*[:\-]?\s*([0-9]{2,7}-[0-9]{2}-[0-9])", re.I),
    ],
    "hazardous_substance": [
        re.compile(r"Hazardous Substance\s*[:\-]?\s*(Yes|No)\b", re.I),
    ],
    "dangerous_good": [
        re.compile(r"Dangerous Goods?\s*[:\-]?\s*(Yes|No)\b", re.I),
    ],
    "description_section2": [
        re.compile(r"Section\s*2[^\n]*\n(.{0,800})", re.I | re.S),
    ],
}

DATE_FORMATS_IN = ["%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y-%m-%d", "%m/%d/%Y"]

# --------------------------------------------------
# DATA MODEL
# --------------------------------------------------
class ParsedRecord(BaseModel):
    product_name: Optional[str] = None
    vendor: Optional[str] = None
    quantity: Optional[str] = None
    location: Optional[str] = None
    cas_number: Optional[str] = None
    sds_available: str = "Yes"
    issue_date: Optional[str] = None  # normalized DD/MM/YYYY
    hazardous_substance: Optional[str] = None
    dangerous_good: Optional[str] = None
    dangerous_goods_class: Optional[str] = None
    description: Optional[str] = None
    packing_group: Optional[str] = None
    subsidiary_risks: Optional[str] = None
    consequence: Optional[str] = None
    likelihood: Optional[str] = None
    risk_rating: Optional[str] = None
    swp_requirement: Optional[str] = None
    comments_swp: Optional[str] = None
    barcode: Optional[str] = None

    def to_csv_row(self) -> List[str]:
        return [
            self.product_name or "",
            self.vendor or "",
            self.quantity or "",
            self.location or "",
            self.cas_number or "",
            self.sds_available,
            self.issue_date or "",
            self.hazardous_substance or "",
            self.dangerous_good or "",
            self.dangerous_goods_class or "",
            self.description or "",
            self.packing_group or "",
            self.subsidiary_risks or "",
            self.consequence or "",
            self.likelihood or "",
            self.risk_rating or "",
            self.swp_requirement or "",
            self.comments_swp or "",
            self.barcode or "",
        ]

# --------------------------------------------------
# UTILITIES
# --------------------------------------------------
def normalize_whitespace(txt: str) -> str:
    return re.sub(r"[\t\u00A0]+", " ", txt)


def find_first(patterns: List[re.Pattern], text: str) -> Optional[str]:
    for pat in patterns:
        m = pat.search(text)
        if m:
            groups = [g for g in m.groups() if g]
            value = groups[-1].strip() if groups else m.group(0).strip()
            return re.sub(r"[\s;:]+$", "", value)
    return None


def parse_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw_clean = raw.strip().replace("-", "/")
    for fmt in DATE_FORMATS_IN:
        try:
            dt = datetime.strptime(raw_clean, fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            continue
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw_clean)
    if m:
        day, month, year = m.groups()
        if len(year) == 2:
            year = "20" + year
        try:
            dt = datetime(int(year), int(month), int(day))
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            pass
    return raw_clean


def extract_description(text: str) -> Optional[str]:
    section2_block = find_first(PATTERNS["description_section2"], text)
    if not section2_block:
        return None
    lines = [l.strip() for l in section2_block.splitlines() if l.strip()]
    selected: List[str] = []
    for l in lines:
        if re.search(r"\bH\d{3}\b", l) or re.search(r"(Danger|Warning)\b", l):
            selected.append(l)
    if not selected:
        selected = lines[:3]
    out: List[str] = []
    seen = set()
    for s in selected:
        if s not in seen:
            seen.add(s)
            out.append(s)
    desc = "; ".join(out)[:800]
    desc = re.sub(r"\s*;\s*", "; ", desc)
    desc = re.sub(r"(; ){2,}", "; ", desc)
    return desc


def compute_risk_rating(consequence: Optional[str], likelihood: Optional[str]) -> Optional[str]:
    if not consequence or not likelihood:
        return None
    cons_map = {
        "insignificant": 1,
        "minor": 2,
        "moderate": 3,
        "major": 4,
        "severe": 5,
    }
    lik_map = {
        "rare": 1,
        "unlikely": 2,
        "possible": 3,
        "likely": 4,
        "almost certain": 5,
    }
    c = cons_map.get(consequence.strip().lower())
    l = lik_map.get(likelihood.strip().lower())
    if c is None or l is None:
        return None
    score = c * l
    if score <= 4:
        return f"Low ({score})"
    if score <= 9:
        return f"Medium ({score})"
    if score <= 16:
        return f"High ({score})"
    return f"Extreme ({score})"


def hash_pdf(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def extract_text_from_pdf(data: bytes) -> str:
    text_chunks: List[str] = []
    ocr_candidates: List[Image.Image] = [] if OCR_AVAILABLE else []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if OCR_AVAILABLE and len(t.strip()) < 30:
                try:
                    im = page.to_image(resolution=300).original
                    ocr_candidates.append(im)
                except Exception:
                    pass
            else:
                text_chunks.append(t)
    if ocr_candidates and OCR_AVAILABLE:
        logger.info(f"Running OCR on {len(ocr_candidates)} low-text pages")
        for im in ocr_candidates:
            try:
                ocr_text = pytesseract.image_to_string(im)  # type: ignore
                text_chunks.append(ocr_text)
            except Exception as e:
                logger.warning(f"OCR page failed: {e}")
    return "\n".join(text_chunks)


def infer_flags(record: ParsedRecord, text_norm: str) -> None:
    if not record.hazardous_substance:
        if re.search(r"Not classified as Hazardous", text_norm, re.I):
            record.hazardous_substance = "No"
        elif re.search(r"Classified as Hazardous|Hazardous according to", text_norm, re.I):
            record.hazardous_substance = "Yes"
    if not record.dangerous_good:
        if re.search(r"Not classified as Dangerous Goods", text_norm, re.I):
            record.dangerous_good = "No"
        elif re.search(r"Classified as Dangerous Goods|Dangerous Goods according to", text_norm, re.I) or record.dangerous_goods_class:
            record.dangerous_good = "Yes"
    if not record.packing_group:
        m = re.search(r"Packing\s+Group\s*(I{1,3}|II|III)\b", text_norm, re.I)
        if m:
            record.packing_group = m.group(1).upper()


def extract_fields(text: str) -> ParsedRecord:
    text_norm = normalize_whitespace(text)
    record = ParsedRecord()
    record.product_name = find_first(PATTERNS["product_name"], text_norm)
    record.vendor = find_first(PATTERNS["vendor"], text_norm)
    record.quantity = None  # not auto-extracted yet
    record.location = None  # not auto-extracted yet
    record.cas_number = find_first(PATTERNS["cas_number"], text_norm)
    raw_issue = find_first(PATTERNS["issue_date"], text_norm)
    record.issue_date = parse_date(raw_issue)
    record.hazardous_substance = find_first(PATTERNS["hazardous_substance"], text_norm)
    record.dangerous_good = find_first(PATTERNS["dangerous_good"], text_norm)
    record.dangerous_goods_class = find_first(PATTERNS["dangerous_goods_class"], text_norm)
    if record.dangerous_goods_class and 'ification' in record.dangerous_goods_class.lower():
        record.dangerous_goods_class = None
    record.packing_group = find_first(PATTERNS["packing_group"], text_norm)
    record.subsidiary_risks = find_first(PATTERNS["subsidiary_risks"], text_norm)
    record.description = extract_description(text_norm)
    infer_flags(record, text_norm)
    record.risk_rating = compute_risk_rating(record.consequence, record.likelihood)
    return record

# --------------------------------------------------
# CSV OUTPUT
# --------------------------------------------------
def append_record_to_csv(record: ParsedRecord, path: str = OUTPUT_CSV) -> None:
    new_row = record.to_csv_row()
    file_exists = os.path.isfile(path)

    if file_exists:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if record.barcode and row.get("Barcode") == record.barcode:
                    logger.info("Skipping duplicate based on barcode %s", record.barcode)
                    return

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(REGISTER_HEADERS)
        writer.writerow(new_row)

    logger.info("Appended record for barcode %s", record.barcode)

def record_to_register_row_dict(record: ParsedRecord) -> Dict[str, str]:
    return {h: v for h, v in zip(REGISTER_HEADERS, record.to_csv_row())}

# --------------------------------------------------
# FASTAPI APP
# --------------------------------------------------
app = FastAPI(title="ChemFetch SDS Parser", version="0.2.0")

import shutil

def configure_tesseract():
    if not OCR_AVAILABLE:
        return
    if shutil.which("tesseract"): return
    default_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
    if os.path.isfile(default_cmd):
        try:
            pytesseract.pytesseract.tesseract_cmd = default_cmd  # type: ignore
            logger.info("Configured explicit Tesseract path")
        except Exception as e:
            logger.warning(f"Failed to set explicit tesseract path: {e}")

configure_tesseract()

@app.get("/health/ocr")
def ocr_health():
    status: Dict[str, Any] = {
        "ocr_imported": OCR_AVAILABLE,
        "tesseract_in_path": bool(shutil.which("tesseract")),
    }
    if OCR_AVAILABLE:
        try:
            status["version"] = str(pytesseract.get_tesseract_version())  # type: ignore
        except Exception as e:
            status["error"] = str(e)
    return status

class ParseResponse(BaseModel):
    hash: str
    record: Dict[str, Any]
    csv_path: str

@app.post("/parse-sds", response_model=ParseResponse)
async def parse_sds(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    data = await file.read()
    if len(data) < 1000:
        raise HTTPException(status_code=400, detail="PDF appears too small / empty")
    try:
        text = extract_text_from_pdf(data)
    except Exception as e:
        logger.exception("PDF text extraction failed")
        raise HTTPException(status_code=500, detail=f"Failed to extract text: {e}")
    if not text.strip():
        raise HTTPException(status_code=422, detail="No extractable text in PDF (try OCR install)")
    record = extract_fields(text)
    # API mode does not set barcode; use CLI for barcode-based dedupe
    if not (record.product_name or record.vendor):
        raise HTTPException(status_code=422, detail="Could not detect minimum fields; tune patterns")
    try:
        append_record_to_csv(record)
    except Exception as e:
        logger.exception("CSV append failed")
        raise HTTPException(status_code=500, detail=f"CSV append failed: {e}")
    return ParseResponse(
        hash=hash_pdf(data),
        record=record_to_register_row_dict(record),
        csv_path=os.path.abspath(OUTPUT_CSV),
    )

# --------------------------------------------------
# CLI ENTRY POINT
# --------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Parse one or more SDS PDFs into the chemical register CSV")
    parser.add_argument("pdfs", nargs="+", help="PDF file paths")
    parser.add_argument("--csv", default=OUTPUT_CSV, help="Output CSV path")
    parser.add_argument("--json-out", help="Optional JSON dump of parsed records")
    parser.add_argument("--barcode", help="Barcode value to attach to all parsed records")
    args = parser.parse_args()

    parsed: List[Dict[str, Any]] = []
    for pdf_path in args.pdfs:
        with open(pdf_path, "rb") as f:
            data = f.read()
        logger.info(f"Processing {pdf_path} .")
        text = extract_text_from_pdf(data)
        rec = extract_fields(text)
        rec.barcode = args.barcode
        append_record_to_csv(rec, args.csv)
        parsed.append(record_to_register_row_dict(rec))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as jf:
            json.dump(parsed, jf, indent=2)
        logger.info(f"JSON written: {args.json_out}")
    logger.info(f"Done. CSV at {os.path.abspath(args.csv)}")
