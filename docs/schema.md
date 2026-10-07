# Schema contract v1

Generated from A03 ORM metadata. UTC DateTime is stored without tzinfo; JSON Decimal values are strings.
NULL means nullable. PK/FK/unique constraints below are the frozen cross-module baseline.

## business_clocks

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| id | INTEGER | False |  |
| business_anchor | DATETIME | False |  |
| server_anchor | DATETIME | False |  |
| paused | BOOLEAN | False |  |

Constraints:

- PrimaryKeyConstraint pk_business_clocks: id

## products

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| id | INTEGER | False |  |
| sku | VARCHAR(32) | False |  |
| name | VARCHAR(120) | False |  |
| base_unit | VARCHAR(16) | False |  |
| pack_size | INTEGER | False |  |
| active | BOOLEAN | False |  |

Constraints:

- CHECK ck_products_pack_size: `pack_size > 0`
- PrimaryKeyConstraint pk_products: id
- UniqueConstraint uq_products_sku: sku

## stores

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| id | INTEGER | False |  |
| code | VARCHAR(32) | False |  |
| name | VARCHAR(120) | False |  |
| timezone | VARCHAR(40) | False |  |
| cutoff | TIME | False |  |
| active | BOOLEAN | False |  |
| calculation_version | INTEGER | False |  |

Constraints:

- PrimaryKeyConstraint pk_stores: id
- UniqueConstraint uq_stores_code: code

## users

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| id | INTEGER | False |  |
| username | VARCHAR(80) | False |  |
| password_hash | VARCHAR(255) | False |  |
| role | VARCHAR(20) | False |  |
| active | BOOLEAN | False |  |

Constraints:

- CHECK ck_users_role: `role IN ('manager','operator','admin')`
- PrimaryKeyConstraint pk_users: id
- UniqueConstraint uq_users_username: username

## audit_events

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| id | INTEGER | False |  |
| store_id | INTEGER | True | stores.id |
| actor_id | INTEGER | True | users.id |
| action | VARCHAR(80) | False |  |
| entity | VARCHAR(120) | False |  |
| old | JSON | True |  |
| new | JSON | True |  |
| server_time | DATETIME | False |  |
| business_time | DATETIME | False |  |
| request_id | VARCHAR(80) | False |  |

Constraints:

- ForeignKeyConstraint fk_audit_events_actor_id_users: actor_id
- ForeignKeyConstraint fk_audit_events_store_id_stores: store_id
- PrimaryKeyConstraint pk_audit_events: id

## delivery_cycles

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| id | INTEGER | False |  |
| store_id | INTEGER | False | stores.id |
| baseline_at | DATETIME | False |  |
| cutoff_at | DATETIME | False |  |
| arrival_at | DATETIME | False |  |
| cancelled | BOOLEAN | False |  |

Constraints:

- ForeignKeyConstraint fk_delivery_cycles_store_id_stores: store_id
- PrimaryKeyConstraint pk_delivery_cycles: id
- UniqueConstraint uq_delivery_cycles_store_id: store_id, baseline_at, arrival_at

## inventories

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| physical_qty | INTEGER | False |  |
| unsellable_qty | INTEGER | False |  |
| book_physical_qty | INTEGER | False |  |
| book_unsellable_qty | INTEGER | False |  |
| reconciliation_required | BOOLEAN | False |  |
| counted_at | DATETIME | False |  |
| updated_at | DATETIME | False |  |
| store_id | INTEGER | False | stores.id |
| product_id | INTEGER | False | products.id |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- CHECK ck_inventories_count_quantities: `physical_qty >= 0 AND unsellable_qty >= 0 AND unsellable_qty <= physical_qty`
- ForeignKeyConstraint fk_inventories_product_id_products: product_id
- ForeignKeyConstraint fk_inventories_store_id_stores: store_id
- PrimaryKeyConstraint pk_inventories: id
- UniqueConstraint uq_inventories_store_id: store_id, product_id

## inventory_counts

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| cutoff_at | DATETIME | False |  |
| baseline_physical_qty | INTEGER | False |  |
| baseline_unsellable_qty | INTEGER | False |  |
| store_id | INTEGER | False | stores.id |
| product_id | INTEGER | False | products.id |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_inventory_counts_product_id_products: product_id
- ForeignKeyConstraint fk_inventory_counts_store_id_stores: store_id
- PrimaryKeyConstraint pk_inventory_counts: id
- UniqueConstraint uq_inventory_counts_store_id: store_id, product_id, cutoff_at

