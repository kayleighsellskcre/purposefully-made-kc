# Purposefully Made KC Operations System

Your complete back-office control center for orders, inventory, vendors, production, and growth.

## Quick Start

1. **Run migration** (if you haven't already):
   ```
   python migrate_operations.py
   ```

2. **Start the app** — new tables are created automatically:
   ```
   python app.py
   ```

3. **Admin Dashboard** → `http://localhost:5000/admin/`

---

## 1. Orders & Revenue Tracking (Control Center)

**Location:** `/admin/orders` and `/admin/orders/<id>`

- **Master Order Log** — Every order with filters (status, Retail/Wholesale/Event)
- **Order Detail** — Due date, order type, cost of goods, profit, refund tracking
- **Per-Item:** Print type (DTF, screen print, vinyl), design file name
- **Columns:** Order #, Customer, Contact, Items, Size, Color, Qty, Design, Print type, Due date, Paid, Fulfilled, Pickup/Shipped, Profit

---

## 2. Inventory Management

**Location:** `/admin/operations/inventory`

- **Apparel Inventory** — Brand, color, size, quantity, cost per unit, reorder threshold
- **Transfer Inventory** — DTF/Screen print: design name, size, quantity, cost per sheet, vendor
- **Blanks + Supplies** — Heat tape, Teflon, packaging, poly mailers, thank you cards, ink, blades, etc.
- Add/update inline; transfer inventory links to vendors

---

## 3. Vendor & Supplier Database

**Location:** `/admin/operations/vendors`

- Vendor name, contact, website, website login
- Lead times, MOQ, pricing tier, quality rating (1–5)
- Backup vendor reference
- Add/Edit forms

---

## 4. Production Workflow (5-Stage Kanban)

**Location:** `/admin/operations/workflow`

1. **Order Received** — New/paid orders
2. **Waiting on Supplies** — Awaiting blanks or transfers
3. **Ready to Press** — Supplies in, ready to heat
4. **Pressed** — Print applied
5. **Packaged & Ready** — Ready for pickup/ship

Move orders between stages via dropdown. Orders auto-update status when moved.

---

## 5. Design Organization

**Location:** `/admin/design-gallery`

- **Folder categories:** Custom Orders, Evergreen, School, Holiday, Sports, Funny, Luxury Basics
- **SKU** — Assign SKU to each design
- Upload form includes folder + SKU; gallery displays both

---

## 6. Financial Buckets

**Location:** `/admin/operations/financial`

- **Categories:** Revenue, COGS, Advertising, Equipment, Misc/Software
- Add manual entries; view total revenue & profit
- Recent entries table

---

## 7. Customer & Marketing Tracker

**Location:** `/admin/operations/customers`

- **Repeat customers** — Users with 2+ orders
- **School/Team/Event collections** — Collections with order counts and share links

---

## 8. Packaging & Fulfillment SOP

**Location:** `/admin/operations/packaging-sop`

- Printable checklist:
  - Quality check seams
  - Check sizing
  - Press alignment check
  - Remove dust
  - Fold uniformly
  - Insert thank you card
  - Apply sticker/freebie
  - Label correctly

---

## 9. Growth Dashboard

**Location:** `/admin/operations/growth`

- **Weekly metrics:** Units sold, revenue, website traffic, events booked, wholesale inquiries, social reach
- **Auto-Sync:** Click "Auto-Sync Now" to pull units sold, revenue, events, wholesale from your orders & collections
- **Weekly automation:** Run `flask sync_growth` or `sync_growth_weekly.bat` via Windows Task Scheduler (e.g. every Monday)
- Traffic & social reach need manual entry or external integration (Google Analytics, etc.)

---

## Navigation

All operations pages have a consistent nav bar linking to:
- Dashboard | Orders | Workflow | Inventory | Vendors | Financial | Growth | Customers | Packaging SOP

---

## Database Models Added

- `Vendor` — Supplier database
- `ApparelInventory` — Blanks by brand/color/size
- `TransferInventory` — DTF/screen print transfers
- `Supply` — Heat tape, packaging, etc.
- `GrowthMetric` — Weekly metrics
- `FinancialEntry` — Expense/revenue entries

**Order/OrderItem extended with:**
- `production_stage`, `order_type`, `due_date`, `cost_of_goods`, `profit`, `is_refunded`, `refund_notes`
- `print_type`, `design_file_name` (per item)

**Design extended with:**
- `folder`, `sku`
