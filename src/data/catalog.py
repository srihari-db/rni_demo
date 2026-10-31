"""Fictional master data for the RNI operations simulator.

Every customer, product, manufacturer and price below is invented for demonstration purposes. Product names are
fictional brand names attached to generic therapeutic categories; none of them describe a real product.
"""
from __future__ import annotations

# demand_profile is the *synthetic generating process* label (ground truth for the demo). The forecasting
# pipeline never reads it; it classifies demand from the observed history instead.
PRODUCTS = [
    # sku,      product_name,                                   category,                    unit_cost, shelf, storage,       critical, pack, profile,       uom
    ("SKU-1001", "Product A – Hyperimmune Globulin 1,500 IU", "Immune Globulin",             900.0,  730, "REFRIGERATED", True,  5,  "EMERGENCY",    "dose"),
    ("SKU-1002", "Corvanta IVIG 10% 10 g",                     "Immune Globulin",            1180.0,  900, "REFRIGERATED", False, 1,  "REGULAR",      "unit"),
    ("SKU-1003", "Imuvex SCIG 20% 4 g",                        "Immune Globulin",             640.0,  730, "REFRIGERATED", False, 5,  "REGULAR",      "unit"),
    ("SKU-1004", "Plasmorin Albumin 25% 50 mL",                "Albumin & Plasma Proteins",   165.0, 1095, "ROOM_TEMP",    False, 10, "REGULAR",      "vial"),
    ("SKU-1005", "Albucel Albumin 5% 250 mL",                  "Albumin & Plasma Proteins",   120.0, 1095, "ROOM_TEMP",    False, 10, "REGULAR",      "vial"),
    ("SKU-1006", "Crotivane Antivenom (lyophilized)",          "Antivenom & Antitoxin",      3200.0, 1095, "REFRIGERATED", True,  1,  "EMERGENCY",    "vial"),
    ("SKU-1007", "Scorpidex Antivenom",                        "Antivenom & Antitoxin",      3900.0, 1095, "ROOM_TEMP",    True,  1,  "EMERGENCY",    "vial"),
    ("SKU-1008", "Botulitox Heptavalent Antitoxin",            "Antivenom & Antitoxin",      5600.0,  730, "FROZEN",       True,  1,  "EMERGENCY",    "vial"),
    ("SKU-1009", "Reversa-4F Prothrombin Complex 1,000 IU",    "Anticoagulant Reversal",     1650.0, 1095, "ROOM_TEMP",    True,  1,  "INTERMITTENT", "vial"),
    ("SKU-1010", "Xabanex Factor Xa Reversal 200 mg",          "Anticoagulant Reversal",     3300.0,  730, "REFRIGERATED", True,  1,  "INTERMITTENT", "vial"),
    ("SKU-1011", "Dabinor Thrombin-Inhibitor Reversal 2.5 g",  "Anticoagulant Reversal",     2050.0, 1095, "REFRIGERATED", True,  1,  "INTERMITTENT", "vial"),
    ("SKU-1012", "FluShield Quadrivalent 0.5 mL",              "Vaccines",                     22.0,  365, "REFRIGERATED", False, 10, "SEASONAL",     "dose"),
    ("SKU-1013", "RSVantis Adult RSV Vaccine",                 "Vaccines",                    285.0,  540, "REFRIGERATED", False, 10, "SEASONAL",     "dose"),
    ("SKU-1014", "PneumoGuard-20 Conjugate Vaccine",           "Vaccines",                    245.0,  730, "REFRIGERATED", False, 10, "SEASONAL",     "dose"),
    ("SKU-1015", "HepaGuard B Vaccine",                        "Vaccines",                     78.0, 1095, "REFRIGERATED", False, 10, "REGULAR",      "dose"),
    ("SKU-1016", "Nirsevia Infant RSV mAb 100 mg",             "Monoclonal Antibodies",       495.0,  730, "REFRIGERATED", False, 5,  "SEASONAL",     "dose"),
    ("SKU-1017", "Oncomab 400 mg",                             "Monoclonal Antibodies",      2400.0,  540, "REFRIGERATED", False, 1,  "REGULAR",      "vial"),
    ("SKU-1018", "Denoxa 120 mg",                              "Monoclonal Antibodies",      1950.0,  730, "REFRIGERATED", False, 1,  "REGULAR",      "vial"),
    ("SKU-1019", "Trastavia Biosimilar 150 mg",                "Oncology Biologics",         1280.0,  540, "REFRIGERATED", False, 1,  "REGULAR",      "vial"),
    ("SKU-1020", "Pegfilra 6 mg Prefilled Syringe",            "Oncology Biologics",         3850.0,  540, "REFRIGERATED", False, 1,  "REGULAR",      "syringe"),
    ("SKU-1021", "Hemofix Factor VIII 2,000 IU",               "Hemostatic Factors",         1450.0,  730, "REFRIGERATED", False, 1,  "REGULAR",      "vial"),
    ("SKU-1022", "Fibrinex Fibrinogen Concentrate 1 g",        "Hemostatic Factors",         1100.0, 1095, "ROOM_TEMP",    False, 1,  "INTERMITTENT", "vial"),
    ("SKU-1023", "Digoxa Immune Fab 40 mg",                    "Emergency Antidotes",        2900.0, 1095, "REFRIGERATED", True,  1,  "EMERGENCY",    "vial"),
    ("SKU-1024", "Cobalanex Cyanide Antidote Kit 5 g",         "Emergency Antidotes",        1400.0,  900, "ROOM_TEMP",    True,  1,  "EMERGENCY",    "kit"),
    ("SKU-1025", "Glycolex Toxic Alcohol Antidote 1.5 g",      "Emergency Antidotes",         980.0, 1095, "ROOM_TEMP",    True,  1,  "EMERGENCY",    "vial"),
    ("SKU-1026", "Rabivax Rabies Immune Globulin 300 IU",      "Immune Globulin",            1150.0, 1095, "REFRIGERATED", True,  1,  "INTERMITTENT", "vial"),
    ("SKU-1027", "Tetanix Tetanus Immune Globulin 250 U",      "Immune Globulin",             260.0, 1095, "REFRIGERATED", False, 5,  "INTERMITTENT", "syringe"),
    ("SKU-1028", "Hepatix Hepatitis B Immune Globulin 1 mL",   "Immune Globulin",             690.0, 1095, "REFRIGERATED", False, 1,  "INTERMITTENT", "vial"),
    ("SKU-1029", "Rhoguard Rho(D) Immune Globulin 300 mcg",    "Immune Globulin",             115.0, 1095, "REFRIGERATED", False, 5,  "REGULAR",      "syringe"),
    ("SKU-1030", "Alteplex Thrombolytic 100 mg",               "Thrombolytics",              9800.0,  730, "ROOM_TEMP",    True,  1,  "INTERMITTENT", "vial"),
]

