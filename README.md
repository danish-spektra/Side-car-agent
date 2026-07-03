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

### Screen companion

Answers can include an annotated guide screenshot (rendered in the chat with a
caption, click to open full size), and the "Include my screen" toggle sends a
one-shot capture of the VM's screen with your question. If capture fails, the
question is still sent text-only.

## Deploy the orchestrator (instructor, one command)

```bash
azd up          # provisions App Service + Azure OpenAI + Storage on your sub
```

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
