# CloudLabs Lab Assistant — Grounded Q&A Sidecar — Design

**Date:** 2026-07-03
**Status:** Approved for planning
**Author:** Danish (Spektra Systems) + Claude

---

## 1. Problem

During large CloudLabs training events, a share of support tickets are navigation
questions: *"I'm stuck on Task 2, I can't find the option."* These are repetitive,
low-complexity, and today pull a human off the support team.

We want a lightweight agent **inside the learner's VM** that answers these,
grounded in **this lab's own guide** plus **MS Learn**, and that **explains and
points — never performs the lab step** (that would defeat a guided lab).

> **Dropped from the earlier draft:** the self-heal tab. CloudLabs already surfaces
> deployment/ARM/region failures in its own portal deployment view, so localized
> repair adds little. The product is now purely **grounded Q&A**.

## 2. Goals / Non-Goals

**Goals**
- Agent runs *inside* the VM (hard requirement), installed via the existing
  CloudLabs logon-script mechanism — no change to how CloudLabs deploys.
- Answers grounded in the exact lab guide the learner is running, **including its
  screenshots**, plus MS Learn.
- Per-lab knowledge that is **ephemeral** and **isolated** — a learner can only ever
  retrieve their own lab's guide, even with multiple labs running at once.
- Instructor feeds the guide **once** before the event, by pointing at the guide's
  **master doc** (GitHub repo) or a **CloudLabs experience preview link**. No manual
  image upload — images are resolved dynamically from the markdown.
- Central infra is **`azd up`-deployable** to the instructor's MSDN subscription.
- Flat cost regardless of learner count; a metering hook from day one.

**Non-Goals (this iteration)**
- No self-heal / environment repair (dropped — see §1).
- No lab-step automation or solving.
- No screenshot annotation / browser control (roadmap, §11).
- No cloud vector DB (Azure AI Search) — guides are small enough to skip it (§5).
- No billing engine — only the metering *log* (§9).

## 3. Architecture

Two pieces, split by *when* they run.

```
BEFORE the event (central, azd-deployed to instructor's MSDN RG)
┌──────────────────────────────────────────────────────────────┐
│  Instructor Portal + Orchestrator (FastAPI, Python)           │
│  ├─ Ingest:  masterdoc → fetch markdown (Order) via CloudLabs  │
│  │           docs-api proxy → resolve + fetch each referenced  │
│  │           image by its relative path → vision-caption →     │
│  │           enriched guide, stored per eventID (blob)         │
│  ├─ Query:   {question, eventID} → enriched guide + MS Learn → │
│  │           Azure OpenAI → grounded answer + guide citation   │
│  └─ Metering: one row per request                             │
└──────────────────────────────────────────────────────────────┘
        ▲ HTTPS (orchestrator endpoint + scoped key + eventID)
        │
DURING the event (inside each learner VM, N copies)
┌──────────────────────────────────────────────────────────────┐
│  Sidecar Agent (single static binary — Go)                    │
│  ├─ Windows service + logon scheduled task + desktop shortcut │
│  ├─ Local web UI on 127.0.0.1  (single "Ask" chat)            │
│  └─ Thin client → proxies question to orchestrator Query API  │
│     (holds only the scoped orchestrator key, never the LLM    │
│      key; the page never sees a secret)                       │
└──────────────────────────────────────────────────────────────┘
```

**Why this split.** The LLM cannot live in the VM (no GPU, cost, security) and must
be **central, not per-VM**: Azure OpenAI quota is per-subscription-per-region, so
hundreds of per-RG OpenAI accounts collide on one shared quota pool (CloudLabs'
default shared-subscription mode). Guides are tiny, so no cloud Search; each event's
enriched guide lives centrally, scoped by event ID. The agent stays *thin* — a UI +
one HTTPS call home — which is why it drops into the VM with a single install line.

## 4. Isolation & Ephemerality

- Each VM is stamped at provisioning with exactly one **`eventID` + orchestrator
  endpoint + scoped key** (`config.json`). It knows nothing about any other event.
