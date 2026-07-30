# Copyright (c) 2025, GreyCube Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import add_to_date

class FHSIncomeForecast(Document):
	def validate(self):
		self.total_details()
		self.apr_may_amount()

	@frappe.whitelist()
	def load_all_grades(self):
		grades = frappe.db.get_all(
			doctype = 'FHS Grade',
			filters = {},
			fields = ['fhs_grade'],
			order_by = 'creation asc'
		)
		
		if len(grades) > 0:
			element =  grades.pop(0)
			grades.insert(2, element)

			for grade in grades:
				self.append('income_details', {
					'grade' : grade['fhs_grade']
				})

		self.save(ignore_permissions = True)
		return self
	
	def total_details(self):
		total_students = 0
		total_amounts = 0
		total_fees_amount_after_discount = 0
		if len(self.income_details) > 0:
			annual_fees = 0
			for income in self.income_details:
				no_of_students = income.noof_students
				fees_per_student = income.fees_per_year_per_student

				if no_of_students and fees_per_student > 0:
					annual_fees = no_of_students * fees_per_student
					income.annual_fees = annual_fees
					
					total_grade_discount = income.total_grade_discount
					if total_grade_discount != None:
						income.fees_amount_after_discount = annual_fees - total_grade_discount

					total_students = total_students + no_of_students
					total_amounts = total_amounts + annual_fees
					total_fees_amount_after_discount = total_fees_amount_after_discount + income.fees_amount_after_discount
			self.total_student = total_students
			self.total_amount = total_amounts		
			self.total_fees_amount_after_discount = total_fees_amount_after_discount
	def apr_may_amount(self):
		curr_academic_amt = 0
		prev_academic_amt = 0

		if len(self.income_details) > 0:
			# Current Academic Year Apr-May Amount (Less Amount)
			if self.total_amount > 0:
				curr_academic_amt = (self.total_fees_amount_after_discount / 12) * 2
				self.arp_may_amount = round(curr_academic_amt, 0)

			# Previous Academic Year Apr-May Amount (Add Amount)
			academic_start_date, academic_end_date = frappe.db.get_value(
				doctype = 'FHS Academic Year', 
				filters = {'name' : self.academic_year}, 
				fieldname = ['year_start_date', 'year_end_date']
			)

			prev_start_date = add_to_date(academic_start_date, months = -12)
			prev_end_date = add_to_date(academic_end_date, months = -12)
			
			prev_academic_year = frappe.db.get_value(
				doctype = "FHS Academic Year",
				filters = {
					'year_start_date' : prev_start_date,
					'year_end_date'   : prev_end_date
				},
				fieldname = ['name']
			)

			if prev_academic_year == None:
				frappe.msgprint("There Is No Previous Academic Year Available", alert = True)

			if prev_academic_year != None:
				income_account = self.income_account 

				prev_total_amount = frappe.db.get_value(
					doctype = "FHS Income Forecast",
					filters = {
						'academic_year' : prev_academic_year,
						'income_account' : income_account,
					},
					fieldname = ['total_fees_amount_after_discount']
				)
			
				if prev_total_amount != None:
					prev_academic_amt = (prev_total_amount / 12) * 2
					self.apr_may_amonut_prev_year = round(prev_academic_amt, 0) or 0