"""One-off operational tools. Run via `bench execute`, never from the UI.

Currently: the vendor bank-details importer that fills the Supplier bank block
(beneficiary code, account, IFSC, bank, branch, email) from accounts' own
RBI-format Excel — the sheet their E-Net VLOOKUP already trusts. Without this,
the payment file works one hand-filled supplier at a time; with it, the whole
master is ready in one pass.

    bench --site <site> execute fountainhead.bill_ocr.tools.import_vendor_bank \
        --kwargs "{'xlsx_path': '/mnt/d/.../RBI File Format - NEFT RTGS.xls.xlsx'}"

DRY RUN by default — it prints what it WOULD write. Pass dry_run=0 to apply.
"""

import frappe
from fountainhead.bill_ocr import match


# Column positions in the RBI sheet (verified against the real file, 1 Sept):
# 1=Beneficiary Code · 2=Account Number · 4=Beneficiary Name · 24=IFSC ·
# 25=Bank · 26=Branch · 27=Email
COLS = {"code": 1, "account": 2, "name": 4, "ifsc": 24, "bank": 25, "branch": 26, "email": 27}


def import_vendor_bank(xlsx_path, sheet="TESTING BANK DETAILS", dry_run=1):
	import openpyxl

	dry_run = int(dry_run)
	wb = openpyxl.load_workbook(xlsx_path, data_only=True)
	if sheet not in wb.sheetnames:
		frappe.throw(f"Sheet '{sheet}' not in {wb.sheetnames}")
	ws = wb[sheet]

	suppliers = frappe.get_all("Supplier", fields=["name", "supplier_name"], limit_page_length=0)
	by_norm = {}
	for s in suppliers:
		key = " ".join(match.name_tokens(s.supplier_name or s.name)) if s else ""
		by_norm.setdefault(key, []).append(s.name)

	def find_supplier(name):
		if not name:
			return None, None
		if frappe.db.exists("Supplier", name):
			return name, "exact"
		key = " ".join(match.name_tokens(name))
		hits = by_norm.get(key) or []
		if len(hits) == 1:
			return hits[0], "normalised"
		return None, None

	updated, skipped, unmatched, ambiguous = [], [], [], []
	seen = set()
	for row in ws.iter_rows(min_row=2, values_only=True):
		name = (str(row[COLS["name"]]).strip() if row[COLS["name"]] else "")
		if not name or name in seen:
			continue
		seen.add(name)
		values = {
			"custom_beneficiary_code": str(row[COLS["code"]] or "").strip(),
			"custom_bank_account_no": str(row[COLS["account"]] or "").strip(),
			"custom_ifsc": str(row[COLS["ifsc"]] or "").strip().upper(),
			"custom_bank_name": str(row[COLS["bank"]] or "").strip(),
			"custom_bank_branch": str(row[COLS["branch"]] or "").strip(),
			"custom_payment_email": str(row[COLS["email"]] or "").strip(),
		}
		if not values["custom_bank_account_no"] or not values["custom_ifsc"]:
			skipped.append(f"{name}: incomplete row (no account/IFSC)")
			continue
		supplier, how = find_supplier(name)
		if not supplier:
			unmatched.append(name)
			continue
		# Never overwrite something accounts already filled by hand.
		current = frappe.db.get_value("Supplier", supplier,
		                              ["custom_bank_account_no", "custom_ifsc"], as_dict=True)
		if current and (current.custom_bank_account_no or "").strip():
			if current.custom_bank_account_no != values["custom_bank_account_no"]:
				ambiguous.append(f"{supplier}: sheet says a/c {values['custom_bank_account_no']}, "
				                 f"supplier already has {current.custom_bank_account_no} — left alone")
			continue
		if not dry_run:
			frappe.db.set_value("Supplier", supplier, values, update_modified=False)
		updated.append(f"{supplier} ({how})")

	if not dry_run:
		frappe.db.commit()

	print(f"{'DRY RUN — nothing written' if dry_run else 'APPLIED'}")
	print(f"would update: {len(updated)}" if dry_run else f"updated: {len(updated)}")
	print(f"skipped (incomplete): {len(skipped)}")
	print(f"unmatched supplier names: {len(unmatched)}")
	print(f"conflicts left alone: {len(ambiguous)}")
	for label, rows in (("UNMATCHED", unmatched[:25]), ("CONFLICTS", ambiguous[:25])):
		if rows:
			print(f"--- {label} (first {len(rows)}) ---")
			for r in rows:
				print(" ", r)
	return {"updated": len(updated), "skipped": len(skipped),
	        "unmatched": unmatched, "conflicts": ambiguous}
