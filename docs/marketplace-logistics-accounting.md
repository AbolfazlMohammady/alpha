# Marketplace logistics and accounting foundation

This change adds the first backend foundation for seller-owned listings, shipping quotes, shipment tracking, double-entry accounting, daily settlement batches, and external reconciliation.

## Important integration boundary

The carrier and payout clients are configurable adapters, not a claim that a live Tipax, National Post, bank, or PSP contract is already connected. The repository does not contain verified production API credentials or a confirmed carrier/payout contract. Do not enable live order taking until the request/response schemas, authentication, commercial terms, and test-environment results have been confirmed with each provider. The manual/test payment simulator is now blocked outside Django DEBUG mode. Production checkout cannot accept payments until a real gateway and verified callback are integrated. Automatic payout additionally requires explicit `PAYOUT_AMOUNT_MULTIPLIER`, `PAYOUT_API_CURRENCY`, and `PAYOUT_RESPONSE_AMOUNT_PATH` values after verifying the store's toman/rial convention and the bank's actual-amount response field; the adapter intentionally refuses to guess any of these settings.

All monetary amounts use the repository's integer IRT convention. Keep one unit convention end-to-end (the storefront currently labels amounts as toman); never use floats for money.

## Core flow

1. Admin creates and approves a Vendor; bank details must be verified before settlement approval.
2. A seller can either list an existing central-catalog product or submit a new product with its category, primary image, description, price, stock and shipping package. A new-product submission creates a marketplace-only catalog product and active seller listing only after an admin explicitly approves it; it cannot fall back to the platform's legacy price when no seller listing is active or in stock. Existing listings and commercial changes enter pending review.
3. Each listing can hold its own inventory, retail price, wholesale quantity tiers, sale unit (for example, a piece or a box of 12), physical items per sellable unit, parcel weight/dimensions, and custom-printing capability. Prices, stock and wholesale thresholds are measured in sellable units; shipping weight and dimensions are per sellable unit. Wholesale unit prices must not increase at higher quantity tiers.
4. A seller can either request a supported carrier quote/booking or record a seller-arranged shipment with a carrier name and tracking number. Seller-paid shipping fees collected at checkout are reclassified from shipping liability to that seller's payable only after delivery and are included in the next settlement. Platform-paid carrier costs remain separate and require an actual-cost reconciliation. Recipient-paid/cash-on-delivery shipping is not yet connected to the ledger; all such batches are held from settlement until that payment flow is implemented. The product page and 3D designer let the buyer choose an active seller; custom designs use the selected seller retail price as their base price plus the existing print-layer charges.
4. At checkout, the authenticated buyer selects an address. The server obtains one short-lived quote per seller (one combined parcel per seller order) from the chosen carrier using the seller's configured pickup postal code and the saved destination address. Combined dimensions are an estimate; the seller enters final packed dimensions before booking. The quote is bound to the buyer, cart line, listing, quantity, price, and address fingerprint; it expires after 15 minutes if the provider does not return a shorter validity.
5. The quote amount becomes part of the order total. Once payment succeeds, each order line retains the exact vendor listing and the system creates one VendorOrder per seller only if every line has an explicit seller. Mixed legacy/seller carts are rejected before checkout; split them into separate orders until platform-owned fulfilment is implemented.
6. Seller accepts, prepares, and marks the seller order ready to ship. Seller requests a final packed-parcel quote, books a shipment, and hands the package to the carrier or carrier pickup service. Booking timeouts are treated as ambiguous; check the carrier portal before retrying.
7. Carrier tracking is polled every 30 minutes when Celery Beat and workers are running. Unknown provider statuses are not guessed as delivered. Staff can apply a verified manual status as a fallback.
8. Delivery starts the vendor-specific settlement hold period. The daily task creates a batch for delivered seller orders; a centrally-paid shipment is not eligible until its actual carrier cost is recorded.
9. Admin reviews and approves a batch only after the system revalidates every order, shipment, hold period, shipping charge and ledger total. The same checks run again immediately before payout. If a contracted payout API is configured, the system submits the transfer with an idempotency key. An API acknowledgement is not considered proof of payment; the batch becomes paid only after a terminal success status and an exact match between the provider-reported actual amount and the approved amount. Missing or mismatched amounts leave the batch locked for reconciliation.
10. The ledger records vendor payouts and central carrier costs. Gateway-to-bank settlement and processing fees are recorded separately; carrier invoice payments reduce accrued carrier liabilities against the platform bank account. Quote-vs-final-cost and external-vs-internal mismatches are retained for review.

