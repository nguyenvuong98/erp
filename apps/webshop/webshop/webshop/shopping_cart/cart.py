# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
import frappe.defaults
from frappe import _, throw
from frappe.contacts.doctype.address.address import get_address_display
from frappe.contacts.doctype.contact.contact import get_contact_name
from frappe.utils import cint, cstr, flt, get_fullname
from frappe.utils.nestedset import get_root_of

from erpnext.accounts.utils import get_account_name
from webshop.webshop.doctype.webshop_settings.webshop_settings import (
    get_shopping_cart_settings,
)
from webshop.webshop.utils.product import get_web_item_qty_in_stock
from erpnext.selling.doctype.quotation.quotation import _make_sales_order


class WebsitePriceListMissingError(frappe.ValidationError):
    pass


def set_cart_count(quotation=None):
	if cint(frappe.db.get_singles_value("Webshop Settings", "enabled")):
		if not quotation:
			quotation = _get_cart_quotation()
		cart_count = cstr(cint(quotation.get("total_qty")))

		if hasattr(frappe.local, "cookie_manager"):
			frappe.local.cookie_manager.set_cookie("cart_count", cart_count)


@frappe.whitelist()
def get_cart_quotation(doc=None):
	party = get_party()

	if not doc:
		quotation = _get_cart_quotation(party)
		doc = quotation
		set_cart_count(quotation)

	addresses = get_address_docs(party=party)

	if not doc.customer_address and addresses:
		update_cart_address("billing", addresses[0].name)

	return {
		"doc": decorate_quotation_doc(doc),
		"shipping_addresses": get_shipping_addresses(party),
		"billing_addresses": get_billing_addresses(party),
		"shipping_rules": get_applicable_shipping_rules(party),
		"cart_settings": frappe.get_cached_doc("Webshop Settings"),
	}


@frappe.whitelist()
def get_shipping_addresses(party=None):
	if not party:
		party = get_party()
	addresses = get_address_docs(party=party)
	return [
		{
			"name": address.name,
			"title": address.address_title,
			"display": address.display,
		}
		for address in addresses
		if address.address_type == "Shipping"
	]


@frappe.whitelist()
def get_billing_addresses(party=None):
	if not party:
		party = get_party()
	addresses = get_address_docs(party=party)
	return [
		{
			"name": address.name,
			"title": address.address_title,
			"display": address.display,
		}
		for address in addresses
		if address.address_type == "Billing"
	]


@frappe.whitelist()
def place_order():
	quotation = _get_cart_quotation()
	cart_settings = frappe.get_cached_doc("Webshop Settings")
	quotation.company = cart_settings.company

	quotation.flags.ignore_permissions = True
	quotation.submit()

	if quotation.quotation_to == "Lead" and quotation.party_name:
		# company used to create customer accounts
		frappe.defaults.set_user_default("company", quotation.company)

	if not (quotation.shipping_address_name or quotation.customer_address):
		frappe.throw(_("Set Shipping Address or Billing Address"))

	sales_order = frappe.get_doc(
		_make_sales_order(
			quotation.name, ignore_permissions=True
		)
	)
	sales_order.payment_schedule = []

	# Copy custom_end_customer from quotation to sales order
	if hasattr(quotation, 'custom_end_customer') and quotation.custom_end_customer:
		sales_order.custom_end_customer = quotation.custom_end_customer

	if not cint(cart_settings.allow_items_not_in_stock):
		for item in sales_order.get("items"):
			item.warehouse = frappe.db.get_value(
				"Website Item", {"item_code": item.item_code}, "website_warehouse"
			)
			is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")

			if is_stock_item:
				item_stock = get_web_item_qty_in_stock(
					item.item_code, "website_warehouse"
				)
				if not cint(item_stock.in_stock):
					throw(_("{0} Not in Stock").format(item.item_code))
				if item.qty > item_stock.stock_qty:
					throw(
						_("Only {0} in Stock for item {1}").format(
							item_stock.stock_qty, item.item_code
						)
					)

	sales_order.flags.ignore_permissions = True
	sales_order.insert()
	sales_order.submit()

	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.delete_cookie("cart_count")

	return sales_order.name


@frappe.whitelist()
def add_to_cart(item_code, qty, additional_notes=None, with_items=False):
	"""Add item to cart - will ADD to existing quantity instead of replacing"""
	frappe.log_error(f"DEBUG: add_to_cart called with item_code={item_code}, qty={qty}")
	
	quotation = _get_cart_quotation()

	qty = flt(qty)
	if qty <= 0:
		return {"name": quotation.name, "message": "Invalid quantity"}

	warehouse = frappe.get_cached_value(
		"Website Item", {"item_code": item_code}, "website_warehouse"
	)

	quotation_items = quotation.get("items", {"item_code": item_code})
	if not quotation_items:
		# Add new item
		frappe.log_error(f"DEBUG: Adding NEW item {item_code} with qty {qty}")
		quotation.append(
			"items",
			{
				"doctype": "Quotation Item",
				"item_code": item_code,
				"qty": qty,
				"additional_notes": additional_notes,
				"warehouse": warehouse,
			},
		)
	else:
		# ADD to existing quantity instead of replacing
		old_qty = flt(quotation_items[0].qty)
		new_qty = old_qty + qty
		frappe.log_error(f"DEBUG: ADDING to existing item {item_code}: {old_qty} + {qty} = {new_qty}")
		quotation_items[0].qty = new_qty
		quotation_items[0].warehouse = warehouse
		if additional_notes:
			quotation_items[0].additional_notes = additional_notes

	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.payment_schedule = []
	quotation.save()

	set_cart_count(quotation)

	if cint(with_items):
		context = get_cart_quotation(quotation)
		return {
			"items": frappe.render_template(
				"templates/includes/cart/cart_items.html", context
			),
			"total": frappe.render_template(
				"templates/includes/cart/cart_items_total.html", context
			),
			"taxes_and_totals": frappe.render_template(
				"templates/includes/cart/cart_payment_summary.html", context
			),
		}
	else:
		return {"name": quotation.name}