## inventory_movements

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| physical_delta | INTEGER | False |  |
| unsellable_delta | INTEGER | False |  |
| source_type | VARCHAR(40) | False |  |
| source_id | VARCHAR(100) | False |  |
| reason | VARCHAR(500) | False |  |
| actor_id | INTEGER | False | users.id |
| occurred_at | DATETIME | False |  |
| applied_at | DATETIME | False |  |
| resulting_version | INTEGER | False |  |
| store_id | INTEGER | False | stores.id |
| product_id | INTEGER | False | products.id |
| id | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_inventory_movements_actor_id_users: actor_id
- ForeignKeyConstraint fk_inventory_movements_product_id_products: product_id
- ForeignKeyConstraint fk_inventory_movements_store_id_stores: store_id
- PrimaryKeyConstraint pk_inventory_movements: id
- UniqueConstraint uq_inventory_movements_store_id: store_id, source_type, source_id, product_id

## inventory_reconciliations

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| source_type | VARCHAR(40) | False |  |
| source_id | VARCHAR(100) | False |  |
| reason | VARCHAR(500) | False |  |
| status | VARCHAR(24) | False |  |
| created_at | DATETIME | False |  |
| resolved_at | DATETIME | True |  |
| resolved_by | INTEGER | True | users.id |
| resolution | JSON | True |  |
| store_id | INTEGER | False | stores.id |
| product_id | INTEGER | False | products.id |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_inventory_reconciliations_product_id_products: product_id
- ForeignKeyConstraint fk_inventory_reconciliations_resolved_by_users: resolved_by
- ForeignKeyConstraint fk_inventory_reconciliations_store_id_stores: store_id
- PrimaryKeyConstraint pk_inventory_reconciliations: id
- UniqueConstraint uq_inventory_reconciliations_store_id: store_id, product_id, source_type, source_id

## manual_forecast_overrides

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| daily_demand | NUMERIC(16, 3) | False |  |
| reason | VARCHAR(500) | False |  |
| actor_id | INTEGER | False | users.id |
| created_at | DATETIME | False |  |
| valid_until | DATETIME | False |  |
| store_id | INTEGER | False | stores.id |
| product_id | INTEGER | False | products.id |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- CHECK ck_manual_forecast_overrides_demand: `daily_demand >= 0 AND daily_demand <= 1000000`
- ForeignKeyConstraint fk_manual_forecast_overrides_actor_id_users: actor_id
- ForeignKeyConstraint fk_manual_forecast_overrides_product_id_products: product_id
- ForeignKeyConstraint fk_manual_forecast_overrides_store_id_stores: store_id
- PrimaryKeyConstraint pk_manual_forecast_overrides: id

## policy_versions

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| id | INTEGER | False |  |
| store_id | INTEGER | False | stores.id |
| product_id | INTEGER | False | products.id |
| version | INTEGER | False |  |
| effective_at | DATETIME | False |  |
| parameters | JSON | False |  |

Constraints:

- ForeignKeyConstraint fk_policy_versions_product_id_products: product_id
- ForeignKeyConstraint fk_policy_versions_store_id_stores: store_id
- PrimaryKeyConstraint pk_policy_versions: id
- UniqueConstraint uq_policy_versions_store_id: store_id, product_id, version

## sales_import_batches

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| store_id | INTEGER | False | stores.id |
| source_batch_id | VARCHAR(100) | False |  |
| payload_hash | VARCHAR(64) | False |  |
| import_mode | VARCHAR(24) | False |  |
| replaces_batch_id | INTEGER | True | sales_import_batches.id |
| actor_id | INTEGER | False | users.id |
| created_at | DATETIME | False |  |
| snapshot | JSON | False |  |
| id | INTEGER | False |  |

Constraints:

