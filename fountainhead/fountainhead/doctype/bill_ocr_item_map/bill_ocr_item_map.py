# Bill OCR Item Map — the feature's memory.
#
# One row = "this exact bill wording means that item", learned from a real user
# choice on a real bill. On the next bill whose line matches word for word, the
# item is filled in directly instead of asked again.
#
# Deliberately EXACT-match only (case- and whitespace-insensitive, but no fuzzy
# logic): a learned answer is auto-applied, so it must never fire on text that is
# merely similar. Similar text still goes through the suggestion flow.

import frappe
from frappe.model.document import Document


class BillOCRItemMap(Document):
	pass


def normalise_key(text):
	"""Case- and whitespace-insensitive key for word-for-word matching."""
	return " ".join(str(text or "").split()).casefold()[:500]