@frappe.whitelist()
def request_for_quotation():
	quotation = _get_cart_quotation()
	quotation.flags.ignore_permissions = True

	if get_shopping_cart_settings().save_quotations_as_draft:
		quotation.save()
	else:
		quotation.submit()

	return quotation.name


@frappe.whitelist()
def update_cart(item_code, qty, additional_notes=None, with_items=False, customer=None, shipping_address_name=None, custom_note=None, add_qty=False):
	quotation = _get_cart_quotation()

	# Handle custom note update
	if custom_note is not None:
		quotation.custom_note = custom_note
		quotation.flags.ignore_permissions = True
		quotation.save()
		return {"name": quotation.name, "message": "Note updated successfully"}

	# Handle selected customer update (including clearing with empty string)
	if customer is not None:
		quotation.custom_end_customer = customer if customer else None
		quotation.flags.ignore_permissions = True
		quotation.save()
		message = "Selected customer cleared" if not customer else "Selected customer updated successfully"
		return {"name": quotation.name, "message": message}
	
	# Handle shipping address update (including clearing with empty string)
	if shipping_address_name is not None:
		quotation.shipping_address_name = shipping_address_name if shipping_address_name else None
		quotation.flags.ignore_permissions = True
		quotation.save()
		message = "Shipping address cleared" if not shipping_address_name else "Shipping address updated successfully"
		return {"name": quotation.name, "message": message}

	empty_card = False
	qty = flt(qty)
	if qty == 0:
		quotation_items = quotation.get("items", {"item_code": ["!=", item_code]})
		if quotation_items:
			quotation.set("items", quotation_items)
		else:
			empty_card = True

	else:
		warehouse = frappe.get_cached_value(
			"Website Item", {"item_code": item_code}, "website_warehouse"
		)

		quotation_items = quotation.get("items", {"item_code": item_code})
		if not quotation_items:
			# Get purchase price from Item
			purchase_price = frappe.get_value("Item", item_code, "custom_purchase_price") or 0
			
			quotation.append(
				"items",
				{
					"doctype": "Quotation Item",
					"item_code": item_code,
					"qty": qty,
					"additional_notes": additional_notes,
					"warehouse": warehouse,
					"custom_purchase_price": purchase_price,
				},
			)
		else:
			if add_qty:
				# ADD to existing quantity (for "buy now" from product listing)
				quotation_items[0].qty = flt(quotation_items[0].qty) + qty
			else:
				# REPLACE quantity (for cart page direct updates)
				quotation_items[0].qty = qty
			quotation_items[0].warehouse = warehouse
			quotation_items[0].additional_notes = additional_notes

	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.payment_schedule = []
	if not empty_card:
		quotation.save()
	else:
		try:
			quotation.delete()
		except Exception as e:
			# Handle database errors during quotation deletion
			frappe.log_error(f"Error deleting quotation: {str(e)}")
			# Force delete using raw SQL if normal deletion fails
			frappe.db.sql("DELETE FROM `tabQuotation` WHERE name = %s", quotation.name)
			frappe.db.sql("DELETE FROM `tabQuotation Item` WHERE parent = %s", quotation.name)
			frappe.db.commit()
		quotation = None

	set_cart_count(quotation)

	if cint(with_items):
		context = get_cart_quotation(quotation)
		return {
			"items": frappe.render_template(
				"templates/includes/cart/cart_items.html", context
			),
			"total": frappe.render_template(
				"templates/includes/cart/cart_items_total.html", context
			),
			"taxes_and_totals": frappe.render_template(
				"templates/includes/cart/cart_payment_summary.html", context
			),
		}
	else:
		return {"name": quotation.name}


@frappe.whitelist()
def get_shopping_cart_menu(context=None):
	if not context:
		context = get_cart_quotation()

	return frappe.render_template("templates/includes/cart/cart_dropdown.html", context)


@frappe.whitelist()
def add_new_address(doc):
	doc = frappe.parse_json(doc)
	doc.update({"doctype": "Address"})
	address = frappe.get_doc(doc)
	address.save(ignore_permissions=True)

	return address


@frappe.whitelist(allow_guest=True)
def create_lead_for_item_inquiry(lead, subject, message):
	lead = frappe.parse_json(lead)
	lead_doc = frappe.new_doc("Lead")
	for fieldname in ("lead_name", "company_name", "email_id", "phone"):
		lead_doc.set(fieldname, lead.get(fieldname))

	lead_doc.set("lead_owner", "")

	if not frappe.db.exists("Lead Source", "Product Inquiry"):
		frappe.get_doc(
			{"doctype": "Lead Source", "source_name": "Product Inquiry"}
		).insert(ignore_permissions=True)

	lead_doc.set("source", "Product Inquiry")

	try:
		lead_doc.save(ignore_permissions=True)
	except frappe.exceptions.DuplicateEntryError:
		frappe.clear_messages()
		lead_doc = frappe.get_doc("Lead", {"email_id": lead["email_id"]})

	lead_doc.add_comment(
		"Comment",
		text="""
		<div>
			<h5>{subject}</h5>
			<p>{message}</p>
		</div>
	""".format(
			subject=subject, message=message
		),
	)

	return lead_doc


@frappe.whitelist()
def get_terms_and_conditions(terms_name):
	return frappe.db.get_value("Terms and Conditions", terms_name, "terms")


