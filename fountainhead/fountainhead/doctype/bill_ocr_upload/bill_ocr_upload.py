# Bill OCR Upload — one queued bill in a batch.
#
# The batch flow mirrors the standalone prototype's queue: drop many bills,
# each becomes one of these documents, reading happens one bill at a time from
# the browser (no background workers needed — works identically on a dev bench
# and under supervisor), and each Read row offers "Create Purchase Receipt",
# which opens the normal form flow with the stored reading. Nothing is created
# or posted without a person on the form pressing Save.

import frappe
from frappe.model.document import Document


class BillOCRUpload(Document):
	def validate(self):
		# The same file queued twice is almost always a double entry about to
		# happen — flag it early, at queue time, not after both got receipts.
		if self.bill_file and self.is_new():
			other = frappe.db.get_value(
				"Bill OCR Upload",
				{"bill_file": self.bill_file, "name": ["!=", self.name or ""]},
				"name",
			)
			if other:
				frappe.msgprint(
					frappe._("This file is already queued as {0}.").format(other),
					indicator="orange",
					alert=True,
				)