PRODUCT_COLUMNS = ["sku", "product_name", "product_category", "unit_cost", "shelf_life_days", "storage_type",
                   "critical_stock_flag", "pack_size", "demand_profile", "unit_of_measure"]

MANUFACTURERS = ["Aurelis Biologics (fictional)", "Northwind Plasma (fictional)", "Cobalt Ridge Pharma (fictional)",
                 "Helix Harbor Therapeutics (fictional)"]

# customer_id, name, city/state, customer_type, region, size_factor, ordering_bias, p_excess, return_propensity
CUSTOMERS = [
    ("CUST-001", "Hospital A",                              "Phoenix, AZ",      "Hospital",               "Southwest", 1.0, 1.35, 0.10, 0.55),
    ("CUST-002", "Lakeshore Children's Hospital",           "Chicago, IL",      "Pediatric Hospital",     "Midwest",   1.1, 1.10, 0.05, 0.40),
    ("CUST-003", "Harbor Point Infusion Center",            "San Diego, CA",    "Infusion Center",        "West",      1.3, 0.75, 0.02, 0.15),
    ("CUST-004", "Mesa Verde Community Hospital",           "Durango, CO",      "Critical Access Hospital", "Southwest", 0.5, 1.00, 0.04, 0.20),
    ("CUST-005", "Summit Hematology & Oncology Associates", "Denver, CO",       "Specialty Clinic",       "West",      0.8, 1.45, 0.12, 0.85),
    ("CUST-006", "Bayou Regional Medical Center",           "Baton Rouge, LA",  "Hospital",               "Southeast", 1.0, 1.05, 0.04, 0.30),
    ("CUST-007", "Pinecrest Health – North Campus",         "Charlotte, NC",    "Health System Hospital", "Southeast", 1.4, 1.40, 0.09, 0.60),
    ("CUST-008", "Riverbend Ambulatory Surgery Center",     "Columbus, OH",     "Ambulatory Surgery Center", "Midwest", 0.6, 1.00, 0.03, 0.20),
    ("CUST-009", "Granite State Medical Center",            "Manchester, NH",   "Hospital",               "Northeast", 0.9, 1.00, 0.03, 0.25),
    ("CUST-010", "Hudson Valley Infusion Partners",         "Albany, NY",       "Infusion Center",        "Northeast", 1.1, 1.15, 0.05, 0.35),
    ("CUST-011", "Sonoran Desert Emergency Hospital",       "Tucson, AZ",       "Emergency Hospital",     "Southwest", 0.8, 1.10, 0.05, 0.30),
    ("CUST-012", "Cascade Valley Medical Center",           "Spokane, WA",      "Hospital",               "West",      0.9, 0.80, 0.02, 0.15),
    ("CUST-013", "Prairie Health Regional",                 "Sioux Falls, SD",  "Hospital",               "Midwest",   0.8, 1.00, 0.03, 0.25),
    ("CUST-014", "Gulf Coast Cancer Institute",             "Tampa, FL",        "Specialty Clinic",       "Southeast", 1.2, 1.50, 0.11, 0.70),
    ("CUST-015", "Liberty Bell University Hospital",        "Philadelphia, PA", "Academic Medical Center", "Northeast", 1.6, 1.10, 0.04, 0.35),
]

