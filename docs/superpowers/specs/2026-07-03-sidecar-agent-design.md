# Self-Healing Sidecar Agent for CloudLabs — Design

**Date:** 2026-07-03
**Status:** Approved for planning
**Author:** Danish (Spektra Systems) + Claude

---

## 1. Problem

During large CloudLabs training events, a large share of support tickets are not
about the lab content — they are about **environment hitches** (DNS loops, a hung
Docker daemon, stuck apt/choco locks, proxy drops, mismatched env vars) and
**"I'm stuck on Task 2, where's the option?"** navigation questions. Both are
repetitive, low-complexity, and today require a human on the support team.

We want a lightweight agent **inside the learner's VM** that resolves both classes
without a human ticket:

1. **Self-Heal** — one-click, deterministic repair of common platform gotchas.
2. **Grounded Q&A** — answers scoped to *this lab's* guide plus MS Learn, that
   *explains and points* — never does the lab step for the learner.

## 2. Goals / Non-Goals

**Goals**
- Agent runs *inside* the VM (hard requirement), installed via the existing
  CloudLabs logon-script mechanism — no change to how CloudLabs deploys.
- Per-lab knowledge that is **ephemeral** and **isolated** — a learner can only
  ever retrieve their own lab's guide, even when multiple labs run simultaneously.
- Instructor feeds the guide **once** before the event, from a CloudLabs preview
  link, a GitHub repo, or a direct upload.
- Flat cost regardless of learner count; a metering hook from day one.

**Non-Goals (this iteration)**
- No automation/solving of lab steps (defeats the point of a guided lab).
- No live screen annotation / computer vision overlay (roadmap, §12).
- No cloud vector database (Azure AI Search) — guides are small enough to skip it (§5).
- No billing engine — only the metering *log* (§10).

## 3. Architecture

Two pieces, split by *when* they run.

```
BEFORE the event (central, on instructor's MSDN RG)
┌─────────────────────────────────────────────────────────┐
│  Instructor Portal + Orchestrator (FastAPI, Python)      │
│  ├─ Ingest: source resolvers → vision-caption images →   │
│  │           enriched guide, stored per eventID (blob)   │
│  ├─ Query API: {question, eventID} → guide + MS Learn →   │
│  │             Azure OpenAI → grounded answer             │
│  └─ Metering log: one row per request                    │
└─────────────────────────────────────────────────────────┘
        ▲ HTTPS (endpoint + scoped key + eventID)
        │
DURING the event (inside each learner VM, N copies)
┌─────────────────────────────────────────────────────────┐
│  Sidecar Agent (Go, single static binary)                │
│  ├─ Windows service + logon scheduled task + shortcut    │
│  ├─ Local web UI on 127.0.0.1  (Ask tab / Fix tab)       │
│  ├─ Self-Heal engine: allowlisted PowerShell repairs     │
│  └─ Thin chat client → calls orchestrator Query API      │
└─────────────────────────────────────────────────────────┘
```

**Why this split:** the LLM cannot live in the VM (no GPU, cost, security), and it
*must* be central rather than per-VM because Azure OpenAI quota is
per-subscription-per-region — hundreds of per-RG OpenAI accounts collide on one
shared quota pool (CloudLabs' default "shared subscription" mode). The guide is
tiny, so it needs no cloud Search; it lives centrally per event, scoped by event ID.
The agent stays *thin*: everything it does that needs no network (self-heal, UI) is
local and instant; everything that needs the LLM is one HTTPS call home.

## 4. Isolation & Ephemerality Model

- Every VM is stamped at provisioning with exactly one **`eventID` + endpoint +
  scoped key** (`config.json`). It knows nothing about any other event.
- The orchestrator stores each event's enriched guide under its `eventID`. A query
  carries `eventID`; retrieval is scoped to that key. **Two simultaneous labs
  cannot cross-contaminate** — a storage-account VM literally cannot address the
  Copilot guide's content.
- Ephemeral: the event's guide + metering rows are deleted on event teardown (TTL
  or explicit "end event"). Nothing is stored forever.
- The scoped key authorizes only that event's endpoint, and can be revoked when the
  event ends.

## 5. Why no Azure AI Search

A 6–10 page guide is ~3–8k tokens of text — it fits *whole* in the model's context
window. A vector DB only earns its cost when the corpus is too large to fit; we are
far below that per lab. Stuffing the full enriched guide into context also removes
the "wrong chunk retrieved" failure mode, so answer quality is higher.

**Add it back only when** a guide exceeds ~50 pages or the agent must search across
many guides at once — and even then as a *lightweight local index in the VM*, not
the $250/mo cloud service. Guide loading is designed so this is a one-module swap.

## 6. Ingestion (instructor side)

Pluggable **source resolvers** normalize any input into markdown + image list:

| Source | Resolver behavior |
|--------|-------------------|
| **CloudLabs preview link** (`experience.cloudlabs.ai/#/labguidepreview/{guid}/{n}`) | SPA — resolve to CloudLabs' backing content API server-side. *(Build-time discovery task; endpoint known internally.)* |
| **GitHub repo + master doc** | Clone/pull (PAT for private repos), read the **master doc** to select the relevant exercise markdown files, fetch their raw content + referenced images. |
| **Direct upload** | Markdown/zip/PDF uploaded through the portal. |

