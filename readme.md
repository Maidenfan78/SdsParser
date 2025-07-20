# ChemFetch SDS Parser

A lightweight FastAPI service and CLI tool to parse **Safety Data Sheets (SDS / MSDS)** (PDF) into a normalized *Chemical Register* CSV.

It extracts key fields (product name, manufacturer, issue date, dangerous goods class, etc.) using regex heuristics and (optionally) OCR for scanned image-only PDFs (Tesseract). Designed for iterative refinement: add or tune patterns as you encounter new supplier formats.

> **Status:** Early prototype. Expect to refine regex patterns per supplier.

---

## ✨ Features

- **/parse-sds** endpoint (multipart upload) → JSON + CSV append.
- **OCR fallback**: pdfplumber for text layer → Tesseract (via pytesseract) for low‑text pages.
- **Heuristic extraction**: Configurable regex patterns; first match wins.
- **Section 2 hazard statement summarizer** for description field.
- **Risk placeholders** (Consequence, Likelihood, Risk Rating) ready for future integration.
- **CSV auto-create** with consistent header ordering.
- **/health/ocr** diagnostics endpoint (checks import, path, version).
- **CLI batch mode** for bulk conversion.

---

## 🗂 Output CSV Schema

Default path: `data/chemical_register.csv`

| Column                                | Description                                                 |
| ------------------------------------- | ----------------------------------------------------------- |
| Product Name                          | Product / Trade identifier                                  |
| Vendor / Manufacturer                 | Supplier / manufacturer name                                |
| Quantity                              | (Optional) Local stored quantity (not auto-extracted yet)   |
| Location                              | (Optional) Storage location (manual / future enhancement)   |
| SDS Available                         | Always `Yes` (placeholder)                                  |
| Issue Date (DD/MM/YYYY)               | Normalized issue / revision date                            |
| Hazardous Substance                   | Yes/No if pattern matches (currently only explicit formats) |
| Dangerous Good                        | Yes/No if pattern matches (explicit only)                   |
| Dangerous Goods Class                 | e.g. `3` for flammable liquid                               |
| Description                           | Signal word + hazard statements (Section 2 heuristic)       |
| Packing group                         | I / II / III if found                                       |
| Subsidiary Risk(s)                    | Additional transport risks                                  |
| Consequence                           | Placeholder (manual or later risk matrix)                   |
| Likelihood                            | Placeholder                                                 |
| Risk Rating                           | Computed from consequence x likelihood (if both present)    |
| Safe Work Procedure (SWP) Requirement | Placeholder                                                 |
| Comments/SWP                          | Placeholder                                                 |

---

## 🏗 Project Structure (simple)

```
SdsParser/
├── sds_parser.py        # Main FastAPI + extraction logic + CLI
├── data/                # Output CSV folder (auto-created)
└── README.md            # This file
```

Add tests / pattern config files as the project grows.

---

## 🔧 Installation

1. **Clone repo** (after you push this project to GitHub):
   ```bash
   git clone https://github.com/<your-user>/<your-repo>.git
   cd <your-repo>
   ```
