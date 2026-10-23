#!/usr/bin/env python3
"""Generate one PDF invoice per invoice_id from a clients CSV and a line-items CSV.

Example:
    python invoice_generator.py --clients data/clients.csv --items data/line_items.csv --out output
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CENT = Decimal("0.01")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
CLIENT_COLUMNS = ("client_id", "name", "email", "address")
ITEM_COLUMNS = ("invoice_id", "client_id", "issue_date", "due_date", "description", "quantity", "unit_price")


@dataclass(frozen=True)
class Client:
    client_id: str
    name: str
    email: str
    address: str


@dataclass(frozen=True)
class LineItem:
    description: str
    quantity: Decimal
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Invoice:
    invoice_id: str
    client: Client
    issue_date: date
    due_date: date
    items: list[LineItem] = field(default_factory=list)

    @property
    def subtotal(self) -> Decimal:
        return sum((item.amount for item in self.items), Decimal("0.00"))

    def tax(self, rate: Decimal) -> Decimal:
        return (self.subtotal * rate).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------- loading and validation ----------

def _cell(row: dict, key: str) -> str:
    return (row.get(key) or "").strip()


def _check_columns(path: Path, fieldnames, required) -> None:
    missing = [c for c in required if c not in (fieldnames or [])]
    if missing:
        raise ValueError(f"{path.name} is missing required column(s): {', '.join(missing)}")


def _parse_decimal(text: str, name: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{name} is not a number: {text!r}") from None
    if not value.is_finite():
        raise ValueError(f"{name} must be a finite number: {text!r}")
    return value


def format_percent(rate: Decimal) -> str:
    """Show a tax rate as a percent without rounding it: 0.075 -> '7.5', 0.10 -> '10'."""
    return f"{(rate * 100).normalize():f}"


def _parse_date(text: str, name: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{name} must be YYYY-MM-DD, got {text!r}") from None


def load_clients(path: Path) -> tuple[dict[str, Client], list[str]]:
    clients: dict[str, Client] = {}
    errors: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        _check_columns(path, reader.fieldnames, CLIENT_COLUMNS)
        for line_no, row in enumerate(reader, start=2):
            client_id = _cell(row, "client_id")
            if not SAFE_ID.match(client_id):
                errors.append(f"{path.name} line {line_no}: invalid client_id {client_id!r}")
            elif client_id in clients:
                errors.append(f"{path.name} line {line_no}: duplicate client_id {client_id!r}")
            elif not _cell(row, "name"):
                errors.append(f"{path.name} line {line_no}: client {client_id!r} has no name")
            else:
                clients[client_id] = Client(
                    client_id, _cell(row, "name"), _cell(row, "email"), _cell(row, "address")
                )
    return clients, errors


def load_items(path: Path, clients: dict[str, Client]) -> tuple[dict[str, Invoice], list[str]]:
    """Group line items into invoices.

    If any row of an invoice is invalid, the whole invoice is skipped. A partial
    invoice would have a wrong total, which is worse than no invoice.
    """
    invoices: dict[str, Invoice] = {}
    rejected: set[str] = set()
    errors: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        _check_columns(path, reader.fieldnames, ITEM_COLUMNS)
        for line_no, row in enumerate(reader, start=2):
            where = f"{path.name} line {line_no}"
            invoice_id = _cell(row, "invoice_id")
            try:
                if not SAFE_ID.match(invoice_id):
                    raise ValueError(f"invalid invoice_id {invoice_id!r}")
                client = clients.get(_cell(row, "client_id"))
                if client is None:
                    raise ValueError(f"unknown client_id {_cell(row, 'client_id')!r}")
                description = _cell(row, "description")
                if not description:
                    raise ValueError("description is empty")
                quantity = _parse_decimal(_cell(row, "quantity"), "quantity")
                unit_price = _parse_decimal(_cell(row, "unit_price"), "unit_price")
                if quantity <= 0:
                    raise ValueError("quantity must be greater than 0")
                if unit_price < 0:
                    raise ValueError("unit_price cannot be negative")
                issue = _parse_date(_cell(row, "issue_date"), "issue_date")
                due = _parse_date(_cell(row, "due_date"), "due_date")
                if due < issue:
                    raise ValueError("due_date is before issue_date")
            except ValueError as exc:
                errors.append(f"{where}: {exc}")
                if invoice_id:
                    rejected.add(invoice_id)
                continue

            invoice = invoices.get(invoice_id)
            if invoice is None:
                invoice = invoices[invoice_id] = Invoice(invoice_id, client, issue, due)
            elif (invoice.client.client_id, invoice.issue_date, invoice.due_date) != (
                client.client_id, issue, due,
            ):
                errors.append(f"{where}: client or dates differ from other lines of {invoice_id!r}")
                rejected.add(invoice_id)
                continue
            invoice.items.append(LineItem(description, quantity, unit_price))

    for invoice_id in rejected:
        invoices.pop(invoice_id, None)
    return invoices, errors


def build_invoices(clients_path: Path, items_path: Path) -> tuple[list[Invoice], list[str]]:
    clients, errors = load_clients(clients_path)
    invoices, item_errors = load_items(items_path, clients)
    return sorted(invoices.values(), key=lambda inv: inv.invoice_id), errors + item_errors


# ---------- rendering ----------

def render_pdf(invoice: Invoice, out_dir: Path, *, company: str, tax_rate: Decimal, currency: str) -> Path:
    styles = getSampleStyleSheet()
    body = styles["Normal"]
    path = out_dir / f"{invoice.invoice_id}.pdf"
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Invoice {invoice.invoice_id}",
        author=company,
    )
    c = invoice.client
    story = [
        Paragraph(f"<b>{escape(company)}</b>", styles["Heading2"]),
        Paragraph(f"INVOICE {escape(invoice.invoice_id)}", styles["Title"]),
        Paragraph(
            f"<b>Bill to</b><br/>{escape(c.name)}<br/>{escape(c.address)}<br/>{escape(c.email)}", body
        ),
        Spacer(1, 6 * mm),
        Paragraph(
            f"Issue date: {invoice.issue_date.isoformat()} &nbsp;&nbsp;&nbsp; "
            f"Due date: {invoice.due_date.isoformat()}",
            body,
        ),
        Spacer(1, 8 * mm),
    ]

    rows = [["Description", "Qty", f"Unit price ({currency})", f"Amount ({currency})"]]
    for item in invoice.items:
        rows.append([
            Paragraph(escape(item.description), body),
            f"{item.quantity.normalize():f}",
            f"{item.unit_price:,.2f}",
            f"{item.amount:,.2f}",
        ])

    subtotal = invoice.subtotal
    tax = invoice.tax(tax_rate)
    rows += [
        ["", "", "Subtotal", f"{subtotal:,.2f}"],
        ["", "", f"Tax ({format_percent(tax_rate)}%)", f"{tax:,.2f}"],
        ["", "", "Total", f"{subtotal + tax:,.2f}"],
    ]
    n = len(rows)
    table = Table(rows, colWidths=[92 * mm, 16 * mm, 32 * mm, 32 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, n - 4), 0.25, colors.lightgrey),
        ("LINEABOVE", (2, n - 3), (-1, n - 3), 0.75, colors.grey),
        ("FONTNAME", (2, n - 1), (-1, n - 1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    doc.build(story)
    return path


def generate_pdfs(
    invoices: list[Invoice], out_dir: Path, *, company: str, tax_rate: Decimal, currency: str
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        render_pdf(inv, out_dir, company=company, tax_rate=tax_rate, currency=currency)
        for inv in invoices
    ]
    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["invoice_id", "client", "issue_date", "due_date", "subtotal", "tax", "total"])
        for inv in invoices:
            sub, tax = inv.subtotal, inv.tax(tax_rate)
            writer.writerow([
                inv.invoice_id, inv.client.name, inv.issue_date.isoformat(), inv.due_date.isoformat(),
                f"{sub:.2f}", f"{tax:.2f}", f"{sub + tax:.2f}",
            ])
    return paths


# ---------- command line ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate PDF invoices from CSV files.")
    parser.add_argument("--clients", type=Path, required=True, help="clients CSV")
    parser.add_argument("--items", type=Path, required=True, help="line items CSV")
    parser.add_argument("--out", type=Path, default=Path("output"), help="output folder")
    parser.add_argument("--company", default="Your Company", help="company name shown on invoices")
    parser.add_argument("--tax-percent", default="0", help="tax rate as a percent, e.g. 10")
    parser.add_argument("--currency", default="USD", help="currency label shown on invoices")
    args = parser.parse_args(argv)

    try:
        tax_percent = _parse_decimal(args.tax_percent, "--tax-percent")
    except ValueError as exc:
        parser.error(str(exc))
    if tax_percent < 0:
        parser.error("--tax-percent cannot be negative")
    tax_rate = tax_percent / 100

    start = time.perf_counter()
    try:
        invoices, errors = build_invoices(args.clients, args.items)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    generate_pdfs(invoices, args.out, company=args.company, tax_rate=tax_rate, currency=args.currency)
    elapsed = time.perf_counter() - start

    print(f"Generated {len(invoices)} invoice(s) in {elapsed:.2f} s -> {args.out}/")
    if errors:
        print(f"\n{len(errors)} problem(s) found. Invoices with a bad row were skipped:")
        for message in errors:
            print(f"  - {message}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