CUSTOMER_COLUMNS = ["customer_id", "customer_name", "location", "customer_type", "region", "size_factor",
                    "ordering_bias", "p_excess", "return_propensity"]

# Which product categories each customer type stocks in its RNI devices.
ASSORTMENT_BY_TYPE = {
    "Hospital": ["Immune Globulin", "Albumin & Plasma Proteins", "Antivenom & Antitoxin", "Anticoagulant Reversal",
                 "Vaccines", "Emergency Antidotes", "Thrombolytics", "Hemostatic Factors"],
    "Pediatric Hospital": ["Immune Globulin", "Albumin & Plasma Proteins", "Vaccines", "Monoclonal Antibodies",
                           "Emergency Antidotes", "Anticoagulant Reversal"],
    "Infusion Center": ["Immune Globulin", "Albumin & Plasma Proteins", "Monoclonal Antibodies", "Oncology Biologics"],
    "Critical Access Hospital": ["Antivenom & Antitoxin", "Emergency Antidotes", "Anticoagulant Reversal",
                                 "Immune Globulin", "Thrombolytics", "Vaccines"],
    "Specialty Clinic": ["Monoclonal Antibodies", "Oncology Biologics", "Hemostatic Factors", "Immune Globulin"],
    "Health System Hospital": ["Immune Globulin", "Albumin & Plasma Proteins", "Anticoagulant Reversal", "Vaccines",
                               "Emergency Antidotes", "Thrombolytics", "Monoclonal Antibodies", "Antivenom & Antitoxin"],
    "Ambulatory Surgery Center": ["Albumin & Plasma Proteins", "Anticoagulant Reversal", "Emergency Antidotes",
                                  "Hemostatic Factors"],
    "Emergency Hospital": ["Antivenom & Antitoxin", "Emergency Antidotes", "Anticoagulant Reversal", "Thrombolytics",
                           "Immune Globulin"],
    "Academic Medical Center": ["Immune Globulin", "Albumin & Plasma Proteins", "Monoclonal Antibodies",
                                "Oncology Biologics", "Anticoagulant Reversal", "Emergency Antidotes", "Vaccines",
                                "Hemostatic Factors", "Thrombolytics"],
}

# Lead time (days) from SAP shipment to RNI device receipt, by region.
LEAD_TIME_BY_REGION = {"West": 2, "Southwest": 3, "Midwest": 2, "Southeast": 3, "Northeast": 2}

# Simulated cold-chain return logistics cost per return shipment (USD, synthetic).
RETURN_SHIPPING_BASE = {"REFRIGERATED": (140.0, 230.0), "FROZEN": (260.0, 390.0), "ROOM_TEMP": (35.0, 65.0)}
RETURN_HANDLING_PER_UNIT = (2.0, 6.0)
# Simulated receiving / QA inspection / requalification cost per return (USD, synthetic).
RETURN_PROCESSING_COST = {"REFRIGERATED": (180.0, 420.0), "FROZEN": (240.0, 520.0), "ROOM_TEMP": (60.0, 140.0)}

DEVICE_TYPES = {"REFRIGERATED": "RNI SmartFridge", "FROZEN": "RNI SmartFreezer", "ROOM_TEMP": "RNI SmartCabinet"}
