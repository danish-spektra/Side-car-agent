# CloudLabs Lab Assistant

Grounded Q&A sidecar for CloudLabs learners: a thin in-VM agent that answers
"I'm stuck on Task 2" questions from the lab's own guide + MS Learn, and never
does the lab for them. Design: `docs/superpowers/specs/2026-07-03-sidecar-agent-design.md`.

## Local demo (no Azure, except OpenAI)

```bash
# 1. env (Azure OpenAI is the only cloud dependency)
export AZURE_OPENAI_ENDPOINT=https://<your>.openai.azure.com
export AZURE_OPENAI_API_KEY=<key>
export AZURE_OPENAI_CHAT_DEPLOYMENT=<deployment>   # default gpt-4o

# 2. run the fake lab-guide server (uses reference-guide/)
python scripts/local_lab_server.py &

# 3. run the orchestrator
cd orchestrator && pip install -r requirements.txt
uvicorn app.main:app --port 8000

# 4. instructor flow: open http://127.0.0.1:8000
#    create event -> ingest http://127.0.0.1:9000/masterdoc.json -> copy values

# 5. learner flow: build + run sidecar
pwsh sidecar/build.ps1
# put the printed eventID/endpoint/key into sidecar/config.json next to the exe, run it,
# open http://127.0.0.1:7788 and ask "I'm stuck on Task 1, where do I search for AI Search?"
```

Steps 1-2 above can be verified without Azure OpenAI credentials — see
"Harness smoke (no LLM)" below. The full learner flow (steps 3-5, an actual
grounded answer) needs real `AZURE_OPENAI_*` env as shown above.

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
spending tokens, computed from the existing `usage.jsonl`:

| env var | default | effect |
|---|---|---|
| `RATE_LIMIT_QUESTIONS` | 10 | max questions per learner per window → HTTP 429 |
| `RATE_LIMIT_WINDOW_SECONDS` | 600 | sliding window size |
| `EVENT_TOKEN_BUDGET` | 2000000 | tokens_in+out per event → HTTP 402 |

The sidecar UI shows friendly messages for both.

### Instructor analytics

Every answered question appends a row to `analytics.jsonl` (task ref, question,
hint level, checker flag — never the answer or screenshots). The portal's
**Live event pulse** card polls `GET /api/events/{id}/analytics` (instructor
key) every 10 s: headline numbers, a per-task bar list (🔥 = learners needed
repeated hints there), and a recent-questions feed.

### Screen companion

Answers can include an annotated guide screenshot (rendered in the chat with a
caption, click to open full size), and the "Include my screen" toggle sends a
one-shot capture of the VM's screen with your question. If capture fails, the
question is still sent text-only.

## Prompt caching

Azure OpenAI caches prompt prefixes automatically (gpt-4o and newer, prefix
≥ 1024 tokens) when the prefix is **byte-identical** across requests. All
learners in an event share one enriched guide, so the system message is
ordered: static rules → guide → MS Learn results → hint block. Never put
per-request content (learn results, hint level, timestamps) before the guide —
that breaks the shared prefix and every query pays full input price.
`usage.jsonl` rows carry `tokens_cached`; expect it ≈ guide size on every
request after the first within a ~5–10 min window.

## Deploy the orchestrator (instructor, one command)

```bash
azd up          # provisions App Service + Azure OpenAI + Storage on your sub
```

Note: the Bicep is resource-group scoped, so enable the azd alpha feature first
with `azd config set alpha.resourceGroupDeployments on`, and pick the target
resource group during `azd up` (set the `AZURE_RESOURCE_GROUP` environment
value when prompted, or via `azd env set AZURE_RESOURCE_GROUP <rg-name>`).

Set `INSTRUCTOR_KEY` (azd parameter `instructorKey`) to gate event creation;
leave it empty for open local dev.

## Wire a CloudLabs lab

1. Portal prints `sidecarEventID / sidecarEndpoint / sidecarKey` after ingest.
2. Merge `scripts/InstallSidecarAgent.ps1` into `cloudlabs-windows-functions.ps1`.
3. Follow `scripts/arm-snippet.md` + `scripts/demo-integration.md`.

## Harness smoke (no LLM)

Sanity-checks the fake docs proxy without touching Azure OpenAI:

```bash
python scripts/local_lab_server.py &
curl http://127.0.0.1:9000/masterdoc.json      # lists reference-guide/*.md as /Labs/*.md
curl -I http://127.0.0.1:9000/Labs/Exercise-1.md   # 200
curl -I http://127.0.0.1:9000/images/0001.png      # 200 (maps to reference-guide/Images/)
kill %1
```

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
