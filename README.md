# CloudLabs Lab Assistant

A grounded Q&A sidecar for CloudLabs learners. A small in-VM agent answers
"I'm stuck on Task 2" questions using the lab's own guide plus MS Learn — and
it never does the lab for the learner. Full design:
`docs/superpowers/specs/sidecar-agent-design.md`.

![Instructor portal after creating an event, ingesting a guide, and starting the live pulse](docs/images/instructor-portal.png)

## What is in this repository

| Folder | What it is | Runs where |
|---|---|---|
| `orchestrator/` | FastAPI service: instructor portal, guide ingestion, Q&A API, analytics | Your machine (local) or Azure App Service |
| `sidecar/` | Go agent + chat UI that runs inside each learner VM | Learner VM (or your machine for a demo) |
| `scripts/` | CloudLabs integration pieces and a fake lab-guide server for local testing | Your machine / CloudLabs template |
| `infra/` | Bicep for `azd up` (App Service + Azure OpenAI + Storage) | Azure |
| `reference-guide/` | A sample lab guide used by the local demo | — |

## Prerequisites

Install these before you start:

1. **Python 3.11 or newer** — runs the orchestrator.
2. **Go 1.22 or newer** — only needed to build the sidecar agent
   (skip it if you only want the orchestrator and portal).
3. **PowerShell** — the sidecar build script is `sidecar/build.ps1` (Windows).
4. **An Azure OpenAI resource** with a chat deployment (for example `gpt-4o`)
   — only needed for real answers. You can start the portal, create an event,
   and ingest a guide **without any Azure credentials**; image captions are
   simply skipped until credentials are provided.
5. **Azure Developer CLI (`azd`)** — only needed if you deploy the
   orchestrator to Azure.

## Run it locally (step by step)

All commands are run from the repository root.

### Step 1 — Install the Python dependencies

```powershell
pip install -r requirements.txt
```

### Step 2 — Start the fake lab-guide server

This serves `reference-guide/` the same way CloudLabs serves a real guide, so
you can test everything without a real lab.

```powershell
python scripts/local_lab_server.py
```

Leave it running. It listens on `http://127.0.0.1:9000`.

### Step 3 — (Optional) Set your Azure OpenAI credentials

Required only for real answers and image captioning. Skip this step to just
explore the portal and ingestion.

```powershell
# PowerShell
$env:AZURE_OPENAI_ENDPOINT        = "https://<your-resource>.openai.azure.com"
$env:AZURE_OPENAI_API_KEY         = "<key>"
$env:AZURE_OPENAI_CHAT_DEPLOYMENT = "gpt-4o"        # your deployment name
```

```bash
# bash
export AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
export AZURE_OPENAI_API_KEY=<key>
export AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
```

### Step 4 — Start the orchestrator

In a second terminal:

```powershell
cd orchestrator
python -m uvicorn app.main:app --port 8000
```

Open **http://127.0.0.1:8000** — you should see the instructor portal
(the screenshot above).

### Step 5 — Create an event and ingest the guide

In the portal:

1. **Create event** — type any name and press **Create**.
2. **Ingest lab guide** — paste `http://127.0.0.1:9000/masterdoc.json` and
   press **Ingest**.
3. **Deploy values** — the portal now shows `sidecarEventID`,
   `sidecarEndpoint`, and `sidecarKey`. Keep these; the sidecar (and a real
   CloudLabs template) needs them.

### Step 6 — Build and run the sidecar (the learner side)

Requires Go. In a third terminal:

```powershell
pwsh sidecar/build.ps1        # produces orchestrator/static/sidecar.zip
```

Unzip `orchestrator/static/sidecar.zip` anywhere, then create a
`config.json` next to `sidecar.exe` with the three values from Step 5:

```json
{
  "endpoint":      "http://127.0.0.1:8000",
  "event_id":      "<sidecarEventID from the portal>",
  "key":           "<sidecarKey from the portal>",
  "deployment_id": "demo-machine"
}
```

Run `sidecar.exe`, open **http://127.0.0.1:7788**, and ask:
*"I'm stuck on Task 1, where do I search for AI Search?"*
(Real answers require the credentials from Step 3.)

### Quick smoke test (no Azure at all)

Verifies the fake guide server without touching Azure OpenAI:

```bash
python scripts/local_lab_server.py &
curl http://127.0.0.1:9000/masterdoc.json        # lists reference-guide/*.md
curl -I http://127.0.0.1:9000/Labs/Exercise-1.md # expect 200
kill %1
```

## Wire it into a real CloudLabs lab

Three pieces must be in place: the ARM template parameters, the deployment
(logon) script, and the install function. The portal prints the three values
after ingest — paste them into the CloudLabs template parameters before
launching the event.

### 1. `deploy.json` — add three parameters

```json
"sidecarEventID":  { "type": "string" },
"sidecarEndpoint": { "type": "string" },
"sidecarKey":      { "type": "securestring" }
```

### 2. `deploy.json` — add a variable (next to `cloudlabsCommon`)

```json
"sidecarArgs": "[concat(' -SidecarEventID ', parameters('sidecarEventID'), ' -SidecarEndpoint ', parameters('sidecarEndpoint'), ' -SidecarKey ', parameters('sidecarKey'))]"
```

### 3. `deploy.json` — thread the variable into `commandToExecute`

```json
"commandToExecute": "[concat('powershell.exe -ExecutionPolicy Unrestricted -File <labscript>.ps1', variables('cloudlabsCommon'), variables('Enable-CloudLabsEmbeddedShadow'), variables('sidecarArgs'))]"
```

