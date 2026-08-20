---
name: project_onebid_hubspot_subscription_sync
description: Three-stage HubSpot-to-OneBid subscription sync pipeline (webhook ingestion, cron backfill, CDC-driven subscriber setup) spanning two NestJS services
type: project
---

The onebid backend indexes a three-stage pipeline that syncs HubSpot subscription/contact/
company data into OneBid and turns it into searchable "subscriber settings". Spans two repos:
`onebid/backend/backend_nodejs_global_tnlm` (global_tnlm) and
`onebid/backend/backend_nodejs_data_sync_onebid` (data_sync_onebid). See
[[project_pipeline_sort_architecture]] for other onebid domain knowledge and
[[project_indexed_target_varies]] for why the index may point elsewhere in future sessions
(verify these paths still exist before relying on them).

**Stage 1 — Real-time webhook ingestion (global_tnlm)**
`POST /webhooks/hubspot` (`src/webhooks/webhooks.controller.ts`) guarded by
`HubspotWebhookGuard` (`src/webhooks/guards/hubspot-webhook.guard.ts`) which HMAC-SHA256
validates `x-hubspot-signature-v3` against a canonical string (method+uri+rawBody+timestamp)
using `HUBSPOT_CLIENT_SECRET`, and rejects timestamps >5 min old (replay protection).
`WebhooksService.webhook()` (`src/webhooks/webhooks.service.ts`) routes each event by
`subscriptionType` prefix to one of 3 Kafka topics via `HubspotWebhookProducerService`
(`src/webhooks/producer/hubspot-webhook.producer.service.ts`, hardcoded topic consts
`hubspot-contact-events` / `hubspot-company-events` / `hubspot-company-association-events`).
`HubspotController` (`src/hubspot/hubspot.controller.ts`, `@EventPattern`) consumes those
topics -> `HubspotService` -> `UpsertHubspotContactUsecase` / `UpsertHubspotCompanyUsecase` /
`UpsertHubspotCompanyAssociationUsecase` (`src/hubspot/usecases/*`) -> mappers
(`HubspotContactMapper`, `HubspotCompanyMapper`, `HubspotCompanyAssociationMapper`) -> upsert
into `HUBSPOT_CONTACT` / `HUBSPOT_COMPANY` / `HUBSPOT_COMPANY_CONTACT_ASSOCIATION` tables
(schema `STAGING_SERVICES_TNLM`).

**Stage 2 — Scheduled on-demand backfill/provisioning (data_sync_onebid)**
`HubspotSubscriptionSchedulerService` (`src/hubspot-sync/hubspot-subscription-scheduler.service.ts`)
only runs when `APP_TYPE=hubspot-scheduler`; registers a `CronJob` via NestJS `SchedulerRegistry`
on `HUBSPOT_SUBSCRIPTION_CRON_SCHEDULE` (default `*/10 * * * *`). `scheduledSync()` guards against
overlap (`isSyncInProgress`), then `syncChangedSubscriptions()`: pages through
`HubspotClientService.searchSubscriptions()` (custom HubSpot object type `2-58668729`, filtered
`hs_lastmodifieddate GTE` a lookback window and `bc_product IN ['Bid Ocean Lite/Pro/Core']`) ->
for each subscription fetches `getContactAssociations`/`getCompanyAssociations` -> upserts into
`HUBSPOT_SUBSCRIPTION` / `HUBSPOT_SUBSCRIPTION_CONTACT` / `HUBSPOT_SUBSCRIPTION_COMPANY` tables
(schema `STAGING_SERVICES`) via `HubspotSubscriptionDbService.upsertSubscriptionWithAssociations`
(one DB transaction). Then `provisionMissingEntities` checks if each associated contact/company
already exists locally (`contactExists`/`companyExists`); if missing, fetches the full record
(`getContactById`/`getCompanyById`), fabricates synthetic `*.creation` + `*.propertyChange` events
via `buildProvisioningEvents` (`src/hubspot-sync/helpers/hubspot-event.builder.ts`) mimicking real
webhook payloads, and publishes them through `HubspotContactProducerService`/
`HubspotCompanyProducerService` (topics configurable via `HUBSPOT_CONTACT_TOPIC`/
`HUBSPOT_COMPANY_TOPIC` env vars, defaulting to `hubspot-contact`/`hubspot-company` — must be set
to match global_tnlm's `hubspot-contact-events`/`hubspot-company-events` in env config for the two
services to share a topic and land on the same `HubspotController` consumer).
Rate limiting: `HubspotClientService.getContactById/getCompanyById` throw `HubspotRateLimitError`
(`src/hubspot-sync/helpers/hubspot-rate-limit.error.ts`) on HTTP 429, parsed via `asRateLimitError`
from the `Retry-After` header; the scheduler catches it, sets a per-tick `rateLimited` flag to defer
remaining fetches, and calls `Helper.sleep(retryAfterSeconds*1000)` before continuing. A
`fetchCap` (`HUBSPOT_ONDEMAND_FETCH_CAP`, default 200) bounds fetches per tick; per-tick `seen`
sets dedupe contact/company IDs across subscriptions.

