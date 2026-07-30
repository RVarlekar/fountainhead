# Copyright (c) 2025, GreyCube Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def execute(filters=None):
	if not filters: 
		filters = {}

	columns, data = [], []
	columns = get_columns()
	data = get_data(filters)

	if not data:
		frappe.msgprint("No Data Found!")

	return columns, data

def get_columns():
	return [
		{
			'fieldname' : 'grade',
			'fieldtype' : 'Data',
			'label' : _('Grade'),
			'width' : 300,
		},
		{
			'fieldname' : 'no_of_students',
			'fieldtype' : 'Float',
			'label' : _('No of Students'),
			'width' : 150,
		},
		{
			'fieldname' : 'expected',
			'fieldtype' : 'Currency',
			'label' : _('Expected'),
			'width' : 150,
		},
		{
			'fieldname' : 'actual',
			'fieldtype' : 'Currency',
			'label' : _('Actual'),
			'width' : 150,
		}
	]

def get_conditions(filters):
	# Academic Year Based On Fiscal Year 
	fiscal_year_start_date = frappe.db.get_value('Fiscal Year', {'name' : filters.get('fiscal_year')} ,['year_start_date'])
	fiscal_year_end_date = frappe.db.get_value('Fiscal Year', {'name' : filters.get('fiscal_year')} ,['year_end_date'])

	academic_year = frappe.db.sql(
		f'''
		SELECT tfay.name
		FROM `tabFHS Academic Year` tfay 
		WHERE tfay.year_start_date > '{fiscal_year_start_date}' AND tfay.year_start_date < '{fiscal_year_end_date}';
		''',
	as_dict = 1)
	
	condition = ""
	if academic_year:
		if filters.get('grade'):
			condition += f"fhs.academic_year = '{academic_year[0].name}' AND fhs.income_account = '{filters.get('income_account')}' AND tifd.grade = '{filters.get('grade')}'"
		else:
			condition += f"fhs.academic_year = '{academic_year[0].name}' AND fhs.income_account = '{filters.get('income_account')}'"
	else:
		frappe.throw(f"No Academic Year Corresponding To Fiscal Year {filters.get('fiscal_year')}")

	return condition

def get_data(filters):
	condition = get_conditions(filters)
	data = []

	# Orderwise Grades List
	grades = frappe.db.get_all(
		doctype = 'FHS Grade',
		filters = {},
		fields = ['fhs_grade'],
		order_by = 'creation asc'
	)
		
	# If Grades Available Then Fetch Income Forecasts Data
	if len(grades) > 0:
		element =  grades.pop(0)
		grades.insert(2, element)

		# Income Forecast Data For The Current Fiscal Year
		incomes = frappe.db.sql(
			f'''
			SELECT 
				tifd.grade, tifd.noof_students, tifd.fees_amount_after_discount, fhs.arp_may_amount as curr_amt, fhs.apr_may_amonut_prev_year as prev_amt, fhs.total_fees_amount_after_discount
			FROM 
				`tabFHS Income Forecast` AS fhs 
			INNER JOIN 
				`tabIncome Forecast Details` tifd 
			WHERE 
				{condition}
			AND 
				tifd.parent = fhs.name
			'''
		,as_dict = 1)

		# If Income Forecast Data Is Available Then Find(Actual) Sales Invoice Data For Each Grade
		if len(incomes) > 0:
			for grade in grades:

				# Sales Invoice Data Between Fiscal Year Start And End Date (Grouped By Grade and Income Account)
				sales_data = frappe.db.sql(
					f'''
					SELECT 
						SUM(tsii.amount) AS "actualSum"
					FROM 
						`tabSales Invoice Item` tsii 
					INNER JOIN 
						`tabSales Invoice` tsi 
					WHERE 
						tsi.posting_date 
						BETWEEN '{frappe.db.get_value('Fiscal Year', {'name' : filters.get('fiscal_year')} ,['year_start_date'])}' 
						AND '{frappe.db.get_value('Fiscal Year', {'name' : filters.get('fiscal_year')} ,['year_end_date'])}'
					AND 
						tsii.income_account  = '{filters.get('income_account')}' AND tsii.fhs_grade = '{grade.fhs_grade}' AND tsii.parent = tsi.name AND tsi.docstatus = 1;
					''',
				as_dict = 1)

				for income in incomes:
					if income.grade == grade.fhs_grade:
						row = frappe._dict({
							'grade' : grade.fhs_grade,
							'no_of_students' : income.noof_students,
							'expected' : income.fees_amount_after_discount,
							'actual' : sales_data[0].actualSum
						})
						data.append(row)
			
			# Last 3 (Addition, Minus and Total) Rows
			add_row = frappe._dict({
				'grade' : 'Add: Fees Of Last Year April & May',
				'no_of_students' : None,
				'expected' : incomes[0].prev_amt,
				'actual' : None
			})
			data.append(add_row)

			less_row = frappe._dict({
				'grade' : 'Less: Fees Of Current Year April & May',
				'no_of_students' : None,
				'expected' : incomes[0].curr_amt,
				'actual' : None
			})
			data.append(less_row)

			total_row = frappe._dict({
				'grade' : 'TOTAL',
				'no_of_students' : None,
				'expected' : (incomes[0].total_fees_amount_after_discount + incomes[0].prev_amt) - incomes[0].curr_amt,
				'actual' : None
			})
			data.append(total_row)
	return data