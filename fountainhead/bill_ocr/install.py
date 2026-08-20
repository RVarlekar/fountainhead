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
	]
}


def after_migrate():
	create_custom_fields(BILL_OCR_FIELDS, update=True)
	frappe.db.commit()