- CHECK ck_sales_import_batches_mode: `import_mode IN ('historical','daily_posting')`
- ForeignKeyConstraint fk_sales_import_batches_actor_id_users: actor_id
- ForeignKeyConstraint fk_sales_import_batches_replaces_batch_id_sales_import_batches: replaces_batch_id
- ForeignKeyConstraint fk_sales_import_batches_store_id_stores: store_id
- PrimaryKeyConstraint pk_sales_import_batches: id
- UniqueConstraint uq_sales_import_batches_store_id: store_id, source_batch_id

## user_acknowledgements

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| id | INTEGER | False |  |
| user_id | INTEGER | False | users.id |
| text_version | VARCHAR(32) | False |  |
| acknowledged_at | DATETIME | False |  |

Constraints:

- ForeignKeyConstraint fk_user_acknowledgements_user_id_users: user_id
- PrimaryKeyConstraint pk_user_acknowledgements: id
- UniqueConstraint uq_user_acknowledgements_user_id: user_id, text_version

## user_stores

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| user_id | INTEGER | False | users.id |
| store_id | INTEGER | False | stores.id |

Constraints:

- ForeignKeyConstraint fk_user_stores_store_id_stores: store_id
- ForeignKeyConstraint fk_user_stores_user_id_users: user_id
- PrimaryKeyConstraint pk_user_stores: user_id, store_id

## inventory_count_revisions

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| count_id | INTEGER | False | inventory_counts.id |
| revision | INTEGER | False |  |
| physical_qty | INTEGER | False |  |
| unsellable_qty | INTEGER | False |  |
| physical_delta | INTEGER | False |  |
| unsellable_delta | INTEGER | False |  |
| expected_version | INTEGER | False |  |
| reason | VARCHAR(500) | False |  |
| actor_id | INTEGER | False | users.id |
| submitted_at | DATETIME | False |  |
| movement_id | INTEGER | False | inventory_movements.id |
| id | INTEGER | False |  |

Constraints:

- CHECK ck_inventory_count_revisions_quantities: `physical_qty >= 0 AND unsellable_qty >= 0 AND unsellable_qty <= physical_qty`
- ForeignKeyConstraint fk_inventory_count_revisions_actor_id_users: actor_id
- ForeignKeyConstraint fk_inventory_count_revisions_count_id_inventory_counts: count_id
- ForeignKeyConstraint fk_inventory_count_revisions_movement_id_inventory_movements: movement_id
- PrimaryKeyConstraint pk_inventory_count_revisions: id
- UniqueConstraint uq_inventory_count_revisions_count_id: count_id, revision
- UniqueConstraint uq_inventory_count_revisions_movement_id: movement_id

## operational_tasks

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| store_id | INTEGER | False | stores.id |
| owner_role | VARCHAR(24) | False |  |
| source_type | VARCHAR(40) | False |  |
| source_id | VARCHAR(100) | False |  |
| task_type | VARCHAR(40) | False |  |
| policy_version_id | INTEGER | False | policy_versions.id |
| due_at | DATETIME | False |  |
| created_at | DATETIME | False |  |
| completed_by | INTEGER | True | users.id |
| completed_at | DATETIME | True |  |
| result | JSON | True |  |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_operational_tasks_completed_by_users: completed_by
- ForeignKeyConstraint fk_operational_tasks_policy_version_id_policy_versions: policy_version_id
- ForeignKeyConstraint fk_operational_tasks_store_id_stores: store_id
- PrimaryKeyConstraint pk_operational_tasks: id
- UniqueConstraint uq_operational_tasks_store_id: store_id, source_type, source_id, task_type

## replenishment_runs

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| store_id | INTEGER | False | stores.id |
| cycle_id | INTEGER | False | delivery_cycles.id |
| actor_id | INTEGER | False | users.id |
| store_version | INTEGER | False |  |
| baseline_at | DATETIME | False |  |
| actual_generated_at | DATETIME | False |  |
| data_through_at | DATETIME | False |  |
| risk_evaluated_at | DATETIME | False |  |
| model_version | VARCHAR(40) | False |  |
| warning_version | VARCHAR(16) | False |  |
| calculation_mode | VARCHAR(32) | False |  |
| snapshot | JSON | False |  |
| id | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_replenishment_runs_actor_id_users: actor_id
- ForeignKeyConstraint fk_replenishment_runs_cycle_id_delivery_cycles: cycle_id
- ForeignKeyConstraint fk_replenishment_runs_store_id_stores: store_id
- PrimaryKeyConstraint pk_replenishment_runs: id

