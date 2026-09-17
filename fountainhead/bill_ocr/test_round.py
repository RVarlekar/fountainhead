"""The answer-keyed test round: run a folder of real bill scans through the
whole pipeline and score the result against what ERPNext already booked.

    bench --site <site> execute fountainhead.bill_ocr.test_round.run \
        --kwargs "{'folder': '/mnt/d/.../Sample Bills (Provided by Chetan Shah)', \
                   'out_md': '/mnt/d/Fountainhead ERPNext/Docs/TEST_ROUND_RESULTS.md'}"

Every bill in the folder was already entered by accounts (confirmed 26 Aug), so
supplier/bill-no/total can be compared against the actual entries — WHERE the
local database is fresh enough to contain them (the local restore is dated;
misses are reported as "no key", never as failures). Each read costs one API
call; cached bills are free on re-runs.
"""

import json
import os

import frappe
from frappe.utils import flt

from fountainhead.bill_ocr import api


def run(folder, out_md=None, limit=0):
	files = sorted(
		f for f in os.listdir(folder)
		if f.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp"))
	)
	if limit:
		files = files[: int(limit)]
	print(f"{len(files)} scans in {folder}")

	rows = []
	for i, fname in enumerate(files, 1):
		path = os.path.join(folder, fname)
		print(f"[{i}/{len(files)}] {fname} …", flush=True)
		row = {"file": fname}
		try:
			file_url = _ensure_file(path, fname)
			payload = api._cached_payload(file_url)
			row["cached"] = payload is not None
			if payload is None:
				payload = api._run_extraction(file_url, "Purchase Receipt")
				api._store_cache(file_url, payload)
			payload = api._serve(payload, None)

			f = payload.get("fields") or {}
			p = payload.get("projection") or {}
			t = payload.get("totals") or {}
			row.update({
				"supplier": f.get("supplier"),
				"vendor_on_bill": payload.get("vendor_name_english") or payload.get("vendor_name_on_bill"),
				"bill_no": f.get("bill_no"),
				"bill_date": f.get("bill_date"),
				"grand_total": t.get("grand_total"),
				"lines": len(payload.get("items") or []),
				"unmatched_lines": sum(
					1 for it in payload.get("items") or []
					if not it.get("item_code") and not it.get("candidates")
				),
				"tallies": bool(p.get("tallies")),
				"folded_total": p.get("items_total") if p.get("gst_folded_into_rates") else None,
				"warnings": sum(1 for n in payload.get("notes") or [] if str(n).startswith("⚠")),
			})
			row.update(_answer_key(row))
		except Exception as e:
			row["error"] = str(e)[:200]
		rows.append(row)
		frappe.db.commit()  # keep each cached reading even if a later one fails

	report = _report(rows)
	print(report)
	if out_md:
		with open(out_md, "w", encoding="utf-8") as fh:
			fh.write(report)
		print(f"written: {out_md}")
	return {"rows": rows}


def _ensure_file(path, fname):
	"""The scan as a private File in the site — reused when already uploaded."""
	existing = frappe.db.get_value("File", {"file_name": fname, "is_private": 1}, "file_url")
	if existing:
		return existing
	with open(path, "rb") as fh:
		content = fh.read()
	doc = frappe.get_doc({
		"doctype": "File",
		"file_name": fname,
		"is_private": 1,
		"content": content,
	})
	doc.save(ignore_permissions=True)
	return doc.file_url


def _answer_key(row):
	"""The entry accounts actually made for this bill, when the local data has it."""
	out = {"key": None, "key_total": None, "total_match": None, "date_match": None}
	if not row.get("supplier") or not row.get("bill_no"):
		return out
	for doctype in ("Purchase Invoice", "Purchase Receipt"):
		hit = frappe.db.get_value(
			doctype,
			{"supplier": row["supplier"], "bill_no": row["bill_no"], "docstatus": ["<", 2]},
			["name", "grand_total", "bill_date"],
			as_dict=True,
		)
		if hit:
			out["key"] = f"{doctype} {hit.name}"
			out["key_total"] = flt(hit.grand_total)
			if row.get("grand_total") is not None:
				out["total_match"] = abs(flt(row["grand_total"]) - flt(hit.grand_total)) <= 1
			if row.get("bill_date") and hit.bill_date:
				out["date_match"] = str(row["bill_date"]) == str(hit.bill_date)
			break
	return out


def _report(rows):
	total = len(rows)
	errors = [r for r in rows if r.get("error")]
	read = [r for r in rows if not r.get("error")]
	tallies = sum(1 for r in read if r.get("tallies"))
	supplier_ok = sum(1 for r in read if r.get("supplier"))
	keyed = [r for r in read if r.get("key")]
	total_ok = sum(1 for r in keyed if r.get("total_match"))
	date_ok = sum(1 for r in keyed if r.get("date_match"))
	date_known = sum(1 for r in keyed if r.get("date_match") is not None)

	lines = [
		"# Test round — answer-keyed corpus, local run",
		"",
		f"**Corpus:** {total} scans · **read cleanly:** {len(read)} · **errors:** {len(errors)}",
		f"**Supplier matched:** {supplier_ok}/{len(read)} · **tally green:** {tallies}/{len(read)}",
		f"**Answer key found locally:** {len(keyed)}/{len(read)} "
		f"(the local restore predates some entries — missing keys are a data gap, not a failure)",
		f"**Grand total matches the booked entry:** {total_ok}/{len(keyed)}",
		f"**Bill date matches the booked entry:** {date_ok}/{date_known} (the 26 Aug demo's date-capture question)",
		"",
		"| # | File | Supplier | Bill no | Date | Total | Tally | Lines (unmatched) | Key | Total= | Date= |",
		"|---|---|---|---|---|---|---|---|---|---|---|",
	]
	for i, r in enumerate(rows, 1):
		if r.get("error"):
			lines.append(f"| {i} | {r['file']} | — | — | — | — | ❌ ERROR: {r['error'][:60]} | | | | |")
			continue
		mark = lambda v: "—" if v is None else ("✅" if v else "❌")
		lines.append(
			f"| {i} | {r['file']} | {r.get('supplier') or '—'} | {r.get('bill_no') or '—'} "
			f"| {r.get('bill_date') or '—'} | {r.get('grand_total') or '—'} "
			f"| {'✅' if r.get('tallies') else '❌'} | {r.get('lines')} ({r.get('unmatched_lines')}) "
			f"| {r.get('key') or '—'} | {mark(r.get('total_match'))} | {mark(r.get('date_match'))} |"
		)
	lines.append("")
	lines.append("*Generated by `fountainhead.bill_ocr.test_round.run` — cached readings are reused free on re-runs.*")
	return "\n".join(lines)
