# register.py

import os
import csv
import logging
from typing import List

logger = logging.getLogger(__name__)

REGISTER_HEADERS: List[str] = [
    "Product Name",
    "Vendor / Manufacturer",
    "Quantity",
    "Location",
    "CAS Number",
    "Last Revision",
    "Barcode",
]
OUTPUT_CSV = "chemical_register.csv"

class ParsedRecord:
    def __init__(self, product_name: str, vendor: str, quantity: str,
                 location: str, cas_number: str, last_revision: str,
                 barcode: str):
        self.product_name = product_name
        self.vendor = vendor
        self.quantity = quantity
        self.location = location
        self.cas_number = cas_number
        self.last_revision = last_revision
        self.barcode = barcode

    def to_csv_row(self) -> List[str]:
        return [
            self.product_name,
            self.vendor,
            self.quantity,
            self.location,
            self.cas_number,
            self.last_revision,
            self.barcode,
        ]

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