## sales_daily

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| business_date | DATE | False |  |
| interval_start | DATETIME | False |  |
| interval_end | DATETIME | False |  |
| sold_qty | INTEGER | False |  |
| was_stockout | BOOLEAN | False |  |
| is_open | BOOLEAN | False |  |
| batch_id | INTEGER | False | sales_import_batches.id |
| import_mode | VARCHAR(24) | False |  |
| applied_at | DATETIME | True |  |
| movement_id | INTEGER | True | inventory_movements.id |
| event_note | VARCHAR(500) | True |  |
| store_id | INTEGER | False | stores.id |
| product_id | INTEGER | False | products.id |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- CHECK ck_sales_daily_sold_qty: `sold_qty >= 0`
- ForeignKeyConstraint fk_sales_daily_batch_id_sales_import_batches: batch_id
- ForeignKeyConstraint fk_sales_daily_movement_id_inventory_movements: movement_id
- ForeignKeyConstraint fk_sales_daily_product_id_products: product_id
- ForeignKeyConstraint fk_sales_daily_store_id_stores: store_id
- PrimaryKeyConstraint pk_sales_daily: id
- UniqueConstraint uq_sales_daily_movement_id: movement_id
- UniqueConstraint uq_sales_daily_store_id: store_id, product_id, business_date

## store_products

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| id | INTEGER | False |  |
| store_id | INTEGER | False | stores.id |
| product_id | INTEGER | False | products.id |
| policy_version_id | INTEGER | False | policy_versions.id |
| lead_days | INTEGER | False |  |
| safety_stock | INTEGER | False |  |
| capacity | INTEGER | False |  |
| active | BOOLEAN | False |  |

Constraints:

- CHECK ck_store_products_policy_quantities: `lead_days >= 1 AND safety_stock >= 0 AND capacity >= 0`
- ForeignKeyConstraint fk_store_products_policy_version_id_policy_versions: policy_version_id
- ForeignKeyConstraint fk_store_products_product_id_products: product_id
- ForeignKeyConstraint fk_store_products_store_id_stores: store_id
- PrimaryKeyConstraint pk_store_products: id
- UniqueConstraint uq_store_products_store_id: store_id, product_id

## count_submission_keys

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| store_id | INTEGER | False | stores.id |
| user_id | INTEGER | False | users.id |
| request_key | VARCHAR(100) | False |  |
| payload_hash | VARCHAR(64) | False |  |
| revision_id | INTEGER | False | inventory_count_revisions.id |
| id | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_count_submission_keys_revision_id_inventory_count_revisions: revision_id
- ForeignKeyConstraint fk_count_submission_keys_store_id_stores: store_id
- ForeignKeyConstraint fk_count_submission_keys_user_id_users: user_id
- PrimaryKeyConstraint pk_count_submission_keys: id
- UniqueConstraint uq_count_submission_keys_store_id: store_id, user_id, request_key

## order_drafts

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| store_id | INTEGER | False | stores.id |
| user_id | INTEGER | False | users.id |
| cycle_id | INTEGER | False | delivery_cycles.id |
| run_id | INTEGER | False | replenishment_runs.id |
| status | VARCHAR(24) | False |  |
| created_at | DATETIME | False |  |
| updated_at | DATETIME | False |  |
| parent_order_id | INTEGER | True | orders.id |
| additional_order_reason | VARCHAR(500) | True |  |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_draft_parent_order: parent_order_id
- ForeignKeyConstraint fk_order_drafts_cycle_id_delivery_cycles: cycle_id
- ForeignKeyConstraint fk_order_drafts_run_id_replenishment_runs: run_id
- ForeignKeyConstraint fk_order_drafts_store_id_stores: store_id
- ForeignKeyConstraint fk_order_drafts_user_id_users: user_id
- PrimaryKeyConstraint pk_order_drafts: id

## run_items

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| run_id | INTEGER | False | replenishment_runs.id |
| product_id | INTEGER | False | products.id |
| mode | VARCHAR(32) | False |  |
| mu | NUMERIC(24, 12) | True |  |
| target_stock | NUMERIC(24, 12) | True |  |
| raw_qty | NUMERIC(24, 12) | True |  |
| suggested_qty | INTEGER | True |  |
| input_snapshot | JSON | False |  |
| output_snapshot | JSON | False |  |
| warnings | JSON | False |  |
| id | INTEGER | False |  |

