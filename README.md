# Retail POS Billing Software

A Flask + SQLite POS and Billing Software for textile/retail businesses. It provides separate Admin and Billing portals, product/staff/supplier management, returns, transaction ledger, reports, invoice printing, stock control, and a dedicated mobile-admin web layout.

## Features
- Admin portal: product CRUD, staff management, supplier CRUD, returns, ledger, reports and transaction management.
- Billing portal: product search, cart, stock validation, customer name, discount, tax, payment method, invoice generation and print.
- Mobile Admin UI: open `/admin/mobile` after logging in as an admin. This switches the complete admin portal into a mobile application-style layout; every admin navigation page uses the mobile layout.
- SQLite database with automatic first-run initialization and sample products.
- Password hashing and role-based access control.
- Safe POST-based destructive actions and return-quantity validation.

## Technology Stack
- Frontend: HTML5, CSS3, JavaScript
- Backend: Python Flask
- Database: SQLite
- Authentication: Flask session + Werkzeug password hashing

## Local Setup
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
pip install -r requirements.txt
python app.py
```
Then open `http://127.0.0.1:5000`.

## Test Credentials
- Admin: `admin` / `admin123`
- Staff: `staff` / `staff123`

Change these credentials before production use. Set `SECRET_KEY` to a strong random value in the environment.

## Important URLs
- Login: `/login`
- Admin portal: `/admin`
- Mobile Admin UI: `/admin/mobile`
- Billing portal: `/billing`
- Ledger: `/admin/transactions`
- Reports: `/admin/reports`

## Deployment
The application is configured to use `HOST`, `PORT`, `SECRET_KEY`, and `FLASK_DEBUG` environment variables. For production, use a production WSGI server such as Gunicorn or Waitress and a persistent database/storage setup.
