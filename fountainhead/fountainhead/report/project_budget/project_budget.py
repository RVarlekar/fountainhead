# Copyright (c) 2025, GreyCube Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from fountainhead.api import get_all_items_of_level_1_item_group, get_all_service_items_of_level_1_item_group, get_all_asset_items_of_level_1_item_group


def execute(filters=None):
	columns, data = [], []
	columns = get_columns(filters)
	data = get_data(filters)

	return columns, data

def get_columns(filters):
	return [
		{
			"fieldname": "budget_area_item_group",
			"label":_("Budget Area /Account (Item group)"),
			"fieldtype": "Link",
			"options": "Item Group",
			"width":"240"
		},
		{
			"fieldname": "budget_area_in_sqft",
			"label":_("Budget Area (in UOM)"),
			"fieldtype": "Float",
			"width":"200"
		},
		{
			"fieldname": "uom",
			"label":_("UOM"),
			"fieldtype": "Link",
			"options": "UOM",
			"width":"200"
		},
		{
			"fieldname": "budget_area_rate_per_area",
			"label":_("Budget Area Rate Per Area"),
			"fieldtype": "Currency",
			"width":"200"
		},
		{
			"fieldname": "budget_amount",
			"label":_("Budget Amount"),
			"fieldtype": "Currency",
			"width":"200"
		},
		{
			"fieldname": "purchase_amount",
			"label":_("Purchase Amount"),
			"fieldtype": "Currency",
			"width":"200"
		},
		{
			"fieldname": "actual_expense_amount",
			"label":_("Actual Expense Amount"),
			"fieldtype": "Currency",
			"width":"200"
		},
		{
			"fieldname": "actual_final_area",
			"label":_("Actual Final Area"),
			"fieldtype": "Float",
			"width":"200"
		},
		{
			"fieldname": "actual_rate_per_area",
			"label":_("Actual Rate Per Area"),
			"fieldtype": "Currency",
			"width":"200"
		},
		{
			"fieldname": "remark",
			"label":_("Remarks"),
			"fieldtype": "Data",
			"width":"200"
		}
	]

def get_data(filters):
	project_details = frappe.db.sql("""
							SELECT
								pd.budget_area_item_group,
								pd.budget_area_in_sqft,
								pd.actual_final_area,
								pd.budget_area_rate_per_area,
								pd.budget_amount,
								pd.remark,
								pd.uom,
								p.project_type,
								p.custom_asset as asset
							FROM
								`tabProject` p
							INNER JOIN `tabProject Details` pd ON
								pd.parent = p.name
							WHERE p.name = '{0}'
					""".format(filters.get("project")),as_dict=1, debug=1)
	print(project_details,"-------")

	if len(project_details) > 0:
		for row in project_details:
			item_list = get_all_items_of_level_1_item_group(row.budget_area_item_group)
			service_item = get_all_service_items_of_level_1_item_group(row.budget_area_item_group)
			asset_item = get_all_asset_items_of_level_1_item_group(row.budget_area_item_group)
			
			purchase_amount = 0
			purchase_amount_data = frappe.db.sql("""
									SELECT amount, item_code FROM `tabPurchase Order Item`
									WHERE project = '{0}' and docstatus = 1
							""".format(filters.get("project")),as_dict=1)
			
			if len(purchase_amount_data)>0:
				for purchase_row in purchase_amount_data:
					if len(item_list)>0:
						if purchase_row.item_code in item_list:
							purchase_amount = purchase_amount + purchase_row.amount
			
			if purchase_amount>0:
				row["purchase_amount"] = purchase_amount
			else:
				row["purchase_amount"] = 0.0
			
			total_expense_amount = 0
			if row.project_type == "Asset":
				actual_expense_amount_of_all_item = frappe.db.sql("""
							SELECT
								acsi.amount as service_amount,
								acsi.item_code as service_item,
								tacsi.amount as stock_amount,
								tacsi.item_code as stock_item,
								tacai.current_asset_value as asset_amount,
								tacai.item_code as asset_item,
								ac.target_asset
							FROM
								`tabAsset Capitalization` ac
							LEFT OUTER JOIN `tabAsset Capitalization Service Item` acsi ON
								acsi.parent = ac.name
							LEFT OUTER JOIN `tabAsset Capitalization Stock Item` tacsi ON
								tacsi.parent = ac.name
							LEFT OUTER JOIN `tabAsset Capitalization Asset Item` tacai ON
								tacai.parent = ac.name
							WHERE ac.target_asset = '{0}' and ac.docstatus = 1
					""".format(row.asset),as_dict=1)
				
				if len(actual_expense_amount_of_all_item)>0:
					for expense_amount_row in actual_expense_amount_of_all_item:
						if len(item_list)>0:
							if expense_amount_row.stock_item in item_list:
								total_expense_amount = total_expense_amount + expense_amount_row.stock_amount
						if len(service_item)>0:
							if expense_amount_row.service_item in service_item:
								total_expense_amount = total_expense_amount + expense_amount_row.service_amount
						if len(asset_item)>0:
							if expense_amount_row.asset_item in asset_item:
								total_expense_amount = total_expense_amount + expense_amount_row.asset_amount
						
			elif row.project_type == "Maintenance":
				data_from_stock_entry = frappe.db.sql("""
											SELECT
												sed.amount,
												sed.item_code
											FROM
												`tabStock Entry` se
											INNER JOIN `tabStock Entry Detail` sed ON
												sed.parent = se.name
											WHERE
												se.docstatus = 1
										  		and se.stock_entry_type = 'Material Issue'
												and sed.project = '{0}'
									""".format(filters.get("project")),as_dict=1)
				if len(data_from_stock_entry)>0:
					for stock_entry_row in data_from_stock_entry:
						if len(item_list)>0:
							if stock_entry_row.item_code in item_list:
								total_expense_amount = total_expense_amount + stock_entry_row.amount

				data_from_purchase_invoice = frappe.db.sql("""
												SELECT
													pii.amount,
													pii.item_code
												FROM
													`tabPurchase Invoice` pi
												INNER JOIN `tabPurchase Invoice Item` pii ON
													pii.parent = pi.name
												WHERE
													pi.docstatus = 1
													and pii.project = '{0}'
										""".format(filters.get("project")),as_dict=1)
				if len(data_from_purchase_invoice)>0:
					for purchase_row in data_from_purchase_invoice:
						if len(service_item)>0:
							if purchase_row.item_code in service_item:
								total_expense_amount = total_expense_amount + purchase_row.amount
			
			if total_expense_amount > 0:
				row["actual_expense_amount"] = total_expense_amount
			else :
				row["actual_expense_amount"] = 0
			if row.actual_expense_amount and row.actual_final_area:
				row["actual_rate_per_area"] = row.actual_expense_amount / row.actual_final_area
			else:
				row["actual_rate_per_area"] = 0
	return project_details