@frappe.whitelist()
def update_cart_address(address_type, address_name):
	quotation = _get_cart_quotation()
	address_doc = frappe.get_doc("Address", address_name).as_dict()
	address_display = get_address_display(address_doc)

	if address_type.lower() == "billing":
		quotation.customer_address = address_name
		quotation.address_display = address_display
		quotation.shipping_address_name = (
			quotation.shipping_address_name or address_name
		)
		address_doc = next(
			(doc for doc in get_billing_addresses() if doc["name"] == address_name),
			None,
		)
	elif address_type.lower() == "shipping":
		quotation.shipping_address_name = address_name
		quotation.shipping_address = address_display
		quotation.customer_address = quotation.customer_address or address_name
		address_doc = next(
			(doc for doc in get_shipping_addresses() if doc["name"] == address_name),
			None,
		)
	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.save()

	context = get_cart_quotation(quotation)
	context["address"] = address_doc

	return {
		"taxes": frappe.render_template(
			"templates/includes/order/order_taxes.html", context
		),
		"address": frappe.render_template(
			"templates/includes/cart/address_card.html", context
		),
	}


def guess_territory():
	territory = None
	geoip_country = frappe.session.get("session_country")
	if geoip_country:
		territory = frappe.db.get_value("Territory", geoip_country)

	return (
		territory
		or get_root_of("Territory")
	)


def decorate_quotation_doc(doc):
	for d in doc.get("items", []):
		item_code = d.item_code
		fields = ["web_item_name", "thumbnail", "website_image", "description", "route"]

		# Variant Item
		if not frappe.db.exists("Website Item", {"item_code": item_code}):
			variant_data = frappe.db.get_values(
				"Item",
				filters={"item_code": item_code},
				fieldname=["variant_of", "item_name", "image"],
				as_dict=True,
			)[0]
			item_code = variant_data.variant_of
			fields = fields[1:]
			d.web_item_name = variant_data.item_name

			if variant_data.image:  # get image from variant or template web item
				d.thumbnail = variant_data.image
				fields = fields[2:]

		d.update(
			frappe.db.get_value(
				"Website Item", {"item_code": item_code}, fields, as_dict=True
			)
		)

		website_warehouse = frappe.get_cached_value(
			"Website Item", {"item_code": item_code}, "website_warehouse"
		)

		d.warehouse = website_warehouse

	return doc


def _get_cart_quotation(party=None):
	"""Return the open Quotation of type "Shopping Cart" or make a new one"""
	if not party:
		party = get_party()

	quotation = frappe.get_all(
		"Quotation",
		fields=["name"],
		filters={
			"party_name": party.name,
			"contact_email": frappe.session.user,
			"order_type": "Shopping Cart",
			"docstatus": 0,
		},
		order_by="modified desc",
		limit_page_length=1,
	)

	if quotation:
		qdoc = frappe.get_doc("Quotation", quotation[0].name)
	else:
		company = frappe.db.get_single_value("Webshop Settings", "company")
		qdoc = frappe.get_doc(
			{
				"doctype": "Quotation",
				"naming_series": get_shopping_cart_settings().quotation_series
				or "QTN-CART-",
				"quotation_to": party.doctype,
				"company": company,
				"order_type": "Shopping Cart",
				"status": "Draft",
				"docstatus": 0,
				"__islocal": 1,
				"party_name": party.name,
			}
		)

		qdoc.contact_person = frappe.db.get_value(
			"Contact", {"email_id": frappe.session.user}
		)
		qdoc.contact_email = frappe.session.user

		qdoc.flags.ignore_permissions = True
		qdoc.run_method("set_missing_values")
		apply_cart_settings(party, qdoc)

	return qdoc


def update_party(fullname, company_name=None, mobile_no=None, phone=None):
	party = get_party()

	party.customer_name = company_name or fullname
	party.customer_type = "Company" if company_name else "Individual"

	contact_name = frappe.db.get_value("Contact", {"email_id": frappe.session.user})
	contact = frappe.get_doc("Contact", contact_name)
	contact.first_name = fullname
	contact.last_name = None
	contact.customer_name = party.customer_name
	contact.mobile_no = mobile_no
	contact.phone = phone
	contact.flags.ignore_permissions = True
	contact.save()

	party_doc = frappe.get_doc(party.as_dict())
	party_doc.flags.ignore_permissions = True
	party_doc.save()

	qdoc = _get_cart_quotation(party)
	if not qdoc.get("__islocal"):
		qdoc.customer_name = company_name or fullname
		qdoc.run_method("set_missing_lead_customer_details")
		qdoc.flags.ignore_permissions = True
		qdoc.save()


def apply_cart_settings(party=None, quotation=None):
	if not party:
		party = get_party()
	if not quotation:
		quotation = _get_cart_quotation(party)

	cart_settings = frappe.get_cached_doc("Webshop Settings")

	set_price_list_and_rate(quotation, cart_settings)

	quotation.run_method("calculate_taxes_and_totals")

	set_taxes(quotation, cart_settings)

	_apply_shipping_rule(party, quotation, cart_settings)


def set_price_list_and_rate(quotation, cart_settings):
	"""set price list based on billing territory"""

	_set_price_list(cart_settings, quotation)

	# Debug: Log before clearing values
	frappe.log_error(f"CART: Before reset - Price List: {quotation.selling_price_list}, Currency: {quotation.currency}", "Cart Price Debug")

	# reset values
	quotation.price_list_currency = (
		quotation.currency
	) = quotation.plc_conversion_rate = quotation.conversion_rate = None
	for item in quotation.get("items"):
		old_rate = item.rate
		item.price_list_rate = item.discount_percentage = item.rate = item.amount = None
		frappe.log_error(f"CART: Reset item {item.item_code} - Old rate: {old_rate}, Reset to None", "Cart Price Debug")

	# DEBUG: Log before setting price details
	# frappe.log_error(f"CART: Before set_price_list_and_item_details - Price List: {quotation.selling_price_list}, Items: {[item.item_code for item in quotation.get('items')]}", "Cart Price Debug")
	

	try:
		# refetch values
		quotation.run_method("set_price_list_and_item_details")
	except Exception as e:
		frappe.log_error(f"CART: Error in set_price_list_and_item_details: {str(e)}", "Cart Price Error")
		# Fallback: manually set prices
		_manual_set_item_prices(quotation)

	# DEBUG: Log after setting price details
	for item in quotation.get("items"):
		frappe.log_error(f"CART: After set_price_list_and_item_details - Item: {item.item_code}, Price List Rate: {item.price_list_rate}, Rate: {item.rate}, Amount: {item.amount}", "Cart Price Debug")

	if hasattr(frappe.local, "cookie_manager"):
		# set it in cookies for using in product page
		frappe.local.cookie_manager.set_cookie(
			"selling_price_list", quotation.selling_price_list
		)


