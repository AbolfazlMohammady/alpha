# Marketplace logistics and accounting foundation

This change adds the first backend foundation for seller-owned listings, shipping quotes, shipment tracking, double-entry accounting, daily settlement batches, and external reconciliation.

## Important integration boundary

The carrier and payout clients are configurable adapters, not a claim that a live Tipax, National Post, bank, or PSP contract is already connected. The repository does not contain verified production API credentials or a confirmed carrier/payout contract. Do not enable live order taking until the request/response schemas, authentication, commercial terms, and test-environment results have been confirmed with each provider. The manual/test payment simulator is now blocked outside Django DEBUG mode. Production checkout cannot accept payments until a real gateway and verified callback are integrated. Automatic payout additionally requires explicit `PAYOUT_AMOUNT_MULTIPLIER`, `PAYOUT_API_CURRENCY`, and provider-specific response paths for transfer reference, final status, actual amount, and currency, after verifying the store's toman/rial convention; the adapter intentionally refuses to guess these settings.

All monetary amounts use the repository's integer IRT convention. Keep one unit convention end-to-end (the storefront currently labels amounts as toman); never use floats for money.

## Core flow

1. Admin creates and approves a Vendor; bank details must be verified before settlement approval.
2. A seller can either list an existing central-catalog product or submit a new product with its category, primary image, description, price, stock and shipping package. A new-product submission creates a marketplace-only catalog product and active seller listing only after an admin explicitly approves it; it cannot fall back to the platform's legacy price when no seller listing is active or in stock. Existing listings and commercial changes enter pending review.
3. Each listing can hold its own inventory, retail price, wholesale quantity tiers, sale unit (for example, a piece or a box of 12), physical items per sellable unit, parcel weight/dimensions, and custom-printing capability. Prices, stock and wholesale thresholds are measured in sellable units; shipping weight and dimensions are per sellable unit. Wholesale unit prices must not increase at higher quantity tiers.
4. A seller can either request a supported carrier quote/booking or record a seller-arranged shipment with a carrier name and tracking number. Seller-paid shipping fees collected at checkout are reclassified from shipping liability to that seller's payable only after delivery and are included in the next settlement. Platform-paid carrier costs remain separate and require an actual-cost reconciliation. Recipient-paid/cash-on-delivery shipping is not yet connected to the ledger; all such batches are held from settlement until that payment flow is implemented. The product page and 3D designer let the buyer choose an active seller; custom designs use the selected seller retail price as their base price plus the existing print-layer charges.
4. At checkout, the authenticated buyer selects an address. The server obtains one short-lived quote per seller (one combined parcel per seller order) from the chosen carrier using the seller's configured pickup postal code and the saved destination address. Combined dimensions are an estimate; the seller enters final packed dimensions before booking. The quote is bound to the buyer, cart line, listing, quantity, price, and address fingerprint; it expires after 15 minutes if the provider does not return a shorter validity.
5. The quote amount becomes part of the order total. Once payment succeeds, each order line retains the exact vendor listing and the system creates one VendorOrder per seller only if every line has an explicit seller. Mixed legacy/seller carts are rejected before checkout; split them into separate orders until platform-owned fulfilment is implemented.
6. Seller accepts, prepares, and marks the seller order ready to ship. Seller requests a final packed-parcel quote, books a shipment, and hands the package to the carrier or carrier pickup service. Booking timeouts are treated as ambiguous; check the carrier portal before retrying.
7. Carrier tracking is polled every 30 minutes when Celery Beat and workers are running. Unknown provider statuses are not guessed as delivered. Staff can apply a verified manual status as a fallback only by entering a traceable delivery-evidence reference; the reference, note, staff user ID and timestamp are retained in the shipment audit payload. The read-only shipment admin page provides this action without allowing direct edits to shipment records.
8. Delivery starts the vendor-specific settlement hold period. The daily task creates a batch for delivered seller orders; a centrally-paid shipment is not eligible until its actual carrier cost is recorded.
9. Admin reviews and approves a batch only after the system revalidates every order, shipment, hold period, shipping charge and ledger total. The same checks run again immediately before payout. If a contracted payout API is configured, the system submits the transfer with an idempotency key. An API acknowledgement is not considered proof of payment; the batch becomes paid only after a terminal success status and an exact match between the provider-reported actual amount and the approved amount. Missing or mismatched amounts leave the batch locked for reconciliation.
10. The ledger records vendor payouts and central carrier costs. Gateway-to-bank settlement and processing fees are recorded separately; carrier invoice payments reduce accrued carrier liabilities against the platform bank account. Quote-vs-final-cost and external-vs-internal mismatches are retained for review.