Constraints:

- CHECK ck_run_items_suggested_qty: `suggested_qty IS NULL OR (suggested_qty >= 0 AND suggested_qty <= 1000000)`
- ForeignKeyConstraint fk_run_items_product_id_products: product_id
- ForeignKeyConstraint fk_run_items_run_id_replenishment_runs: run_id
- PrimaryKeyConstraint pk_run_items: id
- UniqueConstraint uq_run_items_run_id: run_id, product_id

## draft_items

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| draft_id | INTEGER | False | order_drafts.id |
| product_id | INTEGER | False | products.id |
| run_item_id | INTEGER | False | run_items.id |
| final_qty | INTEGER | False |  |
| reason_code | VARCHAR(40) | True |  |
| reason | VARCHAR(500) | True |  |
| special_need | JSON | True |  |
| manual_forecast_acknowledged | BOOLEAN | False |  |
| id | INTEGER | False |  |

Constraints:

- CHECK ck_draft_items_final_qty: `final_qty >= 0 AND final_qty <= 1000000`
- ForeignKeyConstraint fk_draft_items_draft_id_order_drafts: draft_id
- ForeignKeyConstraint fk_draft_items_product_id_products: product_id
- ForeignKeyConstraint fk_draft_items_run_item_id_run_items: run_item_id
- PrimaryKeyConstraint pk_draft_items: id
- UniqueConstraint uq_draft_items_draft_id: draft_id, product_id

## orders

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| store_id | INTEGER | False | stores.id |
| user_id | INTEGER | False | users.id |
| draft_id | INTEGER | False | order_drafts.id |
| cycle_id | INTEGER | False | delivery_cycles.id |
| number | VARCHAR(64) | False |  |
| submitted_at | DATETIME | False |  |
| status | VARCHAR(32) | False |  |
| fixture_only | BOOLEAN | False |  |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_orders_cycle_id_delivery_cycles: cycle_id
- ForeignKeyConstraint fk_orders_draft_id_order_drafts: draft_id
- ForeignKeyConstraint fk_orders_store_id_stores: store_id
- ForeignKeyConstraint fk_orders_user_id_users: user_id
- PrimaryKeyConstraint pk_orders: id
- UniqueConstraint uq_orders_draft_id: draft_id
- UniqueConstraint uq_orders_number: number

## order_confirmations

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| order_id | INTEGER | True | orders.id |
| draft_id | INTEGER | False | order_drafts.id |
| user_id | INTEGER | False | users.id |
| store_id | INTEGER | False | stores.id |
| draft_version | INTEGER | False |  |
| store_version | INTEGER | False |  |
| token_hash | VARCHAR(64) | False |  |
| payload_hash | VARCHAR(64) | False |  |
| text_version | VARCHAR(32) | False |  |
| warning_version | VARCHAR(16) | False |  |
| created_at | DATETIME | False |  |
| expires_at | DATETIME | False |  |
| risk_evaluated_at | DATETIME | False |  |
| acknowledged_at | DATETIME | True |  |
| order_acknowledged | BOOLEAN | False |  |
| exception_acknowledgements | JSON | False |  |
| snapshot | JSON | False |  |
| id | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_order_confirmations_draft_id_order_drafts: draft_id
- ForeignKeyConstraint fk_order_confirmations_order_id_orders: order_id
- ForeignKeyConstraint fk_order_confirmations_store_id_stores: store_id
- ForeignKeyConstraint fk_order_confirmations_user_id_users: user_id
- PrimaryKeyConstraint pk_order_confirmations: id
- UniqueConstraint uq_order_confirmations_order_id: order_id
- UniqueConstraint uq_order_confirmations_token_hash: token_hash