def _manual_set_item_prices(quotation):
	"""Manually set item prices as fallback when automatic method fails"""
	frappe.log_error("CART: Using manual price setting as fallback", "Cart Price Debug")
	
	for item in quotation.get("items"):
		try:
			# First try to get price directly from Item Price
			item_price = frappe.db.get_value("Item Price", {
				"item_code": item.item_code,
				"price_list": quotation.selling_price_list
			}, ["price_list_rate"], as_dict=True)
			
			if item_price and item_price.price_list_rate:
				item.price_list_rate = flt(item_price.price_list_rate)
				item.rate = flt(item_price.price_list_rate)
				item.amount = flt(item.rate) * flt(item.qty)
				
				frappe.log_error(f"CART: Direct price set for {item.item_code} - Rate: {item.rate}, Amount: {item.amount}", "Cart Price Debug")
				continue
			
			# If no direct price found, try get_item_details
			from erpnext.stock.get_item_details import get_item_details
			
			args = {
				'item_code': item.item_code,
				'company': quotation.company,
				'price_list': quotation.selling_price_list,
				'qty': item.qty,
				'uom': item.uom or frappe.db.get_value("Item", item.item_code, "stock_uom"),
				'warehouse': item.warehouse,
				'customer': quotation.party_name,
				'currency': quotation.currency or frappe.db.get_single_value("Company", quotation.company, "default_currency"),
				'conversion_rate': quotation.conversion_rate or 1,
				'transaction_date': quotation.transaction_date,
				'plc_conversion_rate': quotation.plc_conversion_rate or 1,
				'doctype': 'Quotation',
				'name': quotation.name
			}
			
			item_details = get_item_details(args)
			
			# Update item with fetched details
			item.price_list_rate = item_details.get('price_list_rate', 0)
			item.rate = item_details.get('rate', 0)
			item.amount = flt(item.rate) * flt(item.qty)
			
			frappe.log_error(f"CART: Manual price set for {item.item_code} - Rate: {item.rate}, Amount: {item.amount}", "Cart Price Debug")
			
		except Exception as e:
			frappe.log_error(f"CART: Error in manual price setting for {item.item_code}: {str(e)}", "Cart Price Error")
			
			# Last resort: try to get any price for this item
			try:
				fallback_price = frappe.db.get_value("Item Price", {
					"item_code": item.item_code,
					"price_list": quotation.selling_price_list
				}, "price_list_rate")
				
				if fallback_price:
					item.price_list_rate = item.rate = flt(fallback_price)
					item.amount = flt(item.rate) * flt(item.qty)
					frappe.log_error(f"CART: Fallback price set for {item.item_code} - Rate: {item.rate}", "Cart Price Debug")
				else:
					# Set default values
					item.rate = item.price_list_rate = 0
					item.amount = 0
					frappe.log_error(f"CART: No price found for {item.item_code}, set to 0", "Cart Price Debug")
			except:
				item.rate = item.price_list_rate = 0
				item.amount = 0


def _set_price_list(cart_settings, quotation=None):
	"""Set price list based on customer or shopping cart default"""
	from erpnext.accounts.party import get_default_price_list

	party_name = quotation.get("party_name") if quotation else get_party().get("name")
	selling_price_list = None

	frappe.log_error(f"CART: _set_price_list - Party: {party_name}", "Cart Price List Debug")

	# check if default customer price list exists
	if party_name and frappe.db.exists("Customer", party_name):
		try:
			customer_doc = frappe.get_doc("Customer", party_name)
			selling_price_list = get_default_price_list(customer_doc)
			frappe.log_error(f"CART: Customer {party_name} default price list: {selling_price_list}", "Cart Price List Debug")
		except Exception as e:
			frappe.log_error(f"CART: Error getting customer price list: {str(e)}", "Cart Price List Debug")

	# check default price list in shopping cart
	if not selling_price_list:
		selling_price_list = cart_settings.price_list
		frappe.log_error(f"CART: Using cart settings price list: {selling_price_list}", "Cart Price List Debug")

	# Fallback to standard selling price list if none found
	if not selling_price_list:
		selling_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
		frappe.log_error(f"CART: Using selling settings price list: {selling_price_list}", "Cart Price List Debug")

	# Last resort - get any active selling price list
	if not selling_price_list:
		price_lists = frappe.get_all("Price List", 
			filters={"enabled": 1, "selling": 1}, 
			fields=["name"], 
			limit=1
		)
		if price_lists:
			selling_price_list = price_lists[0].name
			frappe.log_error(f"CART: Using first available price list: {selling_price_list}", "Cart Price List Debug")

	# DEBUG: Log price list being used in cart
	frappe.log_error(f"CART: Final price list selected: {selling_price_list} for party: {party_name}", "Cart Price List Debug")

	if quotation:
		quotation.selling_price_list = selling_price_list

	return selling_price_list