Then a common pipeline:
1. Parse markdown, collect referenced screenshots.
2. **Vision-caption each image once** (multimodal model at ingest) → inline a text
   description next to each image. The guide becomes fully self-describing text.
3. Store the enriched guide under `eventID` (cheap blob), ready for context-stuffing.

Vision runs **at ingest (once per guide, central)** — never at query time — so every
learner query stays text-only, fast, and cheap.

**Master doc:** a separate instructor input that tells the ingester *which*
exercises are in scope and their order, so the KB reflects exactly the lab being run.

## 7. Flows

### Instructor — before the event (once)
1. Open portal → **create lab event** → receive `eventID` + endpoint + key.
2. Provide the guide via preview link / GitHub+master / upload.
3. Ingest runs (resolve → caption → store per `eventID`).
4. Paste `eventID` + endpoint + key into the CloudLabs deployment as **ARM
   parameters** (alongside those `deploy.json` already passes).
5. Launch event → CloudLabs fans out N VMs; each logon script stamps the three
   values into the VM's `config.json`.

### Learner — during the event (per stuck moment)
1. **🛟 Lab Assistant** shortcut/hotkey → sidecar opens local web UI on `127.0.0.1`.
2. **Fix tab** → run diagnostics → one-click allowlisted repair. *No network/LLM.*
3. **Ask tab** → "stuck on Task 2, can't find the option" → sidecar sends
   `{question, eventID}` → orchestrator loads that event's guide + relevant MS Learn
   → LLM → grounded answer that *explains and points, never performs the step*.

## 8. Self-Heal engine (safety-critical)

Repairs are a **fixed, allowlisted catalog** — the agent *selects* a repair, it
**never generates shell**. Each repair is:
- **Idempotent** — safe to run twice.
- **Reversible / logged** — records what it changed.
- **Explicit** — shown to the learner before running ("This will restart the Docker
  service"), one-click confirm.

Initial catalog (Windows-first, per confirmed runtime):
- DNS cache flush / resolver reset (DNS loops)
- Restart hung Docker Desktop / daemon
- Clear stuck choco/MSI installer locks
- Proxy / WinHTTP reset
- Repair known lab env-var drift (from `config.json` expected values)

Diagnostics run read-only first; repair is a separate, confirmed action. This is the
one place we do **not** simplify — running elevated repairs is a trust boundary.

## 9. Deployment integration (matches existing idiom)

No ARM resource changes needed for the agent itself. Reuse the exact patterns in
`cloudlabs-windows-functions.ps1`:

- **New function `InstallSidecarAgent`** (mirrors `InstallModernVmValidator`):
  download the agent zip from blob → `sc create` a Windows service → `-AtLogOn`
  scheduled task (mirrors `Enable-CloudLabsEmbeddedShadow`) → `WScript.Shell`
  desktop shortcut "🛟 Lab Assistant".
- **Config injection** (mirrors `CreateCredFile` string-replace): stamp `eventID` +
  endpoint + key into the agent's local `config.json`.
- **Per-lab call:** one line in the lab script (`demo.ps1`): `InstallSidecarAgent`,
  after the existing `choco install` lines.
- **ARM parameters:** add `sidecarEventID`, `sidecarEndpoint`, `sidecarKey` to the
  template's parameters and thread them into the CustomScriptExtension command
  (same mechanism as `cloudlabsCommon`).

## 10. Metering (hook now, monetize later)

The orchestrator appends **one row per request**:
`eventID, userID, timestamp, tokens_in, tokens_out, feature (ask|fix)`.

Application-level metering (orchestrator counts) — not infrastructure billing — so
usage can later be priced/tiered/marked-up independently of raw Azure cost, and the
LLM stays central (no quota wall). No billing engine is built now; the log *is* the
foundation. Investor-facing: "every Ask is a metered, priced event."

## 11. Tech stack

- **Sidecar:** Go — single static, zero-dependency binary; embeds the web UI assets;
  runs as a Windows service. (Rust is an equally valid choice; Go chosen for faster
  hackathon iteration and simpler Windows service tooling.)
- **Orchestrator + portal:** Python / FastAPI (matches the original design and the
  team's stack).
- **LLM + vision:** Azure OpenAI (multimodal model for ingest captioning; chat model
  for Q&A) on the central RG. Model version chosen from what is GA on the MSDN sub.
- **MS Learn:** official docs retrieval at query time via the orchestrator.
- **Guide storage:** Azure Blob, keyed by `eventID`. **No Azure AI Search.**

## 12. Roadmap (explicitly out of scope now)

- **Live screen annotation** — capture + vision + transparent overlay pointing at the
  UI element. Hardest piece; prove Tiers 1–2 first.
- **Local in-VM index** — only if guides grow large or multi-guide search is needed.
- **Billing** — usage tiers / per-seat pricing on top of the metering log.
- **Cross-platform** — Linux VM support (bash/systemctl repair modules) if labs need it.

## 13. Open questions / build-time discovery

1. **CloudLabs preview content API** — exact backing endpoint + auth for resolving
   `labguidepreview` URLs server-side (known internally; confirm during build).
2. **Private GitHub access** — PAT scope/storage for cloning private lab repos.
3. **Azure OpenAI model availability** — which chat + vision models are GA on the
   target MSDN subscription/region.
4. **Hotkey mechanism** — global hotkey vs. desktop shortcut vs. tray icon for
   invoking the local UI (shortcut is the safe default).
