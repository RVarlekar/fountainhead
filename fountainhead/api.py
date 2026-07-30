import frappe
from frappe.utils import get_link_to_form
from frappe import _
from frappe.utils.nestedset import get_root_of

def get_level1_item_groups(doctype, name, order_by="lft desc", limit=None):
	
	"""Get ancestor elements of a DocType with a tree structure"""
	lft, rgt = frappe.db.get_value(doctype, name, ["lft", "rgt"])
	root_item_group=get_root_of(doctype)
	return frappe.get_all(
		doctype,
		{"lft": ["<", lft], "rgt": [">", rgt], 'parent_item_group':root_item_group},
		"name",
		order_by=order_by,
		limit_page_length=limit,
		pluck="name",
	)

def calculate_budget_in_child_table(self, method):
	"""
	Calculate the budget in the child table of the Project doctype.
	"""
	# Iterate through each child table row
	for row in self.custom_project:
		# Set the budget in the child table row
		row.budget_amount = (row.budget_area_in_sqft or 0) * (row.budget_area_rate_per_area or 0)
	
	ig = get_all_level_1_item_groups()
	print(ig,"=============")
	item = get_all_items_of_level_1_item_group("Information Technology")
	print(item,"-------------")

	item_group = get_level_1_item_group_of_any_item(item[0])
	print(item_group,"***************")
	# print(item_group,"+++++++++++++++++")

def get_all_level_1_item_groups():
	item_group_list = frappe.db.get_all("Item Group", 
										filters={"parent_item_group": "All Item Groups","is_group": 1},
										fields=["name"])
	print(item_group_list)
	return item_group_list

def get_level_1_item_group_of_any_item(item_name):
	item_group = frappe.db.get_value("Item", item_name, "item_group")
	level_1_item_group = None

	if item_group:
		print(item_group,"item_group")
		parent_item_group = frappe.db.get_value("Item Group", item_group, "parent_item_group")
		if parent_item_group and parent_item_group == "All Item Groups":
			level_1_item_group = item_group
		else:
			level_1_item_group = get_level1_item_groups("Item Group", item_group)
			print(level_1_item_group,type(level_1_item_group),"--")
			if len(level_1_item_group) > 0:
				level_1_item_group = level_1_item_group[0]
		return level_1_item_group

def get_all_items_of_level_1_item_group(item_group):
	all_item_list = frappe.db.get_all("Item",
								filters={"item_group":["Descendants Of (inclusive)", item_group]},
								fields=["name"])
	items = []
	if len(all_item_list) > 0:
		for item in all_item_list:
			items.append(item.name)
	return items

def get_all_service_items_of_level_1_item_group(item_group):
	service_item_list = frappe.db.get_all("Item",
									   filters={"item_group":["Descendants Of (inclusive)", item_group], "is_stock_item":0},
									   fields=["name"])
	service_item = []
	if len(service_item_list) > 0:
		for item in service_item_list:
			service_item.append(item.name)
	return service_item

def get_all_asset_items_of_level_1_item_group(item_group):
	asset_item_list = frappe.db.get_all("Item",
									   filters={"item_group":["Descendants Of (inclusive)", item_group], "is_fixed_asset":1},
									   fields=["name"])
	asset_item = []
	if len(asset_item_list) > 0:
		for item in asset_item_list:
			asset_item.append(item.name)
	return asset_item

def validate_budget_amount(self, method):
	if len(self.items)>0:
		for row in self.items:
			level1_item_group = get_level_1_item_group_of_any_item(row.item_code)

			if row.project and level1_item_group:
				available_budget_amount = get_budget_amount_from_project(row.project, level1_item_group)
				all_items_of_level1_item_group = get_all_items_of_level_1_item_group(level1_item_group)

				previous_purchase_order_amount = frappe.db.get_all("Purchase Order Item",
													   filters={"docstatus":1, "project": row.project,"item_code":["in",all_items_of_level1_item_group]},
													   fields=["sum(amount) as amount"])
				print(previous_purchase_order_amount, "previous_purchase_order_amount")
				if len(previous_purchase_order_amount) > 0:
					previous_purchase_order_amount = previous_purchase_order_amount[0].amount
					if previous_purchase_order_amount and available_budget_amount:
						total_required_amount = previous_purchase_order_amount + row.amount
						if total_required_amount > available_budget_amount:
							available_amount = available_budget_amount - previous_purchase_order_amount
							frappe.msgprint(_("Row {0}: Budget amount exceeded for item <b>{1}</b> and Parent Item Group <b>{2}</b> for project <b>{3}</b>. <br>Available budget Amount: <b>{4}</b> and Required Amount: <b>{5}</b>.").format(row.idx, row.item_code, level1_item_group, get_link_to_form("Project",row.project), available_amount, row.amount))

def get_budget_amount_from_project(project, item_group):
	available_budget_amount = frappe.db.get_value("Project Details",{"parent":project,"budget_area_item_group":item_group},"budget_amount")
	return available_budget_amount

def calculate_costing_total_in_workshop(self, method):
	total_cost = (self.registration_cost_inr or 0) +  (self.miscell_expenses_taxi_fare_food_lodging_boarding_etc or 0) + (self.tickets_travel or 0) + (self.teacher_compensation_if_on_non_working_day or 0)
	self.total = total_cost

def calculate_total_budget_amount(self, method):
	total_budget = 0
	if len(self.custom_project) > 0:
		for row in self.custom_project:
			if row.budget_amount:
				total_budget = total_budget + row.budget_amount
	self.custom_total_budget_amount = total_budget