**Stage 3 — CDC-driven subscriber setup (global_tnlm)**
The staging tables written in stages 1-2 are watched by an external CDC pipeline (AWS DMS-style)
publishing to Kafka topic `hubspot-cdc-subscription` (constants in
`src/setup-member-subscription/constants/setup-member-subscription.constants.ts`, APP_TYPE
`consumer-setup-member-subscription`). `SetupMemberSubscriptionConsumerService`
(`src/setup-member-subscription/consumer/setup-member-subscription.consumer.service.ts`) consumes
CDC messages shaped like `{data: {HS_COMPANY_ID, HS_CONTACT_ID, HS_SUBSCRIPTION_ID}, metadata:
{schema-name, table-name, operation, ...}}` (`CdcMessage` interface), queries a DB view
`STAGING_SERVICES_TNLM.VW_SUBSCRIPTIONS` with `WHERE HS_COMPANY_ID = :1 OR HS_CONTACT_ID = :2 OR
HS_SUBSCRIPTION_ID = :3`, groups rows by `BC_USER_ID`, then per user: maps `BC_PRODUCT` to a tier
(Bid Ocean Core/Lite/Pro -> `SUBSCRIPTION_TIERS`), resolves state/trade/tradeGroup/goodAndService/
requestType IDs via Elasticsearch lookups, upserts a `SUBSCRIBER_SETTING` row
(`SubscriberSettingRepository`), indexes a `MemberSubscriptionDocument` into the
`memberSubscriptionIndex` ES index, and — only for brand-new subscribers — creates a Save Search
Project (`CreateSaveSearchProjectUsecase`), generates default folders for PRO/CORE tiers
(`FolderService.generateDefaultFolders`), and publishes to the `first-savesearch-notifier` Kafka
topic via `WebhookProducerService`. Visibility is confirmed with bounded polling
(`waitForSaveSearchVisible`/`waitForMemberSubscriptionVisible`, 100 attempts x 500ms) against
`_search` (not `GET /_doc`) before firing downstream events, because ES `refresh: 'wait_for'` is
best-effort under load. Consumer resilience: `attachConsumerHealthListeners` +
`ConsumerCircuitBreakerService` pause/resume the Kafka consumer based on a readiness profile.

**Why this matters:** the `MemberSubscriptionElasticRepository` / `memberSubscriptionIndex`
populated by Stage 3 is what gates project-pipeline matching and login subscription checks
elsewhere in global_tnlm (e.g. `pre-alert-project-pipeline/workers/daily-worker.service.ts`,
`auth/services/subscription-validation.service.ts`) — so "subscription sync" ultimately feeds
access control and search-matching, not just CRM mirroring.

**A separate, unrelated outbound HubSpot integration exists in global_tnlm:**
`HubspotContactApiClient` (`src/hubspot/clients/hubspot-contact-api.client.ts`) is a raw
Axios/HttpService client (base URL `HUBSPOT_API_BASE_URL`, default `https://api.hubapi.com`,
token `HUBSPOT_ACCESS_TOKEN` as `Authorization: Bearer`). Its only method,
`updateContactProperties(email, properties)`, does a **PATCH**
`/crm/v3/objects/contacts/{encodedEmail}?idProperty=email` — not a GET/fetch. It's called
solely by `HqForgotPasswordUseCase.execute()`
(`src/auth/strategies/hq/usecases/hq-forgot-password.usecase.ts`) to write a
`temporary_password` property onto the contact, which triggers HubSpot's password-recovery
email workflow. Don't confuse this with `HubspotClientService.getContactById`
(data_sync_onebid) — that one is the actual GET-a-contact path, uses the official
`@hubspot/api-client` SDK (`client.crm.contacts.basicApi.getById(id, CONTACT_PROPERTIES)`,
properties = `jobtitle, firstname, lastname, email, bc_user_id, hq_userid`), and is only ever
called from `HubspotSubscriptionSchedulerService`'s on-demand provisioning path, not from any
HTTP-facing endpoint. As of this check, the index has no HubSpot "search contact by email" or
"batch read contacts" implementation — only get-by-id (SDK) and update-by-email (raw PATCH).