@frappe.whitelist()
def fix_cart_prices():
	"""Force fix cart prices by directly updating from Item Price"""
	try:
		quotation = _get_cart_quotation()
		
		if not quotation:
			return {"error": "No cart found"}
		
		frappe.log_error(f"FIX PRICES: Starting fix for quotation {quotation.name} with {len(quotation.get('items'))} items", "Cart Price Fix")
		
		fixed_items = []
		total_fixed = 0
		
		for item in quotation.get("items"):
			# Get price directly from Item Price table
			item_price_data = frappe.db.get_value("Item Price", {
				"item_code": item.item_code,
				"price_list": quotation.selling_price_list
			}, ["price_list_rate", "currency"], as_dict=True)
			
			if item_price_data and item_price_data.price_list_rate:
				old_rate = flt(item.rate)
				new_rate = flt(item_price_data.price_list_rate)
				
				# Only update if the rate is different
				if old_rate != new_rate:
					item.price_list_rate = new_rate
					item.rate = new_rate
					item.amount = flt(new_rate) * flt(item.qty)
					
					fixed_items.append({
						"item_code": item.item_code,
						"old_rate": old_rate,
						"new_rate": new_rate,
						"amount": item.amount,
						"qty": item.qty
					})
					
					total_fixed += 1
					frappe.log_error(f"FIXED: Item {item.item_code} - Old Rate: {old_rate}, New Rate: {new_rate}, Amount: {item.amount}", "Cart Price Fix")
				else:
					frappe.log_error(f"SKIP: Item {item.item_code} already has correct price: {old_rate}", "Cart Price Fix")
			else:
				frappe.log_error(f"NO PRICE: Item {item.item_code} has no price in {quotation.selling_price_list}", "Cart Price Fix")
				
				# Try to find any available price
				any_price = frappe.db.get_value("Item Price", {
					"item_code": item.item_code
				}, ["price_list_rate", "price_list"], as_dict=True)
				
				if any_price:
					frappe.log_error(f"FOUND ALTERNATIVE: Item {item.item_code} has price {any_price.price_list_rate} in {any_price.price_list}", "Cart Price Fix")
		
		# Force recalculate taxes and totals
		try:
			quotation.run_method("calculate_taxes_and_totals")
			frappe.log_error(f"SUCCESS: Recalculated taxes and totals", "Cart Price Fix")
		except Exception as calc_error:
			frappe.log_error(f"ERROR: Failed to recalculate taxes: {str(calc_error)}", "Cart Price Fix")
		
		# Save the quotation
		quotation.flags.ignore_permissions = True
		quotation.save()
		
		result = {
			"message": f"Cart prices fixed successfully - {total_fixed} items updated", 
			"quotation": quotation.name,
			"fixed_items": fixed_items,
			"total_fixed": total_fixed,
			"grand_total": flt(quotation.grand_total),
			"net_total": flt(quotation.net_total)
		}
		
		frappe.log_error(f"FIX COMPLETE: {result}", "Cart Price Fix")
		return result
		
	except Exception as e:
		error_msg = f"Error fixing cart prices: {str(e)}"
		frappe.log_error(error_msg, "Cart Price Fix Error")
		frappe.log_error(frappe.get_traceback(), "Cart Price Fix Error")
		return {"error": error_msg}


@frappe.whitelist()
def force_fix_all_items():
	"""Force fix all items in cart by rebuilding price structure"""
	try:
		quotation = _get_cart_quotation()
		
		if not quotation:
			return {"error": "No cart found"}
		
		# Store current items
		current_items = []
		for item in quotation.get("items"):
			current_items.append({
				"item_code": item.item_code,
				"qty": item.qty,
				"warehouse": item.warehouse,
				"additional_notes": getattr(item, 'additional_notes', '')
			})
		
		# Clear all items
		quotation.items = []
		
		# Re-add each item with fresh pricing
		for item_data in current_items:
			# Get fresh price
			item_price = frappe.db.get_value("Item Price", {
				"item_code": item_data["item_code"],
				"price_list": quotation.selling_price_list
			}, "price_list_rate")
			
			if item_price:
				quotation.append("items", {
					"doctype": "Quotation Item",
					"item_code": item_data["item_code"],
					"qty": item_data["qty"],
					"warehouse": item_data["warehouse"],
					"additional_notes": item_data["additional_notes"],
					"price_list_rate": flt(item_price),
					"rate": flt(item_price),
					"amount": flt(item_price) * flt(item_data["qty"])
				})
		
		# Recalculate
		quotation.run_method("calculate_taxes_and_totals")
		quotation.flags.ignore_permissions = True
		quotation.save()
		
		return {
			"message": "Cart completely rebuilt with fresh prices",
			"quotation": quotation.name,
			"items_count": len(quotation.get("items")),
			"grand_total": quotation.grand_total
		}
		
	except Exception as e:
		return {"error": str(e)}


@frappe.whitelist()
def get_cart_summary():
	"""Get detailed cart summary for debugging"""
	try:
		quotation = _get_cart_quotation()
		
		summary = {
			"quotation_details": {
				"name": quotation.name,
				"grand_total": quotation.grand_total,
				"net_total": quotation.net_total,
				"total_taxes_and_charges": quotation.total_taxes_and_charges,
				"selling_price_list": quotation.selling_price_list,
				"currency": quotation.currency,
				"conversion_rate": quotation.conversion_rate,
				"company": quotation.company,
				"customer": quotation.party_name,
				"custom_end_customer": getattr(quotation, 'custom_end_customer', None)
			},
			"items": [],
			"taxes": []
		}
		
		for item in quotation.get("items", []):
			summary["items"].append({
				"item_code": item.item_code,
				"item_name": item.item_name,
				"qty": item.qty,
				"rate": item.rate,
				"amount": item.amount,
				"price_list_rate": item.price_list_rate,
				"warehouse": item.warehouse
			})
		
		for tax in quotation.get("taxes", []):
			summary["taxes"].append({
				"charge_type": tax.charge_type,
				"account_head": tax.account_head,
				"rate": tax.rate,
				"tax_amount": tax.tax_amount,
				"total": tax.total
			})
		
		return summary
		
	except Exception as e:
		return {"error": str(e)}


