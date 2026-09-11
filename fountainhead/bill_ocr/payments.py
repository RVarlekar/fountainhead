"""HDFC E-Net vendor-payment file, generated from approved Purchase Invoices.

Replaces the manual Tally-extract → VLOOKUP → RBI-sheet → save-without-headers
routine (Tejas Patel's "RBI formate" mail + attachments, 1 Sept 2026):

* The output is a headerless CSV, one row per payment, 28 columns in the RBI
  sheet's exact order (verified against the real sample `8892RBI2708.009`).
* Transaction type: **"I"** when the beneficiary's bank is HDFC (internal
  transfer), **"N"** (NEFT) for every other bank — Tejas bhai, 1 Sept 3:00 pm.
* File name: `8892RBI` + DDMM + "." + a random 3-digit serial 001–999 (the
  extension is just a serial, not an entity code — confirmed 1 Sept 4:06 pm).
  The 8892 prefix is per-entity and configurable (`bill_ocr_enet_prefix`).
* Beneficiary details come from the Supplier master (fields shipped by
  install.py) — each vendor already has a unique beneficiary code in accounts'
  bank-details sheet; import it once and the file generates itself.

Generating a file MOVES no money: the file still gets uploaded to E-Net by the
authorised person, and the bank runs its own approvals. This is typing saved,
not control removed.
"""

import io
import random

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


# The 28 columns of the RBI sheet, in order. Blank means "always empty" in the
# sample file; the lambda names the field that fills it.
def _row_for(pi, supplier):
	ifsc = (supplier.custom_ifsc or "").strip().upper()
	txn = "I" if ifsc.startswith("HDFC") else "N"
	amount = flt(pi.outstanding_amount) or flt(pi.grand_total)
	short = "".join(ch for ch in (supplier.name or "").upper() if ch.isalnum())[:10]
	today = getdate(nowdate()).strftime("%d/%m/%Y")
	return [
		txn,                                   # 1  Transaction Type (I = HDFC-internal, N = NEFT)
		supplier.custom_beneficiary_code or "",# 2  Beneficiary Code
		supplier.custom_bank_account_no or "", # 3  Beneficiary Account Number
		f"{amount:.2f}".rstrip("0").rstrip("."),  # 4  Instrument Amount
		(supplier.supplier_name or supplier.name or "").upper(),  # 5  Beneficiary Name
		"", "", "", "", "", "", "",            # 6-12 Drawee/Print Location, Address 1-5
		"",                                    # 13 Instruction Reference Number
		short,                                 # 14 Customer Reference Number
		"", "", "", "", "", "", "",            # 15-21 Payment details 1-7
		"",                                    # 22 Cheque Number
		today,                                 # 23 Cheque Date
		"",                                    # 24 MICR NO
		ifsc,                                  # 25 IFSC CODE
		(supplier.custom_bank_name or "").upper(),    # 26 BENE BANK
		(supplier.custom_bank_branch or "").upper(),  # 27 Bene Bank Branch
		supplier.custom_payment_email or "",   # 28 Bene Email Id
	]


@frappe.whitelist()
def make_enet_file(invoice_names):
	"""Build the E-Net upload file for the given Purchase Invoices.

	Only SUBMITTED invoices with an outstanding amount qualify — the file is the
	payment step, so it must never pick up drafts or already-paid bills. Missing
	bank details fail loudly, per supplier, instead of writing a half-good file.
	"""
	import json

	frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))

	names = json.loads(invoice_names) if isinstance(invoice_names, str) else invoice_names
	if not names:
		frappe.throw(_("Select at least one Purchase Invoice."))

	rows, problems = [], []
	for name in names:
		pi = frappe.get_doc("Purchase Invoice", name)
		if pi.docstatus != 1:
			problems.append(_("{0}: not submitted — only approved bills get paid").format(name))
			continue
		if flt(pi.outstanding_amount) <= 0:
			problems.append(_("{0}: nothing outstanding").format(name))
			continue
		supplier = frappe.get_doc("Supplier", pi.supplier)
		missing = [label for field, label in (
			("custom_bank_account_no", _("account number")),
			("custom_ifsc", _("IFSC")),
			("custom_beneficiary_code", _("beneficiary code")),
		) if not (supplier.get(field) or "").strip()]
		if missing:
			problems.append(_("{0} ({1}): supplier is missing {2} — fill the bank details "
			                  "on the Supplier first").format(name, pi.supplier, ", ".join(missing)))
			continue
		rows.append(_row_for(pi, supplier))

	if problems and not rows:
		frappe.throw("<br>".join(problems), title=_("Nothing to write"))

	buf = io.StringIO()
	for r in rows:
		buf.write(",".join(str(c) for c in r) + "\r\n")

	prefix = frappe.conf.get("bill_ocr_enet_prefix") or "8892RBI"
	serial = f"{random.randint(1, 999):03d}"
	filename = f"{prefix}{getdate(nowdate()).strftime('%d%m')}.{serial}"

	return {
		"filename": filename,
		"content": buf.getvalue(),
		"rows": len(rows),
		"total": sum(flt(c[3]) for c in rows),
		"skipped": problems,
	}
