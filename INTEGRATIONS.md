# INTEGRATIONS.md — the integration landscape & consumer's position

> Why this exists: the "connect every app" problem is a solved market
> (Composio, Nango, Merge, Pipedream, Ampersand). We checked before building
> more hand-rolled connectors, and this file records what we found and what
> we adopted.

## The landscape (verified 2026-10-06)

| Platform      | Model                                                              | Credential custody                   | Our read                                                                                                                                                                                                                           |
| ------------- | ------------------------------------------------------------------ | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Composio**  | 1,000+ connectors, managed OAuth + tool execution for agents       | **Composio-managed** (cloud)         | The action-infra leader — but closed, and its 2025 breach (≈5,001 GitHub OAuth tokens + 5,241 API keys exposed via an intercepted employee Gmail OAuth token) is the exact failure mode local credential custody exists to prevent |
| **Nango**     | open-source OAuth infra, 400+ prebuilt provider configs, self-host | **You own** (your instance, your DB) | The only platform matching our philosophy — open, self-hostable, credentials never leave your box                                                                                                                                  |
| **Merge.dev** | unified API per category (HR/payroll/etc.)                         | Merge-managed                        | Category-normalization play; different problem than ours                                                                                                                                                                           |
| **Pipedream** | 3,000+ APIs, managed auth, event triggers                          | Pipedream-managed                    | Excellent action/event infra; cloud custody again                                                                                                                                                                                  |
| **Ampersand** | real-time native integrations                                      | Ampersand-managed                    | Write-path infra                                                                                                                                                                                                                   |

## Our lane vs theirs

- **Their lane: ACTION** — an agent _does_ things in apps (send email, create
  ticket, post message). Tool-calling infrastructure.
- **Our lane: CONSUMPTION** — archives flow _in_ and become a queryable,
  attributed knowledge graph. Assimilation infrastructure.

The only overlap is OAuth plumbing — and that we adopt rather than rebuild.

## The consumer's connector architecture (three auth lanes)

1. **Local (default, zero-dependency)**: `creds.py` (segmented store,
   Muse-pattern broker) + `ortie` OAuth tokens + keychain/env passwords.
   Works offline, nothing leaves the box. Verified live: gmail via ortie.
2. **Nango (optional, 400+ apps)**: if you run Nango (self-hosted, open
   source), the consumer mints tokens through YOUR instance — `--auth nango`.
   You get Nango's prebuilt OAuth configs without custody loss: tokens live
   in your Nango, the consumer fetches them at call time, never stores.
3. **Manual (escape hatch)**: any app's export (zip of Notion pages, Slack
   export, Takeout) — `source.py` consumes it with zero auth plumbing.

## Why local-first remains the default

The Composio breach is the case study: cloud-held agent credentials become a
single high-value target (their sandbox + credential cache behind one
phished employee token). The consumer's law: credentials stay in
per-platform segmented stores, brokers attach them at the network boundary,
manifests record identity only. For the apps that matter most to you, that
law is not negotiable — which is why it's the default lane and Nango is the
opt-in for the long tail.

## Adding a connector (contributor guide)

A connector = (1) auth lane, (2) export function that writes text files +
an `acquisition.json` manifest with attribution, (3) feed through
`ingest.py` → `graph.py`. That's it — the rest of the engine is shared.
See `connectors.py` (gmail/imap) for the shape.