## order_items

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| order_id | INTEGER | False | orders.id |
| product_id | INTEGER | False | products.id |
| original_qty | INTEGER | False |  |
| product_snapshot | JSON | False |  |
| committed_qty | INTEGER | False |  |
| cancelled_qty | INTEGER | False |  |
| status | VARCHAR(32) | False |  |
| eta | DATETIME | True |  |
| deduction_expires_at | DATETIME | False |  |
| commitment_disputed | BOOLEAN | False |  |
| disputed_qty | INTEGER | False |  |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- CHECK ck_order_items_fulfillment_qty: `committed_qty >= 0 AND cancelled_qty >= 0 AND disputed_qty >= 0`
- CHECK ck_order_items_original_qty: `original_qty > 0 AND original_qty <= 1000000`
- ForeignKeyConstraint fk_order_items_order_id_orders: order_id
- ForeignKeyConstraint fk_order_items_product_id_products: product_id
- PrimaryKeyConstraint pk_order_items: id
- UniqueConstraint uq_order_items_order_id: order_id, product_id

## shipments

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| order_id | INTEGER | False | orders.id |
| request_key | VARCHAR(100) | False |  |
| payload_hash | VARCHAR(64) | False |  |
| actor_id | INTEGER | False | users.id |
| shipped_at | DATETIME | False |  |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_shipments_actor_id_users: actor_id
- ForeignKeyConstraint fk_shipments_order_id_orders: order_id
- PrimaryKeyConstraint pk_shipments: id
- UniqueConstraint uq_shipments_order_id: order_id, request_key

## submission_keys

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| user_id | INTEGER | False | users.id |
| store_id | INTEGER | False | stores.id |
| key | VARCHAR(100) | False |  |
| payload_hash | VARCHAR(64) | False |  |
| order_id | INTEGER | False | orders.id |
| id | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_submission_keys_order_id_orders: order_id
- ForeignKeyConstraint fk_submission_keys_store_id_stores: store_id
- ForeignKeyConstraint fk_submission_keys_user_id_users: user_id
- PrimaryKeyConstraint pk_submission_keys: id
- UniqueConstraint uq_submission_keys_user_id: user_id, store_id, key

## fulfillment_events

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| order_item_id | INTEGER | False | order_items.id |
| actor_id | INTEGER | False | users.id |
| source_key | VARCHAR(100) | False |  |
| event_type | VARCHAR(40) | False |  |
| occurred_at | DATETIME | False |  |
| snapshot | JSON | False |  |
| id | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_fulfillment_events_actor_id_users: actor_id
- ForeignKeyConstraint fk_fulfillment_events_order_item_id_order_items: order_item_id
- PrimaryKeyConstraint pk_fulfillment_events: id
- UniqueConstraint uq_fulfillment_events_source_key: source_key

## receipts

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| store_id | INTEGER | False | stores.id |
| user_id | INTEGER | False | users.id |
| shipment_id | INTEGER | False | shipments.id |
| request_key | VARCHAR(100) | False |  |
| payload_hash | VARCHAR(64) | False |  |
| received_at | DATETIME | False |  |
| id | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_receipts_shipment_id_shipments: shipment_id
- ForeignKeyConstraint fk_receipts_store_id_stores: store_id
- ForeignKeyConstraint fk_receipts_user_id_users: user_id
- PrimaryKeyConstraint pk_receipts: id
- UniqueConstraint uq_receipts_store_id: store_id, user_id, shipment_id, request_key

## shipment_items

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| shipment_id | INTEGER | False | shipments.id |
| order_item_id | INTEGER | False | order_items.id |
| kind | VARCHAR(24) | False |  |
| authorization_id | INTEGER | True | replacement_authorizations.id |
| shipped_qty | INTEGER | False |  |
| checked_qty | INTEGER | False |  |
| eta | DATETIME | False |  |
| eta_disputed | BOOLEAN | False |  |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- CHECK ck_shipment_items_kind_authorization: `(kind = 'original' AND authorization_id IS NULL) OR (kind = 'replacement' AND authorization_id IS NOT NULL)`
- CHECK ck_shipment_items_quantities: `shipped_qty > 0 AND checked_qty >= 0 AND checked_qty <= shipped_qty`
- ForeignKeyConstraint fk_shipment_authorization: authorization_id
- ForeignKeyConstraint fk_shipment_items_order_item_id_order_items: order_item_id
- ForeignKeyConstraint fk_shipment_items_shipment_id_shipments: shipment_id
- PrimaryKeyConstraint pk_shipment_items: id
- UniqueConstraint uq_shipment_items_shipment_id: shipment_id, order_item_id, kind