## Carrier environment variables

Configure separately for each provider. The adapter uses TIPAX and POST prefixes:

- TIPAX_API_BASE_URL, TIPAX_API_TOKEN, TIPAX_QUOTE_PATH, TIPAX_SHIPMENT_PATH, TIPAX_TRACKING_PATH
- POST_API_BASE_URL, POST_API_TOKEN, POST_QUOTE_PATH, POST_SHIPMENT_PATH, POST_TRACKING_PATH
- Optional auth settings: TIPAX_API_AUTH_HEADER, TIPAX_API_AUTH_SCHEME, POST_API_AUTH_HEADER, POST_API_AUTH_SCHEME (default header/scheme: Authorization: Bearer ...)
- Required for shipping quotes: PREFIX_QUOTE_AMOUNT_PATH and PREFIX_QUOTE_CURRENCY_PATH. Configure PREFIX_AMOUNT_DIVISOR and the currency mapping only after confirming the provider's documented currency; missing or unsupported currencies are rejected. Other response mappings are optional only when the corresponding feature is not used: PREFIX_QUOTE_REFERENCE_PATH, PREFIX_QUOTE_EXPIRES_PATH, PREFIX_SHIPMENT_TRACKING_PATH, PREFIX_SHIPMENT_ID_PATH, PREFIX_SHIPMENT_LABEL_PATH, PREFIX_SHIPMENT_COST_PATH, PREFIX_SHIPMENT_CURRENCY_PATH, PREFIX_TRACKING_STATUS_PATH, PREFIX_TRACKING_COST_PATH, PREFIX_TRACKING_CURRENCY_PATH (replace PREFIX with TIPAX or POST).
- TIPAX_AMOUNT_DIVISOR and POST_AMOUNT_DIVISOR (use 10 only when the provider explicitly returns rials and the project stores toman; the adapter checks the currency/divisor combination)
- CARRIER_API_TIMEOUT_SECONDS (default 10)

Response paths use dot notation, for example data.price.amount. The request body is a normalized generic payload; if the provider's official API requires a different schema, implement/verify the provider-specific request mapping before enabling that provider. Never commit tokens or customer data to Git.

Seller profile needs a pickup postal code. Every listed parcel product needs its packed weight in grams and packed dimensions in centimetres. Checkout fails closed when required data is missing; it does not invent a shipping price.

## Payout environment variables

The generic payout adapter is disabled unless all of these are configured:

- PAYOUT_API_BASE_URL (HTTPS required)
- PAYOUT_API_TOKEN
- PAYOUT_API_PATH
- Optional PAYOUT_API_TIMEOUT_SECONDS, PAYOUT_API_AUTH_HEADER, PAYOUT_API_AUTH_SCHEME
- PAYOUT_RESPONSE_REFERENCE_PATH, PAYOUT_RESPONSE_STATUS_PATH, PAYOUT_RESPONSE_AMOUNT_PATH, and PAYOUT_RESPONSE_CURRENCY_PATH are all required and must map to the chosen provider's actual response fields. The adapter does not guess generic field names.
- The amount is normalized using PAYOUT_AMOUNT_MULTIPLIER before reconciliation; missing amount, currency, or reference keeps the payout in a non-final reconciliation state.
- PAYOUT_AMOUNT_MULTIPLIER and PAYOUT_API_CURRENCY (set only after verifying whether the payout API expects toman or rials)

The seller submits bank details from the dashboard; the full IBAN is never returned to the seller UI, and any bank-detail change revokes prior verification. The payload includes an idempotency key, amount, currency, verified IBAN and account name. This generic contract must be mapped and tested against the chosen Iranian bank/PSP payout API. Network timeouts leave a batch in a reconciliation state; do not retry blindly.

## Celery

The app registers:
- Daily settlement-batch preparation (86400 seconds). It creates batches for admin review; it does not independently authorize a payout.
- Carrier tracking refresh (1800 seconds).