## Where to configure carrier tokens

In this Docker deployment, add provider settings to the private file `config/.env` on the server. The Compose services for Django and Celery load that file through `env_file`; do not put tokens in Python files, templates, screenshots, or Git commits. Keep the real `.env` out of version control.

Example shape only (replace values with the carrier's official API documentation; do not copy placeholder URLs):

```dotenv
TIPAX_API_BASE_URL=
TIPAX_API_TOKEN=
TIPAX_QUOTE_PATH=
TIPAX_QUOTE_AMOUNT_PATH=
TIPAX_QUOTE_CURRENCY_PATH=
TIPAX_AMOUNT_DIVISOR=
TIPAX_SHIPMENT_PATH=
TIPAX_TRACKING_PATH=

POST_API_BASE_URL=
POST_API_TOKEN=
POST_QUOTE_PATH=
POST_QUOTE_AMOUNT_PATH=
POST_QUOTE_CURRENCY_PATH=
POST_AMOUNT_DIVISOR=
POST_SHIPMENT_PATH=
POST_TRACKING_PATH=
```

After editing the file, recreate the services so Docker passes the new environment to the running containers:

```bash
docker compose up -d --force-recreate django celery celery_default celery-beat
```

Open **Control Center → حسابداری مارکت‌پلیس → تنظیمات حمل** to view which required settings are present. The page intentionally displays only configured/not-configured indicators; it never reveals token values. A green/complete configuration indicator does not prove the carrier integration works: the endpoint paths, authentication scheme, request body, currency and response fields must match the provider's official API and be tested in its sandbox first. Do not enter a carrier token into the seller's pickup profile; that profile is only for the seller's origin address and postal code.

## Carrier environment variables

Configure separately for each provider. The adapter uses TIPAX and POST prefixes:

- TIPAX_API_BASE_URL, TIPAX_API_TOKEN, TIPAX_QUOTE_PATH, TIPAX_SHIPMENT_PATH, TIPAX_TRACKING_PATH
- POST_API_BASE_URL, POST_API_TOKEN, POST_QUOTE_PATH, POST_SHIPMENT_PATH, POST_TRACKING_PATH
- Optional auth settings: TIPAX_API_AUTH_HEADER, TIPAX_API_AUTH_SCHEME, POST_API_AUTH_HEADER, POST_API_AUTH_SCHEME (default header/scheme: Authorization: Bearer ...)
- Required for shipping quotes: PREFIX_QUOTE_AMOUNT_PATH and PREFIX_QUOTE_CURRENCY_PATH. Configure PREFIX_AMOUNT_DIVISOR and the currency mapping only after confirming the provider's documented currency; missing or unsupported currencies are rejected. Because the ledger stores toman (`IRT`), the adapter accepts only divisor `1` for toman-denominated responses and divisor `10` for rial-denominated responses; other ratios fail closed. Other response mappings are optional only when the corresponding feature is not used: PREFIX_QUOTE_REFERENCE_PATH, PREFIX_QUOTE_EXPIRES_PATH, PREFIX_SHIPMENT_TRACKING_PATH, PREFIX_SHIPMENT_ID_PATH, PREFIX_SHIPMENT_LABEL_PATH, PREFIX_SHIPMENT_COST_PATH, PREFIX_SHIPMENT_CURRENCY_PATH, PREFIX_TRACKING_STATUS_PATH, PREFIX_TRACKING_COST_PATH, PREFIX_TRACKING_CURRENCY_PATH (replace PREFIX with TIPAX or POST).
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
- PAYOUT_AMOUNT_MULTIPLIER and PAYOUT_API_CURRENCY (use only `IRT` with multiplier `1`, or `IRR` with multiplier `10`, after verifying the bank contract)

The seller submits bank details from the dashboard; the full IBAN is never returned to the seller UI, and any bank-detail change revokes prior verification. The payload includes an idempotency key, amount, currency, verified IBAN and account name. This generic contract must be mapped and tested against the chosen Iranian bank/PSP payout API. Network timeouts leave a batch in a reconciliation state; do not retry blindly.

## Celery

The app registers:
- Daily settlement-batch preparation runs at 23:00 Asia/Tehran by default (`CELERY_TIMEZONE` can override the business timezone). It creates batches for admin review; it does not independently authorize a payout.
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
- GET /marketplace/api/admin/accounting/journal-entries/ — latest posted/reversed journal entries with debit/credit lines for staff review
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


## Seller onboarding and temporary portal navigation

- The public home page links to `/marketplace/vendor/apply/`. A prospective seller can submit contact details, business details, seller type (retail/wholesale/both), Iranian national ID, and address details before a site account exists.
- National ID checksum, Iranian phone format, email, and postal code are validated server-side. Applications do not change a user's role and do not grant access automatically.
- Staff review applications in Django admin under **Vendor applications**. For an anonymous applicant, create the account using the submitted phone and email, link that user to the application, and then set the account role to `store_manager`. The admin validates that the linked account's phone and email match the application.
- On first seller dashboard access, an approved application is copied into the vendor profile (store name and seller type). Legacy pending vendor profiles are activated only when the staff-assigned `store_manager` role is present. Suspended and rejected profiles are not automatically reactivated.
- Retail-only vendors cannot create or edit wholesale price tiers through either the UI or API. The seller-type migration preserves vendors that already have wholesale-enabled listings or tiers.
- Operational seller links live in the seller's Control Center shell and point to real dashboard sections. The public home page links to the actual seller-offer marketplace; it no longer displays temporary operational shortcut cards. Staff accounting links lead to the live accounting operations page.
- Release checks: `python manage.py check`, `python manage.py makemigrations --check --dry-run`, and `python manage.py test apps.marketplace.test_release_checks`. Run migrations before starting the updated application. The current external carrier adapters remain unconfigured until provider documentation, credentials, and sandbox access are supplied.


## Operational UI and seller marketplace discovery

- Seller access stays in the existing Control Center shell and uses the existing black/gold tokens from `config/static/css/control-center.css`; the seller page uses native accessible selects rather than a second custom dropdown framework.
- `/marketplace/vendor/dashboard/` includes seller-owned products, orders and shipping, bank settlement details, settlement history, sales over the last 30 days, sold units, and the top five products by sold units/reconciled allocated revenue.
- `/marketplace/store/` is the public seller-offer directory. It lists only active listings from active, enabled vendors, shows each seller's own price and wholesale terms, and links to the product page where the buyer selects the seller offer.
- Control Center links for accounting, trial balance, gateway settlement, carrier invoices, reconciliation, and seller settlement queue now lead to the operational accounting page at `/marketplace/portal/accounting-overview/`. The page reads the existing ledger/report APIs and submits the existing idempotent accounting operations; it is not a second ledger.
- Wholesale minimum quantity is counted in sellable units. For example, a listing whose sale unit is `جین` and whose `units_per_order` is 12 can have a wholesale minimum of one sellable unit, meaning one dozen physical pieces. Supported sale-unit labels and pack counts are selected from controlled options and validated by the API; arbitrary free-text units and pack sizes are rejected for new listings.
- Shipping-provider readiness is visible to staff on the accounting operations page. Secrets remain in environment configuration, not in HTML or ordinary database fields. In this Docker project, add provider variables to `config/.env` (which is injected into Django and Celery), keep the file out of Git, and restart the Django and Celery services after changing it. A configured token alone is insufficient: base URL, endpoint paths, quote amount/currency response paths, and the verified currency divisor must match the provider's official contract.

- A blank-variable template is provided at `config/marketplace.env.example`. Copy only the required variables into the existing `config/.env`; do not rename the environment file referenced by Docker Compose and do not commit the real file. The accounting screen reports which required values are present without displaying secret values. Restart Django and Celery after edits. Do not configure real booking or tracking paths from guesses: the adapter is modular, but each provider still needs its official API documentation, credentials and sandbox validation.
- This UI does not claim a live carrier or payout contract exists. Provider credentials, endpoint schemas, sandbox results, and banking/payout contracts still require verification before production payments or automated carrier booking are enabled.