## supply_change_requests

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| order_item_id | INTEGER | False | order_items.id |
| old_conditions | JSON | False |  |
| new_conditions | JSON | False |  |
| reason | VARCHAR(500) | False |  |
| created_by | INTEGER | False | users.id |
| created_at | DATETIME | False |  |
| response_due_at | DATETIME | False |  |
| status | VARCHAR(24) | False |  |
| responded_by | INTEGER | True | users.id |
| responded_at | DATETIME | True |  |
| response | JSON | True |  |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- ForeignKeyConstraint fk_supply_change_requests_created_by_users: created_by
- ForeignKeyConstraint fk_supply_change_requests_order_item_id_order_items: order_item_id
- ForeignKeyConstraint fk_supply_change_requests_responded_by_users: responded_by
- PrimaryKeyConstraint pk_supply_change_requests: id

## receipt_items

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| receipt_id | INTEGER | False | receipts.id |
| shipment_item_id | INTEGER | False | shipment_items.id |
| checked_qty | INTEGER | False |  |
| sellable_qty | INTEGER | False |  |
| damaged_qty | INTEGER | False |  |
| short_qty | INTEGER | False |  |
| inventory_source_id | VARCHAR(100) | False |  |
| note | VARCHAR(500) | True |  |
| id | INTEGER | False |  |

Constraints:

- CHECK ck_receipt_items_quantities: `checked_qty > 0 AND sellable_qty >= 0 AND damaged_qty >= 0 AND short_qty >= 0 AND checked_qty = sellable_qty + damaged_qty + short_qty`
- ForeignKeyConstraint fk_receipt_items_receipt_id_receipts: receipt_id
- ForeignKeyConstraint fk_receipt_items_shipment_item_id_shipment_items: shipment_item_id
- PrimaryKeyConstraint pk_receipt_items: id
- UniqueConstraint uq_receipt_items_inventory_source_id: inventory_source_id
- UniqueConstraint uq_receipt_items_receipt_id: receipt_id, shipment_item_id

## receipt_variances

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| receipt_item_id | INTEGER | False | receipt_items.id |
| parent_variance_id | INTEGER | True | receipt_variances.id |
| kind | VARCHAR(24) | False |  |
| quantity | INTEGER | False |  |
| closed_qty | INTEGER | False |  |
| status | VARCHAR(24) | False |  |
| created_at | DATETIME | False |  |
| resolved_at | DATETIME | True |  |
| resolution | JSON | True |  |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- CHECK ck_receipt_variances_quantities: `quantity > 0 AND closed_qty >= 0 AND closed_qty <= quantity`
- ForeignKeyConstraint fk_receipt_variances_parent_variance_id_receipt_variances: parent_variance_id
- ForeignKeyConstraint fk_receipt_variances_receipt_item_id_receipt_items: receipt_item_id
- PrimaryKeyConstraint pk_receipt_variances: id
- UniqueConstraint uq_receipt_variances_receipt_item_id: receipt_item_id, kind

## replacement_authorizations

| Column | SQL type | Nullable | Reference |
| --- | --- | --- | --- |
| variance_id | INTEGER | False | receipt_variances.id |
| request_key | VARCHAR(100) | False |  |
| payload_hash | VARCHAR(64) | False |  |
| authorized_qty | INTEGER | False |  |
| used_qty | INTEGER | False |  |
| closed_qty | INTEGER | False |  |
| eta | DATETIME | False |  |
| actor_id | INTEGER | False | users.id |
| created_at | DATETIME | False |  |
| id | INTEGER | False |  |
| version | INTEGER | False |  |

Constraints:

- CHECK ck_replacement_authorizations_quantities: `authorized_qty > 0 AND used_qty >= 0 AND closed_qty >= 0 AND used_qty + closed_qty <= authorized_qty`
- ForeignKeyConstraint fk_replacement_authorizations_actor_id_users: actor_id
- ForeignKeyConstraint fk_replacement_authorizations_variance_id_receipt_variances: variance_id
- PrimaryKeyConstraint pk_replacement_authorizations: id
- UniqueConstraint uq_replacement_authorizations_variance_id: variance_id, request_key