def set_taxes(quotation, cart_settings):
	"""set taxes based on billing territory"""
	from erpnext.accounts.party import set_taxes

	customer_group = frappe.db.get_value(
		"Customer", quotation.party_name, "customer_group"
	)

	quotation.taxes_and_charges = set_taxes(
		quotation.party_name,
		"Customer",
		quotation.transaction_date,
		quotation.company,
		customer_group=customer_group,
		supplier_group=None,
		tax_category=quotation.tax_category,
		billing_address=quotation.customer_address,
		shipping_address=quotation.shipping_address_name,
		use_for_shopping_cart=1,
	)
	#
	# 	# clear table
	quotation.set("taxes", [])
	#
	# 	# append taxes
	quotation.append_taxes_from_master()
	quotation.append_taxes_from_item_tax_template()


def get_party(user=None):
	if not user:
		user = frappe.session.user

	contact_name = get_contact_name(user)
	party = None

	if contact_name:
		contact = frappe.get_doc("Contact", contact_name)
		if contact.links:
			party_doctype = contact.links[0].link_doctype
			party = contact.links[0].link_name

	cart_settings = frappe.get_cached_doc("Webshop Settings")

	debtors_account = ""

	if cart_settings.enable_checkout:
		debtors_account = get_debtors_account(cart_settings)

	if party:
		doc = frappe.get_doc(party_doctype, party)
		if doc.doctype in ["Customer", "Supplier"]:
			if not frappe.db.exists("Portal User", {"parent": doc.name, "user": user}):
				doc.append("portal_users", {"user": user})
				doc.flags.ignore_permissions = True
				doc.flags.ignore_mandatory = True
				doc.save()

		return doc

	elif not frappe.db.exists("Portal User", {"user": user}):
		if not cart_settings.enabled:
			frappe.local.flags.redirect_location = "/contact"
			raise frappe.Redirect
		customer = frappe.new_doc("Customer")
		fullname = get_fullname(user)
		customer.update(
			{
				"customer_name": fullname,
				"customer_type": "Individual",
				"customer_group": get_shopping_cart_settings().default_customer_group,
				"territory": get_root_of("Territory"),
			}
		)

		customer.append("portal_users", {"user": user})

		if debtors_account:
			customer.update(
				{
					"accounts": [
						{"company": cart_settings.company, "account": debtors_account}
					]
				}
			)

		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)

		contact = frappe.new_doc("Contact")
		contact.update(
			{"first_name": fullname, "email_ids": [{"email_id": user, "is_primary": 1}]}
		)
		contact.append("links", dict(link_doctype="Customer", link_name=customer.name))
		contact.flags.ignore_mandatory = True
		contact.insert(ignore_permissions=True)

		return customer
	else:
		customer = frappe.db.get_value(
			"Portal User", {"user": user}, ["parent"]
		)

		if frappe.db.exists("Customer", customer):
			return frappe.get_doc("Customer", customer)


def get_debtors_account(cart_settings):
	if not cart_settings.payment_gateway_account:
		frappe.throw(_("Payment Gateway Account not set"), _("Mandatory"))

	payment_gateway_account_currency = frappe.get_doc(
		"Payment Gateway Account", cart_settings.payment_gateway_account
	).currency

	account_name = _("Debtors ({0})").format(payment_gateway_account_currency)

	debtors_account_name = get_account_name(
		"Receivable",
		"Asset",
		is_group=0,
		account_currency=payment_gateway_account_currency,
		company=cart_settings.company,
	)

	if not debtors_account_name:
		debtors_account = frappe.get_doc(
			{
				"doctype": "Account",
				"account_type": "Receivable",
				"root_type": "Asset",
				"is_group": 0,
				"parent_account": get_account_name(
					root_type="Asset", is_group=1, company=cart_settings.company
				),
				"account_name": account_name,
				"currency": payment_gateway_account_currency,
			}
		).insert(ignore_permissions=True)

		return debtors_account.name

	else:
		return debtors_account_name


def get_address_docs(
    doctype=None,
    txt=None,
    filters=None,
    limit_start=0,
    limit_page_length=20,
    party=None,
):
	if not party:
		party = get_party()

	if not party:
		return []

	address_names = frappe.db.get_all(
		"Dynamic Link",
		fields=("parent"),
		filters=dict(
			parenttype="Address", link_doctype=party.doctype, link_name=party.name
		),
	)

	out = []

	for a in address_names:
		address = frappe.get_doc("Address", a.parent)
		address.display = get_address_display(address.as_dict())
		out.append(address)

	return out


@frappe.whitelist()
def apply_shipping_rule(shipping_rule):
	quotation = _get_cart_quotation()

	quotation.shipping_rule = shipping_rule

	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.save()

	return get_cart_quotation(quotation)


def _apply_shipping_rule(party=None, quotation=None, cart_settings=None):
	if not quotation.shipping_rule:
		shipping_rules = get_shipping_rules(quotation, cart_settings)

		if not shipping_rules:
			return

		elif quotation.shipping_rule not in shipping_rules:
			quotation.shipping_rule = shipping_rules[0]

	if quotation.shipping_rule:
		quotation.run_method("apply_shipping_rule")
		quotation.run_method("calculate_taxes_and_totals")


def get_applicable_shipping_rules(party=None, quotation=None):
	shipping_rules = get_shipping_rules(quotation)

	if shipping_rules:
		rule_label_map = frappe.db.get_values("Shipping Rule", shipping_rules, "label")
		# we need this in sorted order as per the position of the rule in the settings page
		return [[rule, rule] for rule in shipping_rules]


