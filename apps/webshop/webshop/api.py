import frappe
from frappe import _
from frappe.utils import cstr

@frappe.whitelist(allow_guest=True)
def search_customers(search_term, limit=15):
    """Search customers by name, email, mobile, or tax ID"""
    
    if not search_term or len(search_term) < 2:
        return []
    
    search_term = cstr(search_term).strip()
    search_pattern = f"%{search_term}%"
    
    try:
        # Use SQL query for more reliable results
        customers = frappe.db.sql("""
            SELECT 
                name, 
                customer_name, 
                email_id, 
                mobile_no, 
                customer_group,
                territory,
                tax_id,
                customer_type
            FROM `tabCustomer`
            WHERE disabled = 0
            AND (
                customer_name LIKE %(search_pattern)s
                OR name LIKE %(search_pattern)s
                OR email_id LIKE %(search_pattern)s
                OR mobile_no LIKE %(search_pattern)s
                OR tax_id LIKE %(search_pattern)s
            )
            ORDER BY customer_name ASC
            LIMIT %(limit)s
        """, {
            'search_pattern': search_pattern,
            'limit': int(limit)
        }, as_dict=True)
        
        return customers
        
    except Exception as e:
        frappe.log_error(f"Customer search error: {str(e)}")
        return []

@frappe.whitelist(allow_guest=True)
def get_customer_details(customer_name):
    """Get detailed customer information"""
    
    if not customer_name:
        return None
    
    try:
        customer = frappe.get_doc('Customer', customer_name)
        
        # Return only necessary fields for security
        return {
            'name': customer.name,
            'customer_name': customer.customer_name,
            'email_id': customer.email_id,
            'mobile_no': customer.mobile_no,
            'customer_group': customer.customer_group,
            'territory': customer.territory,
            'tax_id': customer.tax_id,
            'customer_type': customer.customer_type,
            'default_currency': customer.default_currency,
            'credit_limit': customer.credit_limit if hasattr(customer, 'credit_limit') else 0
        }
        
    except Exception as e:
        frappe.log_error(f"Get customer details error: {str(e)}")
        return None

@frappe.whitelist(allow_guest=True)
def validate_customer_access(customer_name):
    """Validate if current user can access this customer"""
    
    if not customer_name:
        return False
    
    try:
        # Check if customer exists and is active
        customer = frappe.get_value('Customer', customer_name, 
                                  ['name', 'disabled'], as_dict=True)
        
        if not customer or customer.disabled:
            return False
        
        # Additional access control logic here if needed
        # For example, check if customer belongs to current user's territory
        
        return True
        
    except Exception:
        return False

@frappe.whitelist(allow_guest=True)
def get_all_customers(limit=100):
    """Get all active customers for debugging"""
    try:
        customers = frappe.get_list(
            'Customer',
            filters={'disabled': 0},
            fields=['name', 'customer_name', 'email_id', 'mobile_no', 'customer_group'],
            order_by='customer_name asc',
            limit=int(limit)
        )
        return customers
    except Exception as e:
        frappe.log_error(f"Get all customers error: {str(e)}")
        return []
