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
from frappe.utils import cint

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
def create_item_from_bill(
	item_name,
	item_group,
	stock_uom,
	is_stock_item=1,
	description=None,
	source_note=None,
	acknowledged_similar=0,
):
	"""Create an Item from a bill line — deliberately, never casually.

	Guarded this hard because the item master is already the project's worst data
	problem: 6,141 items, **2,291 of them created in the last twelve months**, with
	typo-duplicates like "Foam Roller 6" / "Fuam Roller 6" / "Foam Roller 6 Inch"
	sitting side by side. A frictionless create button on every unmatched bill line
	would make that materially worse, and cleaning it up is already on the task list.

	So: the caller must pass `acknowledged_similar=1` before we will create anything
	that resembles an existing item. The first call returns the near-matches instead
	of creating, and the UI shows them as "did you mean?".

	Uses `insert()` so every standard ERPNext validation and hook runs — never a
	raw SQL write.
	"""
	if not frappe.has_permission("Item", "create"):
		raise frappe.PermissionError(
			_("You do not have permission to create Items. Ask someone with the "
			  "Item Manager or Purchase Master Manager role.")
		)

	item_name = (item_name or "").strip()
	if not item_name:
		frappe.throw(_("Give the item a name."))
	if not item_group or not frappe.db.exists("Item Group", item_group):
		frappe.throw(_("Choose a valid Item Group — it decides where this item is reported."))
	if not stock_uom or not frappe.db.exists("UOM", stock_uom):
		frappe.throw(_("Choose a valid Unit of Measure."))

	if frappe.db.exists("Item", item_name):
		frappe.throw(_("An item called {0} already exists — use it instead.").format(item_name))

	# Duplicate gate. Only skipped once the user has actually seen the near-matches.
	if not cint(acknowledged_similar):
		similar = match.find_similar_items(item_name)
		if similar:
			return {"created": False, "needs_confirmation": True, "similar": similar}

	doc = frappe.get_doc({
		"doctype": "Item",
		"item_code": item_name,
		"item_name": item_name,
		"item_group": item_group,
		"stock_uom": stock_uom,
		"is_stock_item": cint(is_stock_item),
		"description": description or item_name,
		# Tracking, so the weekly review can find everything this feature created.
		"custom_created_from_bill_ocr": 1,
		"custom_bill_ocr_source": source_note or "",
	})
	doc.insert()

	frappe.msgprint(
		_("Created item {0}. It is flagged for the weekly review of new items.").format(doc.name),
		alert=True,
	)
	return {
		"created": True,
		"item_code": doc.name,
		"item_name": doc.item_name,
		"stock_uom": doc.stock_uom,
		"is_stock_item": doc.is_stock_item,
	}


@frappe.whitelist()
def create_supplier_from_bill(supplier_name, supplier_group=None, acknowledged_similar=0):
	"""Create a Supplier from a bill, with the same duplicate discipline.

	The master already carries pairs like DEEPAK STATIONERY and DEEPAK STATIONERY
	MART, so near-matches must be seen before a new one is allowed.
	"""
	if not frappe.has_permission("Supplier", "create"):
		raise frappe.PermissionError(_("You do not have permission to create Suppliers."))

	supplier_name = (supplier_name or "").strip()
	if not supplier_name:
		frappe.throw(_("Give the supplier a name."))
	if frappe.db.exists("Supplier", supplier_name):
		frappe.throw(_("A supplier called {0} already exists.").format(supplier_name))

	if not cint(acknowledged_similar):
		res = match.match_supplier(supplier_name)
		similar = res.get("candidates") or []
		if similar:
			return {"created": False, "needs_confirmation": True, "similar": similar}

	doc = frappe.get_doc({
		"doctype": "Supplier",
		"supplier_name": supplier_name,
		"supplier_group": supplier_group
		or frappe.db.get_single_value("Buying Settings", "supplier_group")
		or frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
	})
	doc.insert()
	frappe.msgprint(_("Created supplier {0}.").format(doc.name), alert=True)
	return {"created": True, "supplier": doc.name}


@frappe.whitelist()
def get_creation_defaults(item_group=None, unit=None):
	"""What the create-item form should default to, given the chosen Item Group."""
	return {
		"stock": match.stock_default_for_group(item_group),
		"stock_uom": match.normalise_uom(unit),
	}


