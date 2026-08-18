"""Batch accuracy run — extracts a folder of bills and writes a JSON report.

    bench --site fh.localhost execute fountainhead.bill_ocr.accuracy.run \\
        --kwargs "{'folder': '/mnt/d/.../Chetan Sir', 'out': '/tmp/accuracy.json'}"

Scores what can be scored **without ground truth**, by arithmetic:

  * reconciles      — taxable + taxes + round-off equals the printed grand total
  * lines_sum       — the line amounts add up to the taxable value
  * line_math       — every line's qty x rate equals its printed amount
  * supplier_match  — resolved to an existing Supplier, and by what method

Field-level correctness still needs a human (or a second reader) comparing against
the bill itself; this measures whether the numbers hang together, which is the
thing that decides if a bill can be trusted into a draft.
"""

import json
import mimetypes
import pathlib
import time

from fountainhead.bill_ocr import extract, match, normalize

TOLERANCE = 1.0


def run(folder=None, paths=None, out="/tmp/accuracy.json"):
	files = []
	if folder:
		p = pathlib.Path(folder)
		files = sorted(
			f for f in p.iterdir()
			if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".pdf", ".webp")
		)
	if paths:
		files += [pathlib.Path(x) for x in paths]

	results = []
	for f in files:
		results.append(_one(f))
		print(f"  done: {f.name}")

	pathlib.Path(out).write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
	print(f"\nwrote {len(results)} results to {out}")
	return out


def _one(path):
	rec = {"file": path.name, "size_mb": round(path.stat().st_size / 1024 / 1024, 2)}
	data_bytes = path.read_bytes()
	mime = mimetypes.guess_type(path.name)[0]

	started = time.time()
	try:
		raw, usage = extract.read_bill(data_bytes, mime)
	except Exception as e:
		rec["error"] = f"{type(e).__name__}: {e}"
		return rec
	rec["seconds"] = round(time.time() - started, 1)
	rec["input_tokens"] = usage.get("input_tokens")
	rec["output_tokens"] = usage.get("output_tokens")

	clean, notes = normalize.normalize(raw)
	rec["notes"] = notes

	rec["vendor"] = clean.get("vendorName")
	rec["invoice_no"] = clean.get("invoiceNumber")
	rec["invoice_date"] = clean.get("invoiceDate")
	rec["buyer"] = clean.get("targetCompany")
	rec["category"] = clean.get("expenseCategory")
	rec["taxable"] = clean.get("taxableValue")
	rec["cgst"] = clean.get("cgstAmount")
	rec["sgst"] = clean.get("sgstAmount")
	rec["igst"] = clean.get("igstAmount")
	rec["round_off"] = clean.get("roundOff")
	rec["total"] = clean.get("totalInvoiceValue")

	lines = clean.get("lines") or []
	rec["line_count"] = len(lines)
	rec["lines"] = [
		{
			"desc": (l.get("description") or "")[:70],
			"qty": l.get("quantity"),
			"rate": l.get("rate"),
			"amount": l.get("lineAmount"),
		}
		for l in lines
	]

	# --- arithmetic checks, no ground truth needed -------------------------
	components = sum(
		v for v in [
			clean.get("taxableValue"), clean.get("cgstAmount"), clean.get("sgstAmount"),
			clean.get("igstAmount"), clean.get("cessAmount"), clean.get("roundOff"),
		] if v is not None
	)
	others = sum(c.get("amount") or 0 for c in (clean.get("otherCharges") or []))
	total = clean.get("totalInvoiceValue")
	rec["reconciles"] = (
		total is not None and abs(round(components + others - total, 2)) <= TOLERANCE
	)
	rec["reconcile_gap"] = None if total is None else round(components + others - total, 2)

	amounts = [l.get("lineAmount") for l in lines if l.get("lineAmount") is not None]
	taxable = clean.get("taxableValue")
	if amounts and taxable is not None:
		rec["lines_sum"] = abs(round(sum(amounts) - taxable, 2)) <= TOLERANCE
		rec["lines_sum_gap"] = round(sum(amounts) - taxable, 2)
	else:
		rec["lines_sum"] = None
		rec["lines_sum_gap"] = None

	bad = 0
	for l in lines:
		q, r, a = l.get("quantity"), l.get("rate"), l.get("lineAmount")
		if q and r is not None and a is not None and abs(round(q * r - a, 2)) > TOLERANCE:
			bad += 1
	rec["line_math_ok"] = (bad == 0)
	rec["line_math_bad"] = bad

	rec["fields_present"] = sum(
		1 for k in ("vendor", "invoice_no", "invoice_date", "taxable", "total") if rec.get(k)
	)

	# --- master data resolution -------------------------------------------
	# Match on the English rendering first, exactly as api.py does. Measuring a
	# different code path than the one that ships produces numbers that are worse
	# than useless — the first re-run reported two suppliers "regressing" purely
	# because this line was left behind when api.py moved to vendorNameEn.
	rec["vendor_en"] = clean.get("vendorNameEn")
	sup = match.match_supplier(
		clean.get("vendorNameEn") or clean.get("vendorName"), clean.get("vendorGstin")
	)
	rec["supplier"] = sup["supplier"]
	rec["supplier_method"] = sup["method"]
	rec["supplier_confidence"] = sup["confidence"]
	rec["supplier_candidates"] = [c["supplier_name"] for c in (sup.get("candidates") or [])[:3]]

	grp = match.suggest_item_group(sup["supplier"])
	rec["item_group_suggested"] = grp["item_group"] if grp else None
	rec["item_group_share"] = grp["share"] if grp else None

	items = match.match_items(lines, sup["supplier"])
	rec["lines_with_candidates"] = sum(1 for i in items if i.get("candidates"))
	rec["top_candidates"] = [
		((i.get("candidates") or [{}])[0].get("item_name") if i.get("candidates") else None)
		for i in items
	]
	return rec