Both require the project's Celery worker and Beat to be running. Run these after deploying the schema:

    docker compose run --rm django python manage.py migrate
    docker compose run --rm django python manage.py test apps.marketplace

## API overview

Seller dashboard UI is available at /marketplace/vendor/dashboard/. All seller endpoints require login and ownership checks. Admin endpoints require staff access.

- GET /marketplace/api/vendor/dashboard/
- GET /marketplace/api/vendor/orders/
- GET /marketplace/api/vendor/settlements/
- POST /marketplace/api/vendor/profile/shipping/
- GET|POST /marketplace/api/vendor/profile/financial/ — bank details are masked on read and any changed IBAN requires re-verification
- GET|POST /marketplace/api/vendor/products/
- GET /marketplace/api/vendor/catalog-products/?q=text
- GET|POST /marketplace/api/vendor/product-submissions/ — seller-submitted new products, image required, admin approval creates the product and active seller listing
- POST /marketplace/api/vendor/products/<listing_id>/
- POST /marketplace/api/vendor/products/<listing_id>/wholesale/
- PATCH|DELETE /marketplace/api/vendor/wholesale-tiers/<tier_id>/
- POST /marketplace/api/vendor/categories/request/
- POST /marketplace/api/shipping/quote/ — checkout quote (cart_item_id, address_id, provider)
- POST /marketplace/api/vendor/orders/<order_id>/action/ — accept, prepare, ready_to_ship, or allowed cancellation
- POST /marketplace/api/vendor/orders/<order_id>/shipping/quote/
- POST /marketplace/api/vendor/orders/<order_id>/shipping/book/
- POST /marketplace/api/vendor/orders/<order_id>/shipping/<shipment_uuid>/handed-over/
- GET /marketplace/api/admin/settlements/
- POST /marketplace/api/admin/settlements/<batch_id>/approve/
- POST /marketplace/api/admin/orders/<order_uuid>/refund/ (records a full refund only after staff confirms the external refund and exact amount; it does not initiate the bank transfer)
- POST /marketplace/api/admin/settlements/<batch_id>/payout-result/ (successful results require the actual transfer amount)
- GET /marketplace/api/admin/accounting/trial-balance/
- POST /marketplace/api/admin/accounting/reconciliation/
- POST /marketplace/api/admin/accounting/carrier-payment/
- POST /marketplace/api/admin/accounting/gateway-settlement/

The seller-facing dashboard is intentionally a functional first version; styling and product catalog workflows can be refined after end-to-end acceptance testing.

## Accounting safeguards and current scope

- Integer-only amounts; no floats.
- Double-entry journals are balanced before posting.
- Journal idempotency keys are fingerprinted against transaction identity and line amounts, so reusing a key for another transaction or different amounts is rejected.
- Cart and order lines snapshot the seller sale unit and pack size; changing a listing's unit forces stale cart lines to be removed and re-added. Custom-print orders use the selected seller's retail price and pack-size print surcharge on the server, not just in the browser preview.
- Marketplace-only products cannot be bought at a fallback catalogue price when their seller listing is paused, out of stock, or unavailable.
- A confirmed full refund restores the stock deducted at payment exactly once, and is blocked once seller preparation or shipment has started.
- Posted journal entries and lines cannot be edited/deleted; corrections use reversals.
- Seller order financial snapshots and settlement lines are protected.
- Daily settlement batches are idempotent and reserve their eligible orders.
- Carrier final cost is posted against collected shipping funds first; excess becomes shipping expense. If final cost is lower than the collected charge, the remaining shipping liability stays pending review rather than silently becoming platform income.
- Full-order refund reversal is provided only after the payment provider confirms the refund and supplies a reference. Partial refunds and live gateway refunds need provider-specific integration.
- External references and amount differences are retained as reconciliation records.

Before production, add provider-specific integration tests, a real gateway payment/refund adapter, bank statement import/reconciliation, retention controls for shipping PII, and formal accounting/legal review of commission, shipping surplus/shortfall, return windows, and seller payout terms. Failed or ambiguous payouts must be reconciled manually before retry; a retry must never be automatic.
