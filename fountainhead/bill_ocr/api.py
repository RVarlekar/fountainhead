"""The endpoint the Purchase Receipt form calls.

Contract, and the reason for it: this returns DATA. It does not create, save or
submit anything. The browser fills the form the user is already looking at, the
user checks it, the user presses Save.

That is not a workaround — `custom_item_group` and `custom_reason_for_purchase`
are mandatory on Purchase Receipt and are on no vendor bill, so anything that
tried to save a document from here would fail every time. It also keeps Vardan
sir's "nothing posts automatically" rule true by construction.
"""

import mimetypes

import frappe
from frappe import _

from fountainhead.bill_ocr import extract, match, normalize

SUPPORTED_DOCTYPES = ("Purchase Receipt", "Purchase Invoice")


def _find_duplicates(supplier, bill_no):
	"""Existing Purchase Receipts / Invoices carrying this supplier + invoice no.

	Both doctypes are checked whichever one is open: the same paper bill must not
	enter as a Receipt after it already entered as an Invoice, or vice versa.
	Cancelled documents (docstatus 2) don't count.
	"""
	if not supplier or not bill_no:
		return []
	found = []
	for doctype in SUPPORTED_DOCTYPES:
		for name in frappe.get_all(
			doctype,
			filters={"supplier": supplier, "bill_no": bill_no, "docstatus": ["<", 2]},
			pluck="name",
			limit_page_length=3,
		):
			found.append({"doctype": doctype, "name": name})
	return found


def _load_attachment(file_url):
	"""Fetch the attached file, enforcing the caller's own read permission on it."""
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		frappe.throw(_("Could not find that attachment."))

	file_doc = frappe.get_doc("File", name)
	# Honour File's own permission logic (private files, attached-to checks).
	file_doc.check_permission("read")

	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode("utf-8")

	mime = mimetypes.guess_type(file_doc.file_name or file_url)[0]
	if not mime:
		frappe.throw(_("Could not tell what kind of file that is. Attach a PDF or an image."))
	return content, mime


@frappe.whitelist()
def extract_bill(file_url, doctype="Purchase Receipt"):
	"""Read an attached bill and return values for the form to fill in.

	Args:
		file_url: the `custom_attachment` value on the open document.
		doctype:  Purchase Receipt or Purchase Invoice.

	Returns a dict the client applies field by field. Nothing is written here.
	"""
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(_("Bill OCR does not handle {0}.").format(doctype))

	# The caller must be someone who could legitimately create this document.
	if not frappe.has_permission(doctype, "create"):
		raise frappe.PermissionError(_("You are not allowed to create {0}.").format(doctype))

	file_bytes, mime = _load_attachment(file_url)

	raw, usage = extract.read_bill(file_bytes, mime)
	data, notes = normalize.normalize(raw)

	supplier = match.match_supplier(data.get("vendorName"), data.get("vendorGstin"))
	if not supplier["supplier"]:
		notes.append(
			_("No supplier matched {0} — pick one, or create it deliberately.").format(
				data.get("vendorName") or _("the name on the bill")
			)
		)
	elif supplier["method"] == "fuzzy_name":
		notes.append(
			_("Supplier matched by name similarity ({0}%) — please confirm it is right.").format(
				supplier["confidence"]
			)
		)

	# Duplicate check: the same supplier presenting the same invoice number is the
	# classic double-entry — the same paper bill keyed twice and paid twice. Cheap
	# to catch here, expensive to unwind after payment.
	duplicates = _find_duplicates(supplier["supplier"], data.get("invoiceNumber"))
	for dup in duplicates:
		notes.insert(
			0,
			_("⚠ Possible duplicate: {0} {1} already carries invoice no {2} for this supplier. "
			  "Check before saving.").format(dup["doctype"], dup["name"], data.get("invoiceNumber")),
		)

	item_group = match.suggest_item_group(supplier["supplier"])
	items = match.match_items(data.get("lines") or [], supplier["supplier"])

	matched = sum(1 for i in items if i.get("item_code"))
	if items and matched < len(items):
		notes.append(
			_("{0} of {1} bill lines could not be matched to an item — pick those yourself. "
			  "Quantity and rate are filled in from the bill either way.").format(
				len(items) - matched, len(items)
			)
		)

	return {
		"fields": {
			# Straight off the bill — these are the ones the user retypes today.
			"bill_no": data.get("invoiceNumber"),
			"bill_date": data.get("invoiceDate"),
			"supplier": supplier["supplier"],
		},
		"supplier": supplier,
		"totals": {
			"taxable_value": data.get("taxableValue"),
			"cgst": data.get("cgstAmount"),
			"sgst": data.get("sgstAmount"),
			"igst": data.get("igstAmount"),
			"round_off": data.get("roundOff"),
			"grand_total": data.get("totalInvoiceValue"),
		},
		"items": items,
		# Offered, never applied. This field decides who approves the document.
		"suggestions": {
			"custom_item_group": item_group,
			"expense_category": data.get("expenseCategory"),
		},
		"vendor_name_on_bill": data.get("vendorName"),
		"notes": notes,
		"usage": usage,
	}