def get_shipping_rules(quotation=None, cart_settings=None):
	if not quotation:
		quotation = _get_cart_quotation()

	shipping_rules = []
	if quotation.shipping_address_name:
		country = frappe.db.get_value(
			"Address", quotation.shipping_address_name, "country"
		)
		if country:
			sr_country = frappe.qb.DocType("Shipping Rule Country")
			sr = frappe.qb.DocType("Shipping Rule")
			query = (
				frappe.qb.from_(sr_country)
				.join(sr)
				.on(sr.name == sr_country.parent)
				.select(sr.name)
				.distinct()
				.where((sr_country.country == country) & (sr.disabled != 1) & (sr.shipping_rule_type == "Selling"))
			)
			result = query.run(as_list=True)
			shipping_rules = [x[0] for x in result]

	return shipping_rules


def get_address_territory(address_name):
	"""Tries to match city, state and country of address to existing territory"""
	territory = None

	if address_name:
		address_fields = frappe.db.get_value(
			"Address", address_name, ["city", "state", "country"]
		)
		for value in address_fields:
			territory = frappe.db.get_value("Territory", value)
			if territory:
				break

	return territory


def show_terms(doc):
	return doc.tc_name


@frappe.whitelist(allow_guest=True)
def apply_coupon_code(applied_code, applied_referral_sales_partner):
	quotation = True

	if not applied_code:
		frappe.throw(_("Please enter a coupon code"))

	coupon_list = frappe.get_all("Coupon Code", filters={"coupon_code": applied_code})
	if not coupon_list:
		frappe.throw(_("Please enter a valid coupon code"))

	coupon_name = coupon_list[0].name

	from erpnext.accounts.doctype.pricing_rule.utils import validate_coupon_code

	validate_coupon_code(coupon_name)
	quotation = _get_cart_quotation()
	quotation.ignore_pricing_rule = 0
	quotation.coupon_code = coupon_name
	quotation.flags.ignore_permissions = True
	quotation.save()

	if applied_referral_sales_partner:
		sales_partner_list = frappe.get_all(
			"Sales Partner", filters={"referral_code": applied_referral_sales_partner}
		)
		if sales_partner_list:
			sales_partner_name = sales_partner_list[0].name
			quotation.referral_sales_partner = sales_partner_name
			quotation.flags.ignore_permissions = True
			quotation.save()

	return quotation

 
@frappe.whitelist(allow_guest=True)
def remove_coupon_code():
	quotation = _get_cart_quotation()
	quotation.coupon_code = ""
	quotation.referral_sales_partner = ""
	quotation.flags.ignore_permissions = True

	# reset discount amount if coupon code is removed (on desk it is done in client side)
	# as we are enabling ignore_pricing_rule, so we also need to manually reset discount percentage
	quotation.discount_amount = 0
	quotation.additional_discount_percentage = 0
	quotation.ignore_pricing_rule = 1

	quotation.save()

	return quotation


@frappe.whitelist(allow_guest=True)
def apply_discount_percentage(discount_percentage):
	"""Apply discount percentage to cart"""
	quotation = _get_cart_quotation()
	
	# Validate discount percentage
	try:
		discount_percentage = float(discount_percentage)
		if discount_percentage < 0 or discount_percentage > 100:
			frappe.throw(_("Discount percentage must be between 0 and 100"))
	except (ValueError, TypeError):
		frappe.throw(_("Invalid discount percentage"))
	
	# Apply discount to quotation
	quotation.additional_discount_percentage = discount_percentage
	quotation.apply_discount_on="Net Total"
	# Update each item's p_discount and discount
	for item in quotation.get("items"):
		# Set p_discount equal to the cart discount percentage
		# frappe.db.set_value('Quotation Item', item.name, 'custom_p_discount', discount_percentage)
		item.custom_p_discount = discount_percentage
		# Calculate and set the discount amount
		item.custom_discount = (item.amount or 0) * (discount_percentage / 100)
		item.custom_e_amount = item.amount - item.custom_discount
		# frappe.db.set_value('Quotation Item', item.name, 'custom_discount', custom_discount)
	
	quotation.flags.ignore_permissions = True
	quotation.save()
	
	return quotation


@frappe.whitelist(allow_guest=True)
def remove_discount():
	"""Remove discount from cart"""
	quotation = _get_cart_quotation()
	
	# Remove discount from quotation
	quotation.additional_discount_percentage = 0
	quotation.discount_amount = 0
	
	# Remove discount from all items
	for item in quotation.get("items", []):
		item.p_discount = 0
		item.discount = 0
	
	quotation.flags.ignore_permissions = True
	quotation.save()
	
	return quotation


@frappe.whitelist()
def get_customer_addresses(customer=None):
	"""Get addresses for a specific customer"""
	if not customer:
		party = get_party()
		if not party:
			return []
		customer = party.name
	
	try:
		# Get customer doc
		customer_doc = frappe.get_doc("Customer", customer)
		
		# Get addresses using the existing function
		addresses = get_address_docs(party=customer_doc)
		
		# Format addresses for frontend
		address_list = []
		for addr in addresses:
			address_list.append({
				"name": addr.name,
				"address_title": addr.address_title,
				"address_line1": addr.address_line1,
				"address_line2": addr.address_line2 or "",
				"city": addr.city or "",
				"state": addr.state or "",
				"country": addr.country or "",
				"pincode": addr.pincode or "",
				"is_primary_address": addr.is_primary_address,
				"display": addr.display
			})
		
		return address_list
		
	except Exception as e:
		frappe.log_error(f"Error getting customer addresses: {str(e)}")
		return []


@frappe.whitelist()
def test_add_cart():
	"""Test method to check if our add_to_cart is working"""
	return {"message": "add_to_cart method is available", "timestamp": frappe.utils.now()}


@frappe.whitelist()
def get_selected_customer():
	"""Get the selected customer from current cart quotation"""
	try:
		quotation = _get_cart_quotation()
		if hasattr(quotation, 'custom_end_customer') and quotation.custom_end_customer:
			customer_doc = frappe.get_doc("Customer", quotation.custom_end_customer)
			return {
				"id": customer_doc.name,
				"name": customer_doc.customer_name,
				"customer_type": customer_doc.customer_type
			}
		return None
	except Exception as e:
		frappe.log_error(f"Error getting selected customer: {str(e)}")
		return None


