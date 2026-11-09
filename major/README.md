# SmartEcommerceAnalytics

Flask e-commerce app with admin/vendor/customer roles and ML (KMeans segmentation + recommendations).

## Run locally
    pip install -r requirements.txt
    python app.py          # open http://localhost:5000

## Demo logins (change after deploying!)
- Admin:    admin / admin123
- Vendor:   vendor1 / vendor123   (15 starter products are seeded automatically)
- Customer: register at /register

## Deploy (Render.com, free)
1. Push this folder to a GitHub repo.
2. Render -> New -> Blueprint -> select the repo (render.yaml is included).
3. Service name `smartecommerceanalytics` gives https://smartecommerceanalytics.onrender.com
4. Free-tier disk is temporary. For permanent data add a Render Disk and set DATABASE_PATH=/var/data/smart_commerce.db
