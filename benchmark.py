#!/usr/bin/env python3
"""Benchmark invoice generation on synthetic data.

Creates random clients and invoices, then runs the real pipeline (CSV parsing,
validation, totals, PDF rendering) several times and reports median timings.
Run it on your own machine and use your numbers in the README.

    python benchmark.py --invoices 500 --repeat 3
"""
from __future__ import annotations

import argparse
import csv
import platform
import random
import statistics
import sys
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from invoice_generator import build_invoices, generate_pdfs

WORDS = [
    "Website design", "Hosting", "Consulting hours", "Logo design",
    "Print run", "Support plan", "SEO audit", "Maintenance",
]


def make_dataset(folder: Path, invoices: int, clients: int, seed: int) -> tuple[Path, Path, int]:
    rng = random.Random(seed)
    clients_path = folder / "clients.csv"
    items_path = folder / "line_items.csv"

    with clients_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["client_id", "name", "email", "address"])
        for i in range(1, clients + 1):
            writer.writerow([f"C{i:04d}", f"Client {i} Ltd", f"billing{i}@example.com", f"{i} Example Street"])

    line_count = 0
    with items_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["invoice_id", "client_id", "issue_date", "due_date", "description", "quantity", "unit_price"])
        for n in range(1, invoices + 1):
            issue = date(2026, 1, 1) + timedelta(days=rng.randint(0, 280))
            due = issue + timedelta(days=30)
            client_id = f"C{rng.randint(1, clients):04d}"
            for _ in range(rng.randint(1, 8)):
                writer.writerow([
                    f"INV-{n:05d}", client_id, issue.isoformat(), due.isoformat(),
                    rng.choice(WORDS), rng.randint(1, 20), f"{rng.uniform(5, 500):.2f}",
                ])
                line_count += 1
    return clients_path, items_path, line_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the invoice generator.")
    parser.add_argument("--invoices", type=int, default=500)
    parser.add_argument("--clients", type=int, default=50)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        clients_csv, items_csv, line_count = make_dataset(tmp_path, args.invoices, args.clients, args.seed)

        parse_times, render_times = [], []
        generated = 0
        for run in range(args.repeat):
            out = tmp_path / f"run{run}"
            t0 = perf_counter()
            invoices, errors = build_invoices(clients_csv, items_csv)
            t1 = perf_counter()
            generate_pdfs(invoices, out, company="Benchmark Co", tax_rate=Decimal("0.10"), currency="USD")
            t2 = perf_counter()
            if errors:
                print("Unexpected validation errors in synthetic data:", errors[:3], file=sys.stderr)
                return 1
            generated = len(invoices)
            parse_times.append(t1 - t0)
            render_times.append(t2 - t1)

    totals = [p + r for p, r in zip(parse_times, render_times)]
    median_total = statistics.median(totals)

    print(f"Machine:    {platform.machine()}, {platform.system()}, Python {platform.python_version()}")
    print(f"Dataset:    {generated} invoices, {line_count} line items, {args.clients} clients")
    print(f"Runs:       {args.repeat} (median reported)")
    print(f"Parse + validate + totals: {statistics.median(parse_times):.3f} s")
    print(f"Render PDFs + summary:     {statistics.median(render_times):.3f} s")
    print(f"Total:                     {median_total:.3f} s (min {min(totals):.3f}, max {max(totals):.3f})")
    print(f"Throughput:                {generated / median_total:,.0f} invoices/s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
