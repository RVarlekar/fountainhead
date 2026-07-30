# Copyright (c) 2025, GreyCube Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _

class FHSIncomeAndExpenseForecast(Document):
	@frappe.whitelist()
	def fetch_eligible_profit_and_loss_accounts(self):
		accounts = frappe.db.get_list(
			doctype = "Account",
			filters = {
				"is_group" : 0,
				"company" : self.company,
				"report_type" : "Profit and Loss"
			},
			fields = ['name', 'root_type'],
			order_by = 'root_type desc'
		)

		if len(accounts) > 0:
			self.accounts_details = []
			for account in accounts:
				self.append("accounts_details", {
					"account" : account.name,
					"account_root_type" : account.root_type
				})
			self.save(ignore_permissions = True)
			return self