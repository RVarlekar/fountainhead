"""Custom fields this feature needs, created idempotently on every `bench migrate`.

Why in code rather than clicked in the UI: this project's central problem is that
~70% of the system's behaviour lives in the database and nowhere in a repository,
so nobody can tell what a fresh install should look like. Anything this feature
needs therefore ships WITH the feature — deploying the app is enough, and staging
and production cannot silently drift apart.

`create_custom_fields` updates in place if a field already exists, so re-running
is safe.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

BILL_OCR_FIELDS = {
	# The entity-level GST switch decided in the 19 Aug review: the school has no
	# GST registration and books GST-inclusive totals (98.1% of its receipts carry
	# no tax rows), while Protego-side entities are registered and keep the breakup.
	# Which behaviour Bill OCR applies is a property of the Company, not the bill.
	"Company": [
		{
			"fieldname": "custom_gst_registered",
			"label": "GST registered (Bill OCR books tax rows)",
			"fieldtype": "Check",
			"insert_after": "tax_id",
			"default": "0",
			"description": (
				"Ticked: Bill OCR fills the bill's GST into the Taxes table as separate rows. "
				"Unticked (entities without GST registration): GST is folded into the item "
				"rates and the document books the bill's GST-inclusive total."
			),
		},
	],
	"Item": [
		{
			"fieldname": "custom_bill_ocr_section",
			"label": "Bill OCR",
			"fieldtype": "Section Break",
			"insert_after": "item_group",
			"collapsible": 1,
		},
		{
			"fieldname": "custom_created_from_bill_ocr",
			"label": "Created from a bill scan",
			"fieldtype": "Check",
			"insert_after": "custom_bill_ocr_section",
			"read_only": 1,
			"description": "Set automatically when Bill OCR created this item from a vendor bill.",
		},
		{
			"fieldname": "custom_bill_ocr_reviewed",
			"label": "Reviewed",
			"fieldtype": "Check",
			"insert_after": "custom_created_from_bill_ocr",
			"depends_on": "custom_created_from_bill_ocr",
			"description": "Tick once checked in the weekly review of newly created items.",
		},
		{
			"fieldname": "custom_bill_ocr_source",
			"label": "Source bill",
			"fieldtype": "Small Text",
			"insert_after": "custom_bill_ocr_reviewed",
			"read_only": 1,
			"depends_on": "custom_created_from_bill_ocr",
			"description": "Supplier and invoice number this item was first seen on.",
		},
	],
	# The vendor master carries none of the statutory identifiers today (the
	# 21 Aug audit found NO PAN field at all — TDS was literally uncomputable).
	# Approved in the 26 Aug sitting: PAN + GSTIN on Supplier, system-suggested,
	# human-confirmed; PAN auto-derived from GSTIN (chars 3–12 — Tejas bhai's
	# rule, 1 Sept). The TDS section + vendor type drive the TDS engine; the
	# bank block feeds the E-Net payment file.
	"Supplier": [
		{
			"fieldname": "custom_statutory_section",
			"label": "Statutory (Bill OCR)",
			"fieldtype": "Section Break",
			"insert_after": "supplier_group",
			"collapsible": 1,
		},
		{
			"fieldname": "custom_gstin",
			"label": "GSTIN",
			"fieldtype": "Data",
			"insert_after": "custom_statutory_section",
			"length": 15,
			"description": "15 characters. PAN fills itself from characters 3–12.",
		},
		{
			"fieldname": "custom_pan",
			"label": "PAN",
			"fieldtype": "Data",
			"insert_after": "custom_gstin",
			"length": 10,
			"description": "Auto-derived from GSTIN when one is set. Missing/invalid PAN triggers the higher TDS rate.",
		},
		{
			"fieldname": "custom_column_statutory",
			"fieldtype": "Column Break",
			"insert_after": "custom_pan",
		},
		{
			"fieldname": "custom_tds_section",
			"label": "TDS Section",
			"fieldtype": "Link",
			"options": "Bill TDS Rule",
			"insert_after": "custom_column_statutory",
			"description": "Which TDS rule applies to this vendor's usual nature of payment. Leave blank = no TDS suggestions.",
		},
		{
			"fieldname": "custom_vendor_type",
			"label": "Vendor type (for TDS)",
			"fieldtype": "Select",
			"options": "\nIndividual\nHUF\nFirm\nCompany\nOther",
			"insert_after": "custom_tds_section",
		},
		{
			"fieldname": "custom_bank_section",
			"label": "Bank details (E-Net payments)",
			"fieldtype": "Section Break",
			"insert_after": "custom_vendor_type",
			"collapsible": 1,
		},
		{
			"fieldname": "custom_beneficiary_code",
			"label": "Beneficiary Code",
			"fieldtype": "Data",
			"insert_after": "custom_bank_section",
			"description": "The unique code from accounts' bank-details master (SC0001…).",
		},
		{
			"fieldname": "custom_bank_account_no",
			"label": "Bank Account No",
			"fieldtype": "Data",
			"insert_after": "custom_beneficiary_code",
		},
		{
			"fieldname": "custom_ifsc",
			"label": "IFSC",
			"fieldtype": "Data",
			"insert_after": "custom_bank_account_no",
			"description": "HDFC IFSC → the payment file writes an Internal (I) transfer; anything else → NEFT (N).",
		},
		{
			"fieldname": "custom_column_bank",
			"fieldtype": "Column Break",
			"insert_after": "custom_ifsc",
		},
		{
			"fieldname": "custom_bank_name",
			"label": "Bank Name",
			"fieldtype": "Data",
			"insert_after": "custom_column_bank",
		},
		{
			"fieldname": "custom_bank_branch",
			"label": "Bank Branch",
			"fieldtype": "Data",
			"insert_after": "custom_bank_name",
		},
		{
			"fieldname": "custom_payment_email",
			"label": "Payment intimation email",
			"fieldtype": "Data",
			"options": "Email",
			"insert_after": "custom_bank_branch",
		},
	],
	# The two booking checkboxes from the "RCM AND GST" rules (1 Sept), mutually
	# exclusive (either/or by law): GST credit ticked → GST separates to input;
	# RCM ticked → RCM treatment (liability accumulates in GST Payable, settled
	# in the monthly consolidated voucher). Both off = follow the actual bill.
	# Dormant on a non-GST company (the school) — they only matter where the
	# Company's GST flag is on (Protego side).
	"Purchase Invoice": [
		{
			"fieldname": "custom_gst_credit",
			"label": "Claim GST credit (ITC)",
			"fieldtype": "Check",
			"insert_after": "custom_attachment",
			"depends_on": "eval:doc.custom_rcm != 1",
			"description": "Tick only when this bill's GST is claimable input credit (category-wise master: ITC Eligibility Category). Off = GST stays in the cost.",
		},
		{
			"fieldname": "custom_rcm",
			"label": "RCM applicable",
			"fieldtype": "Check",
			"insert_after": "custom_gst_credit",
			"depends_on": "eval:doc.custom_gst_credit != 1",
			"description": "Reverse charge (e.g. lawyer bills): the RCM liability accumulates in GST Payable and is settled in the consolidated voucher. Mutually exclusive with GST credit.",
		},
	],
}


def after_migrate():
	create_custom_fields(BILL_OCR_FIELDS, update=True)
	_seed_cash_memo_series()
	_set_pr_grid_columns()
	_seed_tds_rules()
	_seed_itc_categories()
	frappe.db.commit()


def _set_pr_grid_columns():
	"""Chetan sir's 26 Aug grid cleanup: the Rejected-qty and Item-Tax-Template
	columns add noise to every receipt's item grid and are blank on nearly all
	of them — take them out of the LIST VIEW only (the fields stay on the form).
	Property Setters, so it ships with the app instead of being clicked per site."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	for fieldname in ("rejected_qty", "item_tax_template"):
		make_property_setter(
			"Purchase Receipt Item", fieldname, "in_list_view", 0, "Check",
			for_doctype=False, validate_fields_for_doctype=False,
		)