2. **Create virtual environment** (Windows PowerShell example):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   ```
3. **Install core dependencies:**
   ```powershell
   pip install fastapi uvicorn[standard] pdfplumber pydantic python-multipart pytesseract pillow regex
   ```
   *Add **`opencv-python`** + **`pdf2image`** if you later need more robust OCR preprocessing.*
4. **Install Tesseract executable** (Windows):
   - Using winget: `winget install UB-Mannheim.TesseractOCR`
   - Or Chocolatey: `choco install tesseract`
   - Ensure `C:\Program Files\Tesseract-OCR` is on `PATH` (restart shell) or set explicit path in code.

---

## ▶️ Running the API

```powershell
uvicorn sds_parser:app --reload
```

Open Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

Use **POST /parse-sds** → *Try it out* → upload `SampleSDS.pdf`.

**OCR Health:** [http://127.0.0.1:8000/health/ocr](http://127.0.0.1:8000/health/ocr)

Example health response:

```json
{
  "ocr_imported": true,
  "tesseract_in_path": true,
  "version": "5.5.0.20241111"
}
```

---

## 🧪 CLI Batch Mode

Process multiple PDFs directly (bypasses HTTP):

```powershell
python sds_parser.py file1.pdf file2.pdf --csv data/chemical_register.csv --json-out parsed.json
```

Outputs:

- Appends/creates `chemical_register.csv`.
- Optional machine-readable `parsed.json`.

---

## 🧠 Extraction Logic Overview

1. **Load PDF** (pdfplumber) page by page.
2. **Low text density pages** ( < \~30 chars ) flagged for OCR queue if OCR available.
3. **OCR pass** (Tesseract) on queued images; append extracted text.
4. **Normalization** (collapse tabs / non-breaking spaces).
5. **Pattern matching** (first match wins per field).
6. **Hazard Description**: Section 2 block → hazard statements (Hxxx) & signal word lines.
7. **Date Parsing**: Attempts multiple formats → unified `DD/MM/YYYY`.
8. **Risk Rating**: Placeholder scoring matrix if consequence & likelihood later populated.

---

## 🛠 Customizing Patterns

Edit the `PATTERNS` dict in `sds_parser.py`. For each new supplier:

- Parse once.
- If field missing, inspect raw extracted text (add temporary `print(text[:2000])` or log to file).
- Craft a new regex capturing just the desired portion.
- Order matters: **most specific first**.

**Tip:** Keep a small test corpus; add a basic unit test per new pattern to avoid regressions.

---

## ⚠️ Limitations & Next Steps

| Area                  | Current State                                             | Improvement Ideas                                        |
| --------------------- | --------------------------------------------------------- | -------------------------------------------------------- |
| Hazardous/DG flags    | Only explicit `Yes/No` lines                              | Phrase inference ("Classified as Hazardous ...")         |
| Dangerous Goods Class | May catch fragments like `ification` in current code base | Stricter regex (add boundary & exclude 'classification') |
| Quantity/Location     | Not auto-extracted                                        | Provide metadata mapping file or UI input                |
| OCR Accuracy          | Basic (no preprocessing)                                  | Add OpenCV thresholding / deskew                         |
| Config Management     | Patterns hard-coded                                       | External YAML/JSON + hot reload                          |
| Testing               | None yet                                                  | Pytest with fixture PDFs & text snippets                 |
| Risk Matrix           | Placeholder only                                          | UI or config-driven scoring inputs                       |

---

## 🧰 Optional Enhancements

- **Pattern Config File:** `patterns.yml` loaded on startup.
- **Confidence Scoring:** Count pattern hits / fallback usage.
- **Duplicate Detection:** Add PDF hash & timestamp columns.
- **Dockerization:** Lightweight container for deployment.
- **Front-end:** React or simple HTML for manual validation & edits.

---

## 🐳 (Optional) Quick Dockerfile (Example)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get update && apt-get install -y tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*
COPY sds_parser.py ./
EXPOSE 8000
CMD ["uvicorn", "sds_parser:app", "--host", "0.0.0.0", "--port", "8000"]
```

> For OCR to work in the container, add any needed language packs (`apt-get install -y tesseract-ocr-eng`).

---

## 📦 Example `requirements.txt` (curated)

```
fastapi
uvicorn[standard]
pdfplumber
pydantic
python-multipart
pytesseract
pillow
regex
python-dateutil
rich
```

*(Add **`opencv-python`**, **`pdf2image`**, **`PyPDF2`**, or **`pandas`** only if required.)*

---

## 🚀 Deployment Tips

| Environment | Notes                                                |
| ----------- | ---------------------------------------------------- |
| Local (dev) | `--reload` for code changes; verbose logging         |
| Docker      | Ensure Tesseract & (if needed) Poppler installed     |
| Server / VM | Set `CHEMFETCH_REGISTER_CSV` env var for custom path |
| CI Tests    | Use small fixture PDFs; mock OCR for speed           |

---

## 🔍 Health & Debugging

- `` – Check OCR status/version.
- Log a problematic PDF’s raw text to a temp file to design new patterns.
- If OCR not triggering: verify `tesseract --version` and that the code calls fallback path.

---

## 🤝 Contributing

1. Fork & branch (`feature/pattern-un-number`).
2. Add or adjust regex patterns + unit test.
3. Update README if schema changes.
4. Pull request with description + sample lines from SDS justifying new pattern.

---

## 🛡 License

Choose one (e.g. MIT). Example:

```
MIT License – see LICENSE file for details.
```

---

## 🙋 FAQ

**Q:** Why did a field come back empty?\
**A:** No pattern matched the supplier’s phrasing—add one & retest.

**Q:** Why is Dangerous Goods Class wrong (e.g. `ification`)?\
**A:** Regex too loose; tighten boundary (see Improvements section).

**Q:** OCR not working for scanned SDS?\
**A:** Ensure Tesseract executable is installed & on PATH or supply explicit path.

**Q:** Can I store multiple registers?\
**A:** Set `CHEMFETCH_REGISTER_CSV` env var to another file path per run.

---

## 📬 Contact / Maintainer

Add your contact or GitHub handle here once repo is public.

---

Happy parsing! Refine, test, and iterate over real SDS samples to reach production reliability.

