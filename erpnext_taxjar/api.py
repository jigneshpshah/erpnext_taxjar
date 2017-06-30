import requests
import frappe
import hashlib
import json
import taxjar
from frappe.utils.background_jobs import enqueue


def get_client():
	taxjar_settings = frappe.get_single("TaxJar Settings")
	client = taxjar.Client(api_key=taxjar_settings.get_password("api_key"))
	return client


def set_sales_tax(doc, method):
	if not doc.items:
		return

	taxjar_settings = frappe.get_single("TaxJar Settings")

	client = get_client()
	tax_dict = get_tax_data(doc)

	if not tax_dict:
		return

	taxdata = client.tax_for_order(tax_dict)

	if "Sales Tax" in [tax.description for tax in doc.taxes]:
		for tax in doc.taxes:
			if tax.description == "Sales Tax":
				tax.tax_amount = taxdata.amount_to_collect
				break
	elif taxdata.amount_to_collect > 0:
		doc.append("taxes", {
			"charge_type": "Actual",
			"description": "Sales Tax",
			"account_head": taxjar_settings.tax_account_head,
			"tax_amount": taxdata.amount_to_collect
		})

		doc.run_method("calculate_taxes_and_totals")


def create_transaction(doc, method):

	client = get_client()
	sales_tax = 0
	for tax in doc.taxes:
		if tax.account_head == "Sales Tax - JA":
			sales_tax = tax.tax_amount

	if not sales_tax:
		return

	tax_dict = get_tax_data(doc)
	if not tax_dict:
		return

	tax_dict['transaction_id'] = doc.name
	tax_dict['transaction_date'] = frappe.utils.today()
	tax_dict['sales_tax'] = sales_tax
	tax_dict['amount'] = doc.total + tax_dict['shipping']	

	print tax_dict

	client.create_order(tax_dict)

def delete_transaction(doc, method):
	client = get_client()
	client.delete_order(doc.name)


def get_tax_data(doc):
	taxjar_settings = frappe.get_single("TaxJar Settings")

	client = get_client()
	if not (taxjar_settings.api_key or taxjar_settings.tax_account_head):
		return

	client = taxjar.Client(api_key=taxjar_settings.get_password("api_key"))

	company_address = frappe.get_doc("Address", {"is_your_company_address": 1})
	if company_address and doc.shipping_address_name:
		shipping_address = frappe.get_doc("Address", doc.shipping_address_name)
	else:
		return

	if not shipping_address.country == "United States":
		return

	shipping = 0
	for tax in doc.taxes:
		if tax.account_head == "Freight and Forwarding Charges - JA":
			shipping = tax.tax_amount

	tax_dict = {
		'to_country': 'US',
		'to_zip': shipping_address.pincode,
		'to_city': shipping_address.city,
		'to_state': shipping_address.state,
		'shipping': shipping,
		'line_items': []
	}

	index = 1
	for item in doc.items:
		tax_dict["line_items"].append({
			"id": index,
			"description": item.item_name,
			"unit_price": item.price_list_rate,
			"quantity": item.qty,
			"discount": (item.discount_percentage / 100) * item.price_list_rate
		})

		index = index + 1

	return tax_dict