### 4. Deployment script (for example `demo.ps1`) — accept and use the values

Add the three parameters to the script's `Param()` block:

```powershell
[string]$SidecarEventID,
[string]$SidecarEndpoint,
[string]$SidecarKey
```

Then add one line after the software installs:

```powershell
InstallSidecarAgent -SidecarEventID $SidecarEventID -SidecarEndpoint $SidecarEndpoint -SidecarKey $SidecarKey -DeploymentID $DeploymentID
```

### 5. Merge the install function

Merge `scripts/InstallSidecarAgent.ps1` into
`cloudlabs-windows-functions.ps1`. It downloads `sidecar.zip` from the
orchestrator, writes the per-event `config.json`, registers a logon task,
and drops a **Lab Assistant** shortcut on the desktop.

Reference copies of these snippets live in `scripts/arm-snippet.md` and
`scripts/demo-integration.md`.

## Deploy the orchestrator to Azure (one command)

```bash
azd config set alpha.resourceGroupDeployments on   # Bicep is resource-group scoped
azd up
```

Pick the target resource group when prompted (or set it up front with
`azd env set AZURE_RESOURCE_GROUP <rg-name>`). Set the `instructorKey`
parameter (`INSTRUCTOR_KEY`) to gate event creation; leave it empty for open
local development.

## Configuration reference

All settings are environment variables (see `orchestrator/app/config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | *(empty)* | Azure OpenAI endpoint; empty disables LLM features |
| `AZURE_OPENAI_API_KEY` | *(empty)* | Azure OpenAI key |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | `gpt-4o` | Chat deployment name |
| `AZURE_OPENAI_CHECKER_DEPLOYMENT` | *(empty)* | Cheap second-pass checker; empty = reuse chat deployment |
| `INSTRUCTOR_KEY` | *(empty)* | Gates event creation and analytics; empty = open (local dev) |
| `STORAGE_BACKEND` | `local` | `local` (files under `DATA_DIR`) or `blob` (Azure Storage) |
| `DATA_DIR` | `./data` | Where local storage writes |
| `RATE_LIMIT_QUESTIONS` | `10` | Max questions per learner per window (HTTP 429) |
| `RATE_LIMIT_WINDOW_SECONDS` | `600` | Sliding-window size |
| `EVENT_TOKEN_BUDGET` | `2000000` | Total tokens per event (HTTP 402) |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `⬇ sidecar.zip` returns 404 | The sidecar has not been built yet — run `pwsh sidecar/build.ps1`. |
| Ingest succeeds but captions read "captioning disabled" | `AZURE_OPENAI_ENDPOINT` is not set. Fine for exploring; set the Step 3 variables for real captions. |
| `401 bad instructor key` when creating an event | `INSTRUCTOR_KEY` is set on the server — pass the same key in the portal. |
| Port 8000 or 9000 already in use | Stop the other process, or pass a different `--port` to uvicorn (and update the endpoint everywhere you pasted it). |
| `go: command not found` when building the sidecar | Install Go and make sure it is on `PATH` (`$env:Path = "C:\Program Files\Go\bin;$env:Path"`). |

## How it behaves (design highlights)

### Graduated hinting

The "guide, don't solve" rule is structural, not just prompt text. Each
learner's asks are counted per task (`hints/{deployment_id}.json`): the first
ask gets a conceptual nudge, the second a narrower pointer, the third onward a
full step reference with reasoning — but never resolved `<inject .../>` values
or a copy-pasteable complete solution. A cheap second LLM pass classifies every
draft as PERFORM or POINT (`AZURE_OPENAI_CHECKER_DEPLOYMENT`, falls back to the
chat deployment); a PERFORM draft is regenerated once. A hard post-filter
strips any `<inject .../>` tag from answers regardless of what the model does.

### Abuse limits

The event key ships in plaintext on learner VMs, so `/api/query` gates before
spending tokens, computed from the existing `usage.jsonl` (see the
configuration table above for the three limit variables). The sidecar UI shows
friendly messages for both the rate limit (429) and the token budget (402).

### Instructor analytics

Every answered question appends a row to `analytics.jsonl` (task ref, question,
hint level, checker flag — never the answer or screenshots). The portal's
**Live event pulse** card polls `GET /api/events/{id}/analytics` (instructor
key) every 10 seconds: headline numbers, a per-task bar list (🔥 = learners
needed repeated hints there), and a recent-questions feed.

### Screen companion

Answers can include an annotated guide screenshot (rendered in the chat with a
caption, click to open full size), and the "Include my screen" toggle sends a
one-shot capture of the VM's screen with the question. If capture fails, the
question is still sent text-only.

### Prompt caching

Azure OpenAI caches prompt prefixes automatically (gpt-4o and newer, prefix
≥ 1024 tokens) when the prefix is **byte-identical** across requests. All
learners in an event share one enriched guide, so the system message is
ordered: static rules → guide → MS Learn results → hint block. Never put
per-request content (learn results, hint level, timestamps) before the guide —
that breaks the shared prefix and every query pays full input price.
`usage.jsonl` rows carry `tokens_cached`; expect it ≈ guide size on every
request after the first within a ~5–10 minute window.

## Tests

```bash
# orchestrator
cd orchestrator && python -m pytest tests/ -v

# sidecar (needs Go on PATH)
cd sidecar
$env:Path = "C:\Program Files\Go\bin;$env:Path"   # PowerShell
# export PATH="/c/Program Files/Go/bin:$PATH"     # bash
go test ./...
```
