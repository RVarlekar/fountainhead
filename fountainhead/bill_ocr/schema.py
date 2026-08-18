"""The `emit_invoice` tool schema — the shape the model must return.

Ported from the prototype's Zod `invoiceDataSchema`. Forcing a tool call with
this as its input_schema is what keeps the output structured JSON rather than
free-form text the caller has to parse.

The GST fields are kept even though Fountainhead holds no GST registration:
vendors still print GST on their bills, and we want the printed figures captured
so the total reconciles. Fountainhead simply cannot claim the input credit.
"""

INVOICE_LINE = {
	"type": "object",
	"properties": {
		"description": {"type": "string", "description": "Exactly as printed, original script"},
		"descriptionEn": {
			"type": "string",
			"description": "The same line in plain English — translate the meaning, not the sounds",
		},
		"hsnSac": {"type": "string"},
		"quantity": {"type": "number"},
		"unit": {"type": "string"},
		"rate": {"type": "number"},
		"lineAmount": {"type": "number"},
	},
	"required": ["description", "lineAmount"],
}

OTHER_CHARGE = {
	"type": "object",
	"properties": {
		"description": {"type": "string"},
		"amount": {"type": "number"},
	},
	"required": ["description", "amount"],
}

INVOICE_SCHEMA = {
	"type": "object",
	"properties": {
		# Vendor (the seller)
		"vendorName": {"type": "string", "description": "Seller / supplier name as printed"},
		"vendorNameEn": {
			"type": "string",
			"description": "Seller name in English/Latin script (same as vendorName if already English)",
		},
		"vendorGstin": {"type": "string"},
		"vendorPan": {"type": "string"},
		"vendorState": {"type": "string"},
		"vendorStateCode": {"type": "string"},
		"vendorType": {
			"type": "string",
			"enum": ["Company", "Firm", "Individual", "HUF", "Unknown"],
		},
		# Header
		"invoiceNumber": {"type": "string"},
		"invoiceDate": {"type": "string", "description": "As printed on the bill"},
		"placeOfSupplyStateCode": {"type": "string"},
		"lines": {"type": "array", "items": INVOICE_LINE},
		# Tax block — amounts exactly as printed
		"taxableValue": {"type": "number"},
		"cgstRate": {"type": "number"},
		"cgstAmount": {"type": "number"},
		"sgstRate": {"type": "number"},
		"sgstAmount": {"type": "number"},
		"igstRate": {"type": "number"},
		"igstAmount": {"type": "number"},
		"cessAmount": {"type": "number"},
		"roundOff": {"type": "number"},
		"otherCharges": {"type": "array", "items": OTHER_CHARGE},
		"totalInvoiceValue": {"type": "number"},
		# Classification
		"reverseChargeFlagged": {"type": "boolean"},
		"expenseCategory": {"type": "string"},
		"ancillaryCharges": {
			"type": "string",
			"enum": ["taxed_inclusive", "untaxed_separate"],
		},
		# Routing — the buyer
		"targetCompany": {"type": "string"},
		"companyGstin": {"type": "string"},
		"companyStateCode": {"type": "string"},
	},
	"required": [
		"vendorName",
		"invoiceNumber",
		"invoiceDate",
		"lines",
		"taxableValue",
		"totalInvoiceValue",
		"expenseCategory",
	],
}

TOOL = {
	"name": "emit_invoice",
	"description": "Emit the transcribed invoice as structured data.",
	"input_schema": INVOICE_SCHEMA,
}
