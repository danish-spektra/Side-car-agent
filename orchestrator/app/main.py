from fastapi import FastAPI

app = FastAPI(title="CloudLabs Lab Assistant Orchestrator")

@app.get("/healthz")
def healthz():
    return {"status": "ok"}
