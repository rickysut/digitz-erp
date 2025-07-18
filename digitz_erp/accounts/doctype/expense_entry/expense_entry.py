# Copyright (c) 2023, Rupesh P and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import datetime, timedelta
from digitz_erp.api.document_posting_status_api import init_document_posting_status, update_posting_status
from digitz_erp.api.gl_posting_api import update_accounts_for_doc_type, delete_gl_postings_for_cancel_doc_type
from digitz_erp.api.settings_api import add_seconds_to_time
from digitz_erp.api.accounts_api import calculate_utilization

class ExpenseEntry(Document):

	def Voucher_In_The_Same_Time(self):
		possible_invalid= frappe.db.count('Expense Entry', {'posting_date': ['=', self.posting_date], 'posting_time':['=', self.posting_time]})
		return possible_invalid

	def Set_Posting_Time_To_Next_Second(self):
		# Add 12 seconds to self.posting_time and update it
		self.posting_time = add_seconds_to_time(str(self.posting_time), seconds=12)
  
	
	def validate_expense_budgets(self):
		"""
		Validate Expense Entry accounts against the budget values and utilized amounts.

		This method is intended to be called during the validate event of the Expense Entry.
		"""
		for expense in self.expense_entry_details:
			# Fetch budget details for the expense account
			budget_item = frappe.db.get_value(
				"Budget Item",
				{"reference_type": "Account", "reference_value": expense.expense_account},
				["parent", "budget_amount"],
				as_dict=True
			)

			if not budget_item:
				# Skip validation if no budget exists for the expense account
				continue

			# Get the parent budget details
			budget = frappe.get_doc("Budget", budget_item["parent"])

			# Fetch utilized amount
			utilized_amount = calculate_utilization(
				budget_against=budget.budget_against,
				item_budget_against="Expense",
				budget_against_value=getattr(budget, budget.budget_against.lower()),
				reference_type="Account",
				reference_value=expense.expense_account,
				from_date=budget.from_date,
				to_date=budget.to_date,
			)

			# Calculate total utilized
			total_utilized = utilized_amount + expense.amount

			# Check if total utilized exceeds budget amount
			if total_utilized > budget_item["budget_amount"]:
				frappe.throw(
					f"Expense Account {expense.expense_account} exceeds its budget limit. "
					f"Budget Amount: {budget_item['budget_amount']}, "
					f"Utilized: {utilized_amount}, "
					f"Expense Amount in Entry: {expense.amount}, "
					f"Total Utilized: {total_utilized}."
				)

	def validate(self):
		self.validate_expense_budgets()     


	def before_validate(self):

		if(self.Voucher_In_The_Same_Time()):

				self.Set_Posting_Time_To_Next_Second()

				if(self.Voucher_In_The_Same_Time()):
					self.Set_Posting_Time_To_Next_Second()

					if(self.Voucher_In_The_Same_Time()):
						self.Set_Posting_Time_To_Next_Second()

						if(self.Voucher_In_The_Same_Time()):
							frappe.throw("Voucher with same time already exists.")
    
		if not self.credit_expense:
			self.paid_amount = self.grand_total      

	def on_submit(self):

		init_document_posting_status(self.doctype,self.name)

		self.postings_start_time = datetime.now()
		turn_off_background_job = frappe.db.get_single_value("Global Settings",'turn_off_background_job')

		# if(frappe.session.user == "Administrator" and turn_off_background_job):
		# 	self.do_postings_on_submit()
		# else:
		# 	frappe.enqueue(self.do_postings_on_submit, queue="long")

		self.do_postings_on_submit()
		self.update_project_expenses()

	def on_cancel(self):

		update_posting_status(self.doctype,self.name,'posting_status','Cancel Pending')

		self.cancel_expense()
		self.update_project_expenses(cancel=True)

	def cancel_expense(self):

		delete_gl_postings_for_cancel_doc_type('Expense Entry',self.name)

		# frappe.db.delete("GL Posting",
		# 		{"Voucher_type": "Expense Entry",
		# 		 "voucher_no":self.name
		# 		})

		update_posting_status(self.doctype,self.name, "posting_status", "Completed")


	def do_postings_on_submit(self):

		idx = self.insert_gl_records()
		update_posting_status(self.doctype,self.name,'gl_posted_time')

		self.insert_payment_postings()

		update_posting_status(self.doctype,self.name,'payment_posted_time')

		update_accounts_for_doc_type('Expense Entry',self.name)

		update_posting_status(self.doctype,self.name,'posting_status','Completed')

	def insert_gl_records(self):

		idx = 1

		# Debit Expenses
		for expense_entry in self.expense_entry_details:

			gl_doc = frappe.new_doc('GL Posting')
			gl_doc.idx = idx
			gl_doc.voucher_type = 'Expense Entry'
			gl_doc.voucher_no = self.name
			gl_doc.posting_date = expense_entry.expense_date
			gl_doc.account = expense_entry.expense_account
			gl_doc.debit_amount = expense_entry.amount
			gl_doc.remarks = self.remarks;
			gl_doc.project = self.project
			gl_doc.insert()

			idx += 1

		# Debit Tax Amounts
		taxes = self.get_tax_totals()
		#print("taxes")
		#print(taxes)

		for key, tax_amount  in taxes.items():

			#print("key")
			#print(key)

			tax_for_expense, expense_date = key.split('_')

			#print("tax_for_expense")
			#print(tax_for_expense)

			tax = frappe.get_doc("Tax", tax_for_expense)

			if(tax.tax_rate >0):
				gl_doc = frappe.new_doc('GL Posting')
				gl_doc.idx = idx
				gl_doc.voucher_type = 'Expense Entry'
				gl_doc.voucher_no = self.name
				gl_doc.posting_date = expense_date
				gl_doc.account = tax.account
				gl_doc.debit_amount = tax_amount
				gl_doc.remarks = self.remarks;
				gl_doc.project = self.project
				gl_doc.insert()
				idx += 1

		# Credit Payable Accounts, supplier
		payable_items = self.get_payable_totals()

		for key, amount  in payable_items.items():

			payable_account, supplier, expense_date = key.split('_')

			gl_doc = frappe.new_doc('GL Posting')
			gl_doc.idx = idx
			gl_doc.voucher_type = 'Expense Entry'
			gl_doc.voucher_no = self.name
			gl_doc.posting_date = expense_date
			gl_doc.account = payable_account
			gl_doc.party_type = "Supplier"
			gl_doc.party = supplier
			gl_doc.credit_amount = amount
			gl_doc.remarks = self.remarks;
			gl_doc.project = self.project
			gl_doc.insert()
			idx += 1

	def get_payable_totals(self):

		payable_account_dictionary = {}

		for expense_entry in self.expense_entry_details:

			payable_account = expense_entry.get("payable_account")
			supplier = expense_entry.get("supplier")
			expense_date = expense_entry.get("expense_date")
			total = expense_entry.get("total")
			key = f"{payable_account}_{supplier}_{expense_date}"

			if key in payable_account_dictionary:
				payable_account_dictionary[key] += total
			else:
				payable_account_dictionary[key] = total

		return payable_account_dictionary

	# Need to consider the payment account for each expense date
	def get_payment_totals(self):

		payment_account_dictionary = {}

		for expense_entry in self.expense_entry_details:

			payment_account = self.payment_account

			expense_date = expense_entry.get("expense_date")

			key = f"{payment_account}_{expense_date}"

			if key in payment_account_dictionary:
				payment_account_dictionary[key] += expense_entry.total
			else:
				payment_account_dictionary[key] = expense_entry.total

		return payment_account_dictionary

	def get_tax_totals(self):
		tax_dictionary = {}

		for expense_entry in self.expense_entry_details:
			tax_amount = expense_entry.get("tax_amount")

			if(tax_amount>0):
				tax = expense_entry.get("tax")
				tax_amount = expense_entry.get("tax_amount")
				expense_date = expense_entry.get("expense_date")

				#print("tax from get_tax_totals")
				#print(tax)

				# Use the expense_date in the key along with tax, separated by an underscore
				key = f"{tax}_{expense_date}"
				#print("key from get_tax_totals")
				#print(key)

				if key in tax_dictionary:
					tax_dictionary[key] += tax_amount
				else:
					tax_dictionary[key] = tax_amount

		#print("tax_dictionary")
		#print(tax_dictionary)
		return tax_dictionary

	def insert_payment_postings(self):

		if not self.credit_expense:

			gl_count = frappe.db.count('GL Posting',{'voucher_type':'Expense Entry', 'voucher_no': self.name})

			idx= gl_count + 1
			payable_items = self.get_payable_totals()

			for key, amount  in payable_items.items():

				payable_account, supplier,expense_date = key.split('_')

				gl_doc = frappe.new_doc('GL Posting')
				gl_doc.idx = idx
				gl_doc.voucher_type = 'Expense Entry'
				gl_doc.voucher_no = self.name
				gl_doc.posting_date = expense_date
				gl_doc.account = payable_account
				gl_doc.party_type = "Supplier"
				gl_doc.party = supplier
				gl_doc.debit_amount = amount
				gl_doc.remarks = self.remarks;
				gl_doc.insert()
				idx += 1

			payment_items = self.get_payment_totals()

			for key,amount in payment_items.items():
				payment_account,expense_date = key.split('_')

				gl_doc = frappe.new_doc('GL Posting')
				gl_doc.idx = idx
				gl_doc.voucher_type = 'Expense Entry'
				gl_doc.voucher_no = self.name
				gl_doc.posting_date = expense_date
				gl_doc.account = payment_account
				gl_doc.credit_amount = amount
				gl_doc.remarks = self.remarks;
				gl_doc.insert()
				idx += 1

	def on_update(self):
		self.update_payment_schedules()

	def update_payment_schedules(self):

		existing_entries = frappe.get_all("Payment Schedule", filters={"payment_against": "Expense", "document_no": self.name})


		# Delete existing payment schedules if found
		for entry in existing_entries:
			try:
				frappe.delete_doc("Payment Schedule", entry.name)
			except Exception as e:
				frappe.log_error("Error deleting payment schedule: " + str(e))


		#print("self.payment_schedule")
		#print(self.payment_schedule)

		for payment_schedule in self.payment_schedule:

			new_payment_schedule = frappe.new_doc("Payment Schedule")
			new_payment_schedule.payment_against = "Expense"
			new_payment_schedule.supplier = payment_schedule.supplier
			new_payment_schedule.document_no = self.name
			new_payment_schedule.document_date = self.posting_date
			new_payment_schedule.scheduled_date = payment_schedule.date
			new_payment_schedule.amount = payment_schedule.amount

			try:
				new_payment_schedule.insert()
				frappe.msgprint("payment schedule added successfully",indicator="green", alert = True)
			except Exception as e:
				frappe.log_error("Error creating payment schedule: " + str(e))
				frappe.msgprint("An error occured while inserting payment schedule",indicator="red", alert = True)

		frappe.db.commit()
  
	def update_project_expenses(self, cancel=False):
     
		if self.project:
			# Exclude the current document and include only submitted documents
			filters = {
				"project": self.project,
				"name": ["!=", self.name],  # Exclude the current document
				"docstatus": 1  # Include only submitted documents
			}

			# Fetch all submitted expenses related to the project, excluding the current document
			expenses = frappe.get_all(
				"Expense Entry",
				filters=filters,
				fields=["name"]
			)

			total_excluded_tax = 0
	
			print(expenses)

			# Iterate through each expense (other than the current document)
			for expense in expenses:
				# Fetch items for the current expense
				expense_items = frappe.get_all(
					"Expense Entry Details",
					filters={"parent": expense.name},
					fields=["amount_excluded_tax"]
				)
    
				print("expense_items")
				print(expense_items)

				# Sum up the amount_excluded_tax for the items in this expense
				for item in expense_items:
					total_excluded_tax += item.get("amount_excluded_tax", 0)

			# If not cancelling, add the current document's contribution
			if not cancel:
				# # Fetch items for the current document
				# current_expense_items = frappe.get_all(
				# 	"Expense Entry Details",
				# 	filters={"parent": self.name},
				# 	fields=["amount_excluded_tax"]
				# )

				# Add the current document's contribution to the total
				for item in self.expense_entry_details:
					total_excluded_tax += item.get("amount_excluded_tax", 0)

			# Update the 'overheads' column in the Project
			frappe.db.set_value(
				"Project",
				self.project,
				"overheads",
				total_excluded_tax
			)

			# Optional: Feedback or logging
			frappe.msgprint(
				f"The 'overheads' of project {self.project} has been updated successfully.",alert=True
			)