@frappe.whitelist()
def get_end_customer_from_order(sales_order_name):
	"""Get the end customer from a specific sales order"""
	try:
		sales_order = frappe.get_doc("Sales Order", sales_order_name)
		if hasattr(sales_order, 'custom_end_customer') and sales_order.custom_end_customer:
			customer_doc = frappe.get_doc("Customer", sales_order.custom_end_customer)
			return {
				"id": customer_doc.name,
				"name": customer_doc.customer_name,
				"customer_type": customer_doc.customer_type
			}
		return None
	except Exception as e:
		frappe.log_error(f"Error getting end customer from order: {str(e)}")
		return None


def copy_custom_fields_from_quotation(doc, method):
	"""Hook function to copy custom fields from quotation to sales order"""
	if doc.doctype == "Sales Order" and doc.prevdoc_docname:
		try:
			# Get the source quotation
			quotation = frappe.get_doc("Quotation", doc.prevdoc_docname)
			
			# Copy custom_end_customer if exists
			if hasattr(quotation, 'custom_end_customer') and quotation.custom_end_customer:
				doc.custom_end_customer = quotation.custom_end_customer
				
		except Exception as e:
			frappe.log_error(f"Error copying custom fields from quotation: {str(e)}")


@frappe.whitelist()
def debug_cart_prices():
	"""Debug method to check cart prices and price list"""
	try:
		quotation = _get_cart_quotation()
		party = get_party()
		cart_settings = frappe.get_cached_doc("Webshop Settings")
		
		debug_info = {
			"quotation_name": quotation.name,
			"party_name": party.name if party else None,
			"party_type": party.doctype if party else None,
			"selling_price_list": quotation.selling_price_list,
			"currency": quotation.currency,
			"price_list_currency": quotation.price_list_currency,
			"conversion_rate": quotation.conversion_rate,
			"plc_conversion_rate": quotation.plc_conversion_rate,
			"cart_settings_price_list": cart_settings.price_list,
			"items": []
		}
		
		for item in quotation.get("items", []):
			item_info = {
				"item_code": item.item_code,
				"qty": item.qty,
				"price_list_rate": item.price_list_rate,
				"rate": item.rate,
				"amount": item.amount,
				"warehouse": item.warehouse
			}
			debug_info["items"].append(item_info)
		
		# Check if price list exists and has prices for items
		for item in quotation.get("items", []):
			price_exists = frappe.db.exists("Item Price", {
				"item_code": item.item_code,
				"price_list": quotation.selling_price_list
			})
			item_info = next((x for x in debug_info["items"] if x["item_code"] == item.item_code), None)
			if item_info:
				item_info["price_in_price_list"] = bool(price_exists)
				if price_exists:
					item_price = frappe.get_doc("Item Price", {
						"item_code": item.item_code,
						"price_list": quotation.selling_price_list
					})
					item_info["item_price_rate"] = item_price.price_list_rate
		
		return debug_info
		
	except Exception as e:
		return {"error": str(e)}


@frappe.whitelist()
def force_recalculate_cart():
	"""Force recalculate all cart prices"""
	try:
		quotation = _get_cart_quotation()
		
		# Force recalculation
		apply_cart_settings(quotation=quotation)
		
		quotation.flags.ignore_permissions = True
		quotation.save()
		
		return {"message": "Cart recalculated successfully", "quotation": quotation.name}
		
	except Exception as e:
		frappe.log_error(f"Error force recalculating cart: {str(e)}")
		return {"error": str(e)}


@frappe.whitelist()
def check_item_prices(item_codes=None):
	"""Check prices for specific items or all items in cart"""
	try:
		if not item_codes:
			quotation = _get_cart_quotation()
			item_codes = [item.item_code for item in quotation.get("items", [])]
		
		if isinstance(item_codes, str):
			item_codes = [item_codes]
		
		price_info = []
		
		# Get all active price lists
		price_lists = frappe.get_all("Price List", 
			filters={"enabled": 1, "selling": 1}, 
			fields=["name", "currency"]
		)
		
		for item_code in item_codes:
			item_prices = []
			
			for price_list in price_lists:
				price_data = frappe.db.get_value("Item Price", {
					"item_code": item_code,
					"price_list": price_list.name
				}, ["price_list_rate", "valid_from", "valid_upto"], as_dict=True)
				
				if price_data:
					item_prices.append({
						"price_list": price_list.name,
						"currency": price_list.currency,
						"rate": price_data.price_list_rate,
						"valid_from": price_data.valid_from,
						"valid_upto": price_data.valid_upto
					})
			
			price_info.append({
				"item_code": item_code,
				"prices": item_prices
			})
		
		return price_info
		
	except Exception as e:
		return {"error": str(e)}


@frappe.whitelist()
def search_customers_by_staff(keyword=""):
	from frappe import _
	
	# Lấy user hiện tại
	current_user_email = frappe.session.user
	
	# Lấy username từ User table nếu cần
	user_doc = frappe.get_doc("User", current_user_email)
	username = user_doc.username  # Tùy trường bạn dùng
	
	# Nếu là Administrator thì không lọc
	if current_user_email == "Administrator":
		filters = []
	else:
		# Lọc theo username thay vì email
		filters = [
			["custom_staffinchargeid", "=", username]
		]
	
	# Thêm điều kiện tìm kiếm theo keyword nếu có
	if keyword:
		filters.append(["customer_name", "like", f"%{keyword}%"])
	
	# Lấy danh sách khách hàng
	customers = frappe.get_all(
		"Customer",
		filters=filters,
		fields=["name", "customer_name", "mobile_no", "email_id", "custom_staffinchargeid"],
		limit=20,
		order_by="customer_name asc"
	)
	
	return customers