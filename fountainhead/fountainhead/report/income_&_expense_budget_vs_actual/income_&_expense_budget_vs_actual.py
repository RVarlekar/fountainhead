# Copyright (c) 2025, GreyCube Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from erpnext.accounts.report.financial_statements import (
	compute_growth_view_data,
	compute_margin_view_data,
	get_columns,
	get_data,
	get_filtered_list_for_consolidated_report,
	get_period_list,
)

def execute(filters):
	company = filters.get("company")
	fiscal_year = filters.get("fiscal_year")
	show_zero_values = filters.get("show_zero_values")
	filters = frappe._dict({
		'company' : company,
		'fiscal_year' : fiscal_year,
		'from_fiscal_year' : fiscal_year,
		'to_fiscal_year' : fiscal_year,
		'period_start_date' : frappe.db.get_value("Fiscal Year", fiscal_year, "year_start_date"),
		'period_end_date' : frappe.db.get_value("Fiscal Year", fiscal_year, "year_end_date"),
		'filter_based_on' : "Fiscal Year",
		'periodicity' : 'Yearly',
		'accumulated_values' : 1,
		'presentation_currency' : "INR",
		'include_default_book_entries' : 1,
		'selected_view' : "Report",
		'show_zero_values' : show_zero_values
	})

	period_list = get_period_list(
		filters.from_fiscal_year,
		filters.to_fiscal_year,
		filters.period_start_date,
		filters.period_end_date,
		filters.filter_based_on,
		filters.periodicity,
		company=filters.company,
	)

	income = get_data(
		filters.company,
		"Income",
		"Credit",
		period_list,
		filters=filters,
		accumulated_values=filters.accumulated_values,
		ignore_closing_entries=True,
	)

	expense = get_data(
		filters.company,
		"Expense",
		"Debit",
		period_list,
		filters=filters,
		accumulated_values=filters.accumulated_values,
		ignore_closing_entries=True,
	)

	net_profit_loss = get_net_profit_loss(
		income, expense, period_list, filters.company, filters.presentation_currency
	)

	data = []
	data.extend(income or [])
	data.extend(expense or [])
	if net_profit_loss:
		data.append(net_profit_loss)
	
	columns = get_columns(filters.periodicity, period_list, filters.accumulated_values, filters.company)
	
	add_budget_columns(columns)
	add_budget_data(data, filters)

	currency = filters.presentation_currency or frappe.get_cached_value(
		"Company", filters.company, "default_currency"
	)
	chart = get_chart_data(filters, columns, income, expense, net_profit_loss, currency)

	report_summary, primitive_summary = get_report_summary(
		period_list, filters.periodicity, income, expense, net_profit_loss, currency, filters
	)

	if filters.get("selected_view") == "Growth":
		compute_growth_view_data(data, period_list)

	if filters.get("selected_view") == "Margin":
		compute_margin_view_data(data, period_list, filters.accumulated_values)

	return columns, data, None, chart, report_summary, primitive_summary

def get_report_summary(
	period_list, periodicity, income, expense, net_profit_loss, currency, filters, consolidated=False
):
	net_income, net_expense, net_profit = 0.0, 0.0, 0.0
	budgeted_net_income, budgeted_net_expense, budgeted_net_profit_loss = 0.0, 0.0, 0.0

	# from consolidated financial statement
	if filters.get("accumulated_in_group_company"):
		period_list = get_filtered_list_for_consolidated_report(filters, period_list)

	if filters.accumulated_values:
		# when 'accumulated_values' is enabled, periods have running balance.
		# so, last period will have the net amount.
		key = period_list[-1].key
		if income:
			net_income = income[-2].get(key)
			budgeted_net_income =  income[-2].get("budgeted_amount")
		if expense:
			net_expense = expense[-2].get(key)
			budgeted_net_expense =  expense[-2].get("budgeted_amount")
		if net_profit_loss:
			net_profit = net_profit_loss.get(key)
			budgeted_net_profit_loss =  net_profit_loss.get("budgeted_amount")
	else:
		for period in period_list:
			key = period if consolidated else period.key
			if income:
				net_income += income[-2].get(key)
			if expense:
				net_expense += expense[-2].get(key)
			if net_profit_loss:
				net_profit += net_profit_loss.get(key)

	if len(period_list) == 1 and periodicity == "Yearly":
		profit_label = _("Profit This Year")
		income_label = _("Total Income This Year")	
		expense_label = _("Total Expense This Year")
		budgeted_profit_label = _("Budget Profit This Year")
		budgeted_income_label = _("Total Budget Income This Year")
		budgeted_expense_label = _("Total Budget Expense This Year")
	else:
		profit_label = _("Net Profit")
		income_label = _("Total Income")
		expense_label = _("Total Expense")

	return [
		{"value": net_income, "label": income_label, "datatype": "Currency", "currency": currency},
		{"type": "separator", "value": "-"},
		{"value": net_expense, "label": expense_label, "datatype": "Currency", "currency": currency},
		{"type": "separator", "value": "=", "color": "blue"},
		{
			"value": net_profit,
			"indicator": "Green" if net_profit > 0 else "Red",
			"label": profit_label,
			"datatype": "Currency",
			"currency": currency,
		},

		{"value": budgeted_net_income, "label": budgeted_income_label, "datatype": "Currency", "currency": currency},
		{"type": "separator", "value": "-"},
		{"value": budgeted_net_expense, "label": budgeted_expense_label, "datatype": "Currency", "currency": currency},
		{"type": "separator", "value": "=", "color": "blue"},
		{
			"value": budgeted_net_profit_loss,
			"indicator": "Green" if budgeted_net_profit_loss > 0 else "Red",
			"label": budgeted_profit_label,
			"datatype": "Currency",
			"currency": currency,
		},
	], net_profit