def _seed_tds_rules():
	from fountainhead.bill_ocr import tds

	tds.seed_rules()


def _seed_itc_categories():
	"""The category-wise ITC master, seeded from the 'RCM AND GST' rules mail
	(1 Sept). Idempotent — existing rows are accounts' property, never touched."""
	if not frappe.db.exists("DocType", "ITC Eligibility Category"):
		return
	seeds = [
		("Professional / Consultancy Services", 1, ""),
		("Legal Services", 1, "Often RCM — tick the RCM box on the bill."),
		("IT Services / Software", 1, ""),
		("Office Expenses", 1, ""),
		("Repairs & Maintenance", 1, ""),
		("Security Services", 1, ""),
		("Housekeeping Services", 1, ""),
		("Employee Personal Expenses", 0, "Blocked under ITC rules."),
		("Personal Consumption", 0, "Blocked under ITC rules."),
		("Canteen / Food", 0, "Blocked unless an applicable exception exists."),
		("Passenger / Employee Transport", 0, "Restricted/blocked, subject to the specific provision."),
		("Motor Vehicles & Related", 0, "Blocked, subject to exceptions."),
	]
	for category, eligible, note in seeds:
		if frappe.db.exists("ITC Eligibility Category", category):
			continue
		frappe.get_doc({
			"doctype": "ITC Eligibility Category",
			"category": category,
			"itc_eligible": eligible,
			"note": note,
		}).insert(ignore_permissions=True)


def derive_pan_from_gstin(doc, method=None):
	"""Supplier validate: GSTIN → PAN, exactly per the 1 Sept rule.

	GSTIN is 15 characters; characters 3–12 ARE the PAN (24AADFF3677P1ZY →
	AADFF3677P). The user never types the PAN when a GSTIN exists. A malformed
	GSTIN throws — a wrong identifier is worse than a missing one.
	"""
	import re

	gstin = (doc.get("custom_gstin") or "").strip().upper()
	if not gstin:
		return
	doc.custom_gstin = gstin
	if not re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$", gstin):
		frappe.throw(
			frappe._("{0} is not a valid 15-character GSTIN — check it against the bill.").format(gstin)
		)
	pan = gstin[2:12]
	if (doc.get("custom_pan") or "").strip().upper() != pan:
		doc.custom_pan = pan
		frappe.msgprint(
			frappe._("PAN set to {0} — derived from the GSTIN (characters 3–12).").format(pan),
			alert=True,
		)


def _seed_cash_memo_series():
	"""Start the CM-#### Cash Memo series safely above the old hand-typed
	counter (it had reached 145). Idempotent: never lowers an existing counter."""
	current = frappe.db.sql("select current from tabSeries where name = 'CM-'")
	if not current:
		frappe.db.sql("insert into tabSeries (name, current) values ('CM-', 200)")
	elif (current[0][0] or 0) < 200:
		frappe.db.sql("update tabSeries set current = 200 where name = 'CM-'")