- The orchestrator stores each event's enriched guide under its `eventID`; a query
  carries `eventID`, so retrieval is scoped to that key. **Two simultaneous labs
  cannot cross-contaminate** — a storage-account VM cannot address the Copilot
  guide's content.
- Ephemeral: the event's guide + metering rows are deleted on teardown (TTL or an
  explicit "end event"). Nothing is stored forever.
- The scoped key authorizes only that event's endpoint and is revoked at teardown.

## 5. Why no Azure AI Search

A 6–10 page guide (~200–300 lines of markdown per exercise) is a few thousand tokens
of text — it fits *whole* in the model's context window. A vector DB only earns its
cost when the corpus is too big to fit; we are far below that per lab. Full-context
stuffing also removes the "wrong chunk retrieved" failure mode → higher answer
quality. **Add it back only** if a guide exceeds ~50 pages or the agent must search
across many guides at once — and then as a *lightweight local index*, not the cloud
service. Guide loading is isolated so this is a one-module swap.

## 6. Ingestion — masterdoc-driven, dynamic image resolution

This is the core of the instructor side. Input is **one of**:

| Source | How the ingester resolves it |
|--------|------------------------------|
| **Master doc** (`masterdoc.json`) — uploaded, or its repo/raw URL | Read the `Files[]` list; each entry has a `RawFilePath` (served via `docs-api.cloudlabs.ai/repos/raw.githubusercontent.com/...`) and an `Order`. Fetch each in order. The proxy fronts GitHub and handles **private repos**, so no PAT plumbing needed. |
| **CloudLabs experience preview link** (`experience.cloudlabs.ai/#/labguidepreview/{guid}/{n}`) | SPA — resolve the `{guid}` to its master doc via CloudLabs' content API, then proceed as above. *(Build-time discovery, §12.)* |

Then a common pipeline, per markdown file in `Order`:

1. Parse markdown.
2. **Resolve every image reference dynamically.** A ref like `![](../images/aisnew.png)`
   is resolved *relative to that markdown file's location* on the same proxy base
   (e.g. `.../Labs/Exercise-1.md` + `../images/aisnew.png` →
   `.../images/aisnew.png`) and fetched. **No separate images folder is ever
   uploaded** — the agent follows the path in the markdown to the exact image, as
   required.
3. **Vision-caption each fetched image once** (multimodal model, at ingest) and
   inline the caption next to the reference. The guide becomes fully self-describing
   text. Store the **resolved image URL alongside the caption** so the future
   annotation feature (§11) can re-fetch the exact screenshot on demand.
4. Recognize CloudLabs template tokens (`<inject key="Deployment ID" .../>`) as
   per-learner dynamic values, so the agent explains them rather than treating them
   as literal text.
5. Store the enriched guide under `eventID` (Azure Blob), ready for context-stuffing.

Vision runs **at ingest, once per guide, centrally** — never at query time — so every
learner query stays text-only, fast, and cheap.

## 7. Flows

### Instructor — before the event (once)
1. Open portal → **create lab event** → receive `eventID` + endpoint + key.
2. Point at the guide: paste the **master doc** (repo/raw URL or upload) *or* the
   **experience preview link**.
3. Ingest runs (fetch markdown in order → resolve+fetch images → caption → store per
   `eventID`).
4. Paste `eventID` + endpoint + key into the CloudLabs deployment as **ARM
   parameters** (alongside those `deploy.json` already passes).
5. Launch event → CloudLabs fans out N VMs; each logon script stamps the three values
   into the VM's `config.json`.

### Learner — during the event (per stuck moment)
1. **Lab Assistant** shortcut/hotkey → sidecar opens local web UI on `127.0.0.1`.
2. Types "stuck on Task 2, can't find the option" → sidecar sends
   `{question, eventID}` → orchestrator loads that event's enriched guide + relevant
   MS Learn → LLM → **grounded answer that explains and points, never performs the
   step**, with a citation to the guide step it came from.
3. Isolation: the sidecar only knows its own `eventID`, so it can only ever retrieve
   its own lab's guide.

## 8. Deployment integration