def get_net_profit_loss(income, expense, period_list, company, currency=None, consolidated=False):
	total = 0
	net_profit_loss = {
		"account_name": "'" + _("Profit for the year") + "'",
		"account": "'" + _("Profit for the year") + "'",
		"warn_if_negative": True,
		"currency": currency or frappe.get_cached_value("Company", company, "default_currency"),
	}

	has_value = False

	for period in period_list:
		key = period if consolidated else period.key
		total_income = flt(income[-2][key], 3) if income else 0
		total_expense = flt(expense[-2][key], 3) if expense else 0

		net_profit_loss[key] = total_income - total_expense

		if net_profit_loss[key]:
			has_value = True

		total += flt(net_profit_loss[key])
		net_profit_loss["total"] = total

	if has_value:
		return net_profit_loss

def get_chart_data(filters, columns, income, expense, net_profit_loss, currency):
	labels = [d.get("label") for d in columns[2:]]

	income_data, expense_data, net_profit = [], [], []

	for p in columns[2:]:
		if income:
			income_data.append(income[-2].get(p.get("fieldname")))
		if expense:
			expense_data.append(expense[-2].get(p.get("fieldname")))
		if net_profit_loss:
			net_profit.append(net_profit_loss.get(p.get("fieldname")))

	datasets = []
	if income_data:
		datasets.append({"name": _("Income"), "values": income_data})
	if expense_data:
		datasets.append({"name": _("Expense"), "values": expense_data})
	if net_profit:
		datasets.append({"name": _("Net Profit/Loss"), "values": net_profit})

	chart = {"data": {"labels": labels, "datasets": datasets}}

	if not filters.accumulated_values:
		chart["type"] = "bar"
	else:
		chart["type"] = "line"

	chart["fieldtype"] = "Currency"
	chart["options"] = "currency"
	chart["currency"] = currency

	return chart

def add_budget_columns(columns):
	col = {
		"fieldname":"budgeted_amount",
		"label":"Budget Amount",
		"fieldtype":"Currency",
		"options":"currency",
		"width":150
   	}
	columns.append(col)

def get_account_budget_map(filters):
	company = filters.get("company")
	fiscal_year = filters.get("fiscal_year")
	docname = frappe.db.get_value(
		"FHS Income And Expense Forecast",
		filters = {
			"company" : company,
			"fiscal_year" : fiscal_year
		},
		fieldname = ['name']
	)
	budgets = {}
	if docname != None:
		
		doc = frappe.get_doc("FHS Income And Expense Forecast", docname)
		if doc != None and len(doc.accounts_details) > 0:
			for detail in doc.accounts_details:
				budgets.update({
					detail.account: detail.budget_amount
				})

	return budgets

def add_budget_data(data, filters):
	# Assigning Budget Values From Doctype
	account_budget_map = get_account_budget_map(filters)
	parent_accounts = {}
	if account_budget_map == {}:
		frappe.msgprint("No Income and Expense Accounts Budget Found For Fiscal Year {0}".format(filters.get("fiscal_year")), alert=True)

	for d in data:
		if d != {} and d.get("is_group") == 0:
			d.update({
				"budgeted_amount" : account_budget_map[d.get("account")] if account_budget_map != {} else 0
			})
		elif d != {} and d.get("is_group") == 1:
			parent_accounts.update({d.get("account"): {'amount' : 0, "parent" : d.get("parent_account")}})

	# Calculating Root Nodes Total
	for acc in data:
		if acc != {} and acc.get("parent_account") != "" and "budgeted_amount" in acc:
			parent_accounts[acc.parent_account]['amount'] = parent_accounts[acc.parent_account]['amount'] + acc.budgeted_amount

	res = dict(reversed(list(parent_accounts.items())))
	for p in res:
		if parent_accounts[p]['parent'] != "":
			parent_accounts[parent_accounts[p]['parent']]['amount'] = parent_accounts[parent_accounts[p]['parent']]['amount'] + parent_accounts[p]['amount']

	for d in data:
		if d != {} and d.get("is_group") == 1:
			d.update({
				"budgeted_amount" : parent_accounts[d.get("account")]['amount']
			})
	
	# Calculating Total Income, Expense and Profit.
	income_nodes = frappe.db.get_all("Account", {'root_type': "Income", "is_group":1, "report_type":"Profit and Loss"}, pluck="name")
	expense_nodes = frappe.db.get_all("Account", {'root_type': "Expense", "is_group":1, "report_type":"Profit and Loss"}, pluck="name")

	total_income = 0
	total_expense = 0
	
	for ti in data:
		if ti.get("indent") == 0 and  ti.get("account") in income_nodes:
			total_income = total_income + ti.budgeted_amount
		if ti.get("indent") == 0 and  ti.get("account") in expense_nodes:
			total_expense = total_expense + ti.budgeted_amount
	
	for t in data:
		if t.get("account") == "'Total Income (Credit)'":
			t.update({"budgeted_amount" : total_income})
		if t.get("account") == "'Total Expense (Debit)'":
			t.update({"budgeted_amount" : total_expense})
		if t.get("account") ==  "'Profit for the year'":
			t.update({"budgeted_amount" : total_income - total_expense})