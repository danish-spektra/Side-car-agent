package main

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadConfig(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "config.json")
	os.WriteFile(p, []byte(`{"endpoint":"https://orch","event_id":"ev1","key":"k1"}`), 0o644)
	cfg, err := loadConfig(p)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Endpoint != "https://orch" || cfg.EventID != "ev1" || cfg.Key != "k1" {
		t.Fatalf("bad config: %+v", cfg)
	}
}

func TestAskHandlerProxiesToOrchestrator(t *testing.T) {
	var gotPath, gotKey string
	var gotBody map[string]any
	orch := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotKey = r.Header.Get("X-Event-Key")
		b, _ := io.ReadAll(r.Body)
		json.Unmarshal(b, &gotBody)
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"answer":"look left","sources":[]}`))
	}))
	defer orch.Close()

	cfg := Config{Endpoint: orch.URL, EventID: "ev1", Key: "k1", DeploymentID: "dep-9"}
	h := newAskHandler(cfg, orch.Client(), nil)
	req := httptest.NewRequest("POST", "/ask", strings.NewReader(`{"question":"where is it"}`))
	rec := httptest.NewRecorder()
	h(rec, req)

	if gotPath != "/api/query" {
		t.Fatalf("path = %s", gotPath)
	}
	if gotKey != "k1" {
		t.Fatalf("key = %s", gotKey)
	}
	if gotBody["event_id"] != "ev1" || gotBody["deployment_id"] != "dep-9" || gotBody["question"] != "where is it" {
		t.Fatalf("body = %v", gotBody)
	}
	if _, ok := gotBody["screen_b64"]; ok {
		t.Fatalf("screen_b64 sent without include_screen: %v", gotBody)
	}
	if !strings.Contains(rec.Body.String(), "look left") {
		t.Fatalf("response = %s", rec.Body.String())
	}
}

func TestAskHandlerIncludesScreen(t *testing.T) {
	var gotBody map[string]any
	orch := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		json.Unmarshal(b, &gotBody)
		w.Write([]byte(`{"answer":"ok"}`))
	}))
	defer orch.Close()

	cfg := Config{Endpoint: orch.URL, EventID: "ev1", Key: "k1", DeploymentID: "dep-9"}
	capture := func() (string, error) { return "ZmFrZXBuZw==", nil }
	h := newAskHandler(cfg, orch.Client(), capture)
	req := httptest.NewRequest("POST", "/ask", strings.NewReader(`{"question":"what am I looking at","include_screen":true}`))
	rec := httptest.NewRecorder()
	h(rec, req)

	if gotBody["screen_b64"] != "ZmFrZXBuZw==" {
		t.Fatalf("screen_b64 = %v", gotBody["screen_b64"])
	}
	if gotBody["question"] != "what am I looking at" {
		t.Fatalf("body = %v", gotBody)
	}
}

func TestAskHandlerCaptureErrorDegradesToTextOnly(t *testing.T) {
	var gotBody map[string]any
	orch := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		json.Unmarshal(b, &gotBody)
		w.Write([]byte(`{"answer":"ok"}`))
	}))
	defer orch.Close()

	cfg := Config{Endpoint: orch.URL, EventID: "ev1", Key: "k1", DeploymentID: "dep-9"}
	capture := func() (string, error) { return "", errors.New("no display") }
	h := newAskHandler(cfg, orch.Client(), capture)
	req := httptest.NewRequest("POST", "/ask", strings.NewReader(`{"question":"still works","include_screen":true}`))
	rec := httptest.NewRecorder()
	h(rec, req)

	if gotBody["question"] != "still works" {
		t.Fatalf("question not proxied: %v", gotBody)
	}
	if _, ok := gotBody["screen_b64"]; ok {
		t.Fatalf("screen_b64 present despite capture error: %v", gotBody)
	}
	if !strings.Contains(rec.Body.String(), "ok") {
		t.Fatalf("response = %s", rec.Body.String())
	}
}