**Central infra (instructor side):** an **`azd` project** (Bicep + `azure.yaml`) the
instructor runs with **`azd up`** on their MSDN — provisions the FastAPI
orchestrator/portal, Azure OpenAI (chat + vision), blob storage, and the metering
store. We author the IaC; the instructor runs one command.

**VM side (matches existing `cloudlabs-windows-functions.ps1` idiom):**
- **New function `InstallSidecarAgent`** (mirrors `InstallModernVmValidator`):
  download the agent zip from blob → `sc create` a Windows service → `-AtLogOn`
  scheduled task (mirrors `Enable-CloudLabsEmbeddedShadow`) → `WScript.Shell`
  desktop shortcut "Lab Assistant".
- **Config injection** (mirrors `CreateCredFile` string-replace): stamp `eventID` +
  endpoint + key into the agent's local `config.json`.
- **Per-lab call:** one line in the lab script (`demo.ps1`): `InstallSidecarAgent`.
- **ARM parameters:** add `sidecarEventID`, `sidecarEndpoint`, `sidecarKey`, threaded
  into the CustomScriptExtension command like the existing `cloudlabsCommon`.

## 9. Metering (hook now, monetize later)

Orchestrator appends **one row per request**:
`eventID, deploymentID, timestamp, tokens_in, tokens_out`.
`DeploymentID` is unique per learner within an ODL (confirmed), so it is the
per-learner metering key.
Application-level metering (orchestrator counts) — so usage can later be
priced/tiered independently of raw Azure cost, and the LLM stays central (no quota
wall). No billing engine now; the log *is* the foundation.
`ponytail: metering = one append-only log line per request; no billing until a customer.`

## 10. Tech stack

- **Sidecar:** Go — single static, zero-dependency binary; embeds the web UI; runs as
  a Windows service. Holds only the scoped orchestrator key.
- **Orchestrator + portal:** Python / FastAPI.
- **LLM + vision:** Azure OpenAI on the central RG. Latest GA multimodal chat model
  (per user: "gpt-chat-latest" / GPT-5.x tier — pinned at build time to what the MSDN
  region offers, `gpt-4o` as fallback) for both Q&A and ingest captioning;
  `gpt-image-2` deployment reserved for the roadmap image-generation feature.
- **MS Learn:** official docs retrieval at query time via the orchestrator.
- **Guide storage:** Azure Blob, keyed by `eventID`. **No Azure AI Search.**
- **Infra:** Bicep + `azd`.

## 11. Roadmap (explicitly out of scope now)

> **Update 2026-07-03:** items 1 and (a one-shot variant of) live-screen help were
> pulled INTO scope as the "screen companion": annotated guide screenshots and an
> explicit "Include my screen" one-shot capture, both rendered in chat. Approved
> decisions: explicit capture button (consent-first), in-chat rendering (no OS
> overlay), Pillow-drawn boxes via marker protocol on the existing chat deployment.

Ordered by tractability:
1. **Continuous live overlay** — persistent screen watch + transparent always-on-top
   overlay drawing on the live screen. The hard part deferred from the companion.
2. **Image generation** — synthesize a pointer/diagram when no guide screenshot fits
   (`gpt-image-2` reserved for this).
3. **Browser control** — agent drives the learner's browser (Playwright-style) to the
   right screen. Powerful but must stay within "guide, don't solve."
4. **Local in-VM index** — only if guides grow large or multi-guide search is needed.
5. **Billing** — usage tiers / per-seat pricing on the metering log.

## 12. Open questions / build-time discovery

1. **CloudLabs experience preview → master doc mapping** — the content API that turns
   a `labguidepreview/{guid}` into its `masterdoc.json` (known internally; confirm
   during build). Master-doc/repo path works today without it.
2. **Azure OpenAI model pinning** — confirm the exact latest chat model name GA in
   the MSDN region at `azd up` time (fallback `gpt-4o`); `gpt-image-2` only when the
   image-gen roadmap item lands.
3. **Hotkey mechanism** — global hotkey vs. desktop shortcut vs. tray icon
   (shortcut is the safe default).