@frappe.whitelist()
def extract_bill(file_url, doctype="Purchase Receipt"):
	"""Read an attached bill and return values for the form to fill in.

	Args:
		file_url: the `custom_attachment` value on the open document.
		doctype:  Purchase Receipt or Purchase Invoice.

	Returns a dict the client applies field by field. Nothing is written here.

	If this exact file was already read through the batch queue (Bill OCR
	Upload), the stored reading is reused — the same bill is never paid for
	twice, and the dialog opens instantly.
	"""
	cached = _cached_payload(file_url)
	if cached is not None:
		return cached
	return _run_extraction(file_url, doctype)


def _cached_payload(file_url):
	"""A stored reading for this file from the batch queue, if one exists."""
	import json

	row = frappe.db.get_value(
		"Bill OCR Upload",
		{"bill_file": file_url, "status": "Read"},
		["name", "extraction_json"],
		as_dict=True,
	) if frappe.db.exists("DocType", "Bill OCR Upload") else None
	if not row or not row.extraction_json:
		return None
	try:
		payload = json.loads(row.extraction_json)
	except ValueError:
		return None
	# Permission flags are per-user; never serve another user's.
	payload["can_create_item"] = bool(frappe.has_permission("Item", "create"))
	payload["can_create_supplier"] = bool(frappe.has_permission("Supplier", "create"))
	payload.setdefault("notes", []).append(
		_("Reused the reading from batch upload {0} — no new reading was paid for.").format(row.name)
	)
	return payload


def _run_extraction(file_url, doctype="Purchase Receipt"):
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(_("Bill OCR does not handle {0}.").format(doctype))

	# The caller must be someone who could legitimately create this document.
	if not frappe.has_permission(doctype, "create"):
		raise frappe.PermissionError(_("You are not allowed to create {0}.").format(doctype))

	file_bytes, mime = _load_attachment(file_url)

	raw, usage = extract.read_bill(file_bytes, mime)
	data, notes = normalize.normalize(raw)

	# Prefer the English rendering of the vendor name — the supplier master is Latin,
	# so a Gujarati name can only match through its translation.
	vendor_for_match = data.get("vendorNameEn") or data.get("vendorName")
	supplier = match.match_supplier(vendor_for_match, data.get("vendorGstin"))
	if not supplier["supplier"]:
		notes.append(
			_("No supplier matched {0} — pick one, or create it deliberately.").format(
				vendor_for_match or _("the name on the bill")
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
	items = match.match_items(
		data.get("lines") or [],
		supplier["supplier"],
		item_group_hint=(item_group or {}).get("item_group"),
	)

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
		"vendor_name_english": data.get("vendorNameEn"),
		"can_create_item": bool(frappe.has_permission("Item", "create")),
		"can_create_supplier": bool(frappe.has_permission("Supplier", "create")),
		"notes": notes,
		"usage": usage,
	}


@frappe.whitelist()
def read_upload(name):
	"""Read one queued bill (a Bill OCR Upload) and store the result on it.

	Called sequentially from the browser for each Pending row — deliberately not
	a background job, so the batch works the same on a dev bench (no workers)
	and under supervisor, shows progress, and can be stopped mid-way.

	Errors are RECORDED on the row rather than raised, so one unreadable photo
	doesn't stop the rest of the batch.
	"""
	import json

	doc = frappe.get_doc("Bill OCR Upload", name)
	doc.check_permission("write")

	if doc.status == "Read" and doc.extraction_json:
		return {"name": doc.name, "status": "Read", "skipped": True}

	try:
		payload = _cached_payload(doc.bill_file) or _run_extraction(
			doc.bill_file, doc.target_doctype or "Purchase Receipt"
		)
	except Exception as e:
		doc.status = "Error"
		doc.error_message = str(e)[:500]
		doc.save()
		return {"name": doc.name, "status": "Error", "error": doc.error_message}

	fields = payload.get("fields") or {}
	totals = payload.get("totals") or {}
	doc.status = "Read"
	doc.error_message = ""
	doc.vendor_name = (payload.get("vendor_name_on_bill") or "")[:140]
	doc.supplier = fields.get("supplier")
	doc.bill_no = (fields.get("bill_no") or "")[:140]
	doc.bill_date = fields.get("bill_date")
	doc.grand_total = totals.get("grand_total")
	doc.lines_count = len(payload.get("items") or [])
	doc.extraction_json = json.dumps(payload, ensure_ascii=False, default=str)
	doc.save()

	return {
		"name": doc.name,
		"status": "Read",
		"vendor": doc.vendor_name,
		"supplier": doc.supplier,
		"bill_no": doc.bill_no,
		"grand_total": doc.grand_total,
	}
