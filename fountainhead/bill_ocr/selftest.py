"""Developer self-test — runs the pipeline against real bill files on disk.

Not part of the feature. It exists so the extraction can be checked end to end
on a real bill after a change, on any environment, without clicking through the
UI. It makes live API calls, so it costs a few rupees per bill.

    bench --site fh.localhost execute fountainhead.bill_ocr.selftest.run
    bench --site fh.localhost execute fountainhead.bill_ocr.selftest.run \\
        --kwargs "{'paths': ['/path/to/one.pdf']}"
"""

import mimetypes
import pathlib
import time

from fountainhead.bill_ocr import extract, match, normalize

DEFAULT_PATHS = [
	"/mnt/d/Fountainhead ERPNext/Meetings/Resources/Stationery/Sample Bills/3836.pdf",
	"/mnt/d/Fountainhead ERPNext/Meetings/Resources/Chetan Sir/IMG_20260812_150134.jpg",
]


def run(paths=None):
	paths = paths or DEFAULT_PATHS
	for path in paths:
		_one(path)


def _one(path):
	p = pathlib.Path(path)
	if not p.exists():
		print(f"MISSING: {path}")
		return

	data = p.read_bytes()
	mime = mimetypes.guess_type(p.name)[0]
	print("=" * 74)
	print(f"{p.name}   {len(data) / 1024 / 1024:.1f} MB   {mime}")
	print("=" * 74)

	started = time.time()
	try:
		raw, usage = extract.read_bill(data, mime)
	except Exception as e:
		print(f"  EXTRACTION FAILED: {type(e).__name__}: {e}")
		return
	elapsed = time.time() - started

	clean, notes = normalize.normalize(raw)

	print(f"  time       : {elapsed:.1f}s")
	print(f"  tokens     : in={usage.get('input_tokens')}  out={usage.get('output_tokens')}")
	print(f"  vendor     : {clean.get('vendorName')}")
	print(f"  invoice no : {clean.get('invoiceNumber')}")
	print(f"  date       : {clean.get('invoiceDate')}")
	print(f"  taxable    : {clean.get('taxableValue')}")
	print(f"  cgst/sgst  : {clean.get('cgstAmount')} / {clean.get('sgstAmount')}")
	print(f"  round off  : {clean.get('roundOff')}")
	print(f"  TOTAL      : {clean.get('totalInvoiceValue')}")
	print(f"  buyer      : {clean.get('targetCompany')}")
	print(f"  category   : {clean.get('expenseCategory')}")

	lines = clean.get("lines") or []
	print(f"  lines      : {len(lines)}")
	for line in lines[:5]:
		desc = str(line.get("description") or "")[:44]
		print(f"       {desc:44s} qty={line.get('quantity')} rate={line.get('rate')} amt={line.get('lineAmount')}")
	if len(lines) > 5:
		print(f"       ... and {len(lines) - 5} more")

	supplier = match.match_supplier(clean.get("vendorName"), clean.get("vendorGstin"))
	print(f"  supplier   : {supplier['supplier']}   [{supplier['method']}, {supplier['confidence']}%]")
	for c in (supplier.get("candidates") or [])[:3]:
		print(f"       candidate  {str(c['supplier_name'])[:44]:44s} {c['score']}%")

	print(f"  item group : {match.suggest_item_group(supplier['supplier'])}")

	if notes:
		print("  notes:")
		for n in notes:
			print(f"       ! {n}")
	print()
