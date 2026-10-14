-- ============================================
-- demo_data.sql
-- Optional sample stock for trying CityPharma out.
-- Import AFTER schema.sql. All names, suppliers and contact details are
-- fictional. Dates are relative to today, so the expiry, low-stock and
-- FEFO examples keep working whenever the file is loaded.
-- ============================================

INSERT INTO suppliers (supplier_id, name, contact_person, email, phone, address) VALUES
(1, 'Riverside Pharma Wholesale', 'Priya Shah',   'orders@riverside-pharma.example', '020 7946 0101', '12 Wharf Road, London'),
(2, 'Kingsway Medical Supplies',  'Tom Bennett',  'sales@kingsway-medical.example',  '020 7946 0202', '48 Kingsway, London'),
(3, 'Northfield Generics',        'Aisha Rahman', 'trade@northfield-generics.example','0161 496 0303', '3 Mill Lane, Manchester');

INSERT INTO medicines (medicine_id, name, type, strength, dosage_form, low_stock_threshold, selling_price, description) VALUES
(1, 'Amoxicillin',    'Antibiotic',        '500 mg',  'Capsule', 50,  3.20, 'Penicillin-type antibiotic'),
(2, 'Paracetamol',    'Analgesic',         '500 mg',  'Tablet',  100, 1.00, 'Pain relief and fever'),
(3, 'Ibuprofen',      'Anti-inflammatory', '200 mg',  'Tablet',  80,  1.50, 'NSAID pain relief'),
(4, 'Metformin',      'Antidiabetic',      '500 mg',  'Tablet',  60,  2.40, 'Type 2 diabetes'),
(5, 'Clotrimazole',   'Antifungal',        '1%',      'Cream',   20,  3.95, 'Topical antifungal'),
(6, 'Salbutamol',     'Bronchodilator',    '100 mcg', 'Inhaler', 15,  4.50, 'Reliever inhaler'),
(7, 'Omeprazole',     'Gastrointestinal',  '20 mg',   'Capsule', 40,  2.10, 'Reduces stomach acid'),
(8, 'Cetirizine',     'Antihistamine',     '10 mg',   'Tablet',  40,  1.80, 'Allergy relief'),
(9, 'Hydrocortisone', 'Corticosteroid',    '1%',      'Cream',   15,  3.50, 'Topical steroid');

INSERT INTO medicine_suppliers (medicine_id, supplier_id, unit_cost) VALUES
(1, 1, 1.40), (2, 1, 0.35), (3, 2, 0.55), (4, 3, 0.90), (5, 2, 1.60),
(6, 1, 2.10), (7, 3, 0.80), (8, 2, 0.60), (9, 3, 1.45);

-- Several batches per medicine with different expiry dates, so FEFO
-- (First Expiry, First Out) has something to choose between.
-- Amoxicillin AMX-2401 is already expired and should never be dispensed.
-- Paracetamol PCM-2405 expires within 30 days (shows in the expiring report).
-- Salbutamol is below its low-stock threshold; Hydrocortisone has no stock.
INSERT INTO batches (medicine_id, batch_number, expiry_date, quantity, date_received) VALUES
(1, 'AMX-2401', DATE_SUB(CURDATE(), INTERVAL 10 DAY),  30,  DATE_SUB(CURDATE(), INTERVAL 300 DAY)),
(1, 'AMX-2507', DATE_ADD(CURDATE(), INTERVAL 45 DAY),  60,  DATE_SUB(CURDATE(), INTERVAL 120 DAY)),
(1, 'AMX-2602', DATE_ADD(CURDATE(), INTERVAL 220 DAY), 120, DATE_SUB(CURDATE(), INTERVAL 20 DAY)),
(2, 'PCM-2405', DATE_ADD(CURDATE(), INTERVAL 20 DAY),  80,  DATE_SUB(CURDATE(), INTERVAL 200 DAY)),
(2, 'PCM-2601', DATE_ADD(CURDATE(), INTERVAL 400 DAY), 400, DATE_SUB(CURDATE(), INTERVAL 15 DAY)),
(3, 'IBU-2511', DATE_ADD(CURDATE(), INTERVAL 160 DAY), 240, DATE_SUB(CURDATE(), INTERVAL 60 DAY)),
(4, 'MET-2509', DATE_ADD(CURDATE(), INTERVAL 90 DAY),  70,  DATE_SUB(CURDATE(), INTERVAL 90 DAY)),
(4, 'MET-2604', DATE_ADD(CURDATE(), INTERVAL 330 DAY), 150, DATE_SUB(CURDATE(), INTERVAL 10 DAY)),
(5, 'CLT-2512', DATE_ADD(CURDATE(), INTERVAL 270 DAY), 44,  DATE_SUB(CURDATE(), INTERVAL 30 DAY)),
(6, 'SAL-2510', DATE_ADD(CURDATE(), INTERVAL 180 DAY), 9,   DATE_SUB(CURDATE(), INTERVAL 45 DAY)),
(7, 'OME-2508', DATE_ADD(CURDATE(), INTERVAL 60 DAY),  35,  DATE_SUB(CURDATE(), INTERVAL 100 DAY)),
(7, 'OME-2603', DATE_ADD(CURDATE(), INTERVAL 300 DAY), 90,  DATE_SUB(CURDATE(), INTERVAL 25 DAY)),
(8, 'CET-2602', DATE_ADD(CURDATE(), INTERVAL 365 DAY), 160, DATE_SUB(CURDATE(), INTERVAL 5 DAY));
