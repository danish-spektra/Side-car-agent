package main

import (
	"bytes"
	"embed"
	"encoding/base64"
	"encoding/json"
	"image/png"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/kbinani/screenshot"
)

//go:embed ui/index.html
var ui embed.FS

type Config struct {
	Endpoint     string `json:"endpoint"`
	EventID      string `json:"event_id"`
	Key          string `json:"key"`
	DeploymentID string `json:"deployment_id"`
}

func loadConfig(path string) (Config, error) {
	var cfg Config
	b, err := os.ReadFile(path)
	if err != nil {
		return cfg, err
	}
	err = json.Unmarshal(b, &cfg)
	if cfg.DeploymentID == "" {
		host, _ := os.Hostname()
		cfg.DeploymentID = host // labvm-{DeploymentID} per ARM naming
	}
	return cfg, err
}

// newAskHandler proxies /ask to the orchestrator. capture returns a base64
// PNG of the primary display; nil means screen capture is unavailable.
func newAskHandler(cfg Config, client *http.Client, capture func() (string, error)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			Question      string `json:"question"`
			IncludeScreen bool   `json:"include_screen"`
			ScreenB64     string `json:"screen_b64"` // frame picked in the browser (tab/window/screen)
		}
		if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		body := map[string]string{
			"event_id":      cfg.EventID,
			"deployment_id": cfg.DeploymentID,
			"question":      in.Question,
		}
		if in.ScreenB64 != "" {
			body["screen_b64"] = in.ScreenB64
		} else if in.IncludeScreen && capture != nil {
			if b64, err := capture(); err == nil {
				body["screen_b64"] = b64
			} else {
				log.Printf("screen capture failed, sending text only: %v", err)
			}
		}
		payload, _ := json.Marshal(body)
		req, _ := http.NewRequest("POST", cfg.Endpoint+"/api/query", bytes.NewReader(payload))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-Event-Key", cfg.Key)
		resp, err := client.Do(req)
		if err != nil {
			http.Error(w, "orchestrator unreachable: "+err.Error(), http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body)
	}
}

// captureScreen grabs the primary display as a base64 PNG. Called only when
// the learner opts in per question.
func captureScreen() (string, error) {
	img, err := screenshot.CaptureDisplay(0)
	if err != nil {
		return "", err
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(buf.Bytes()), nil
}

func main() {
	exe, _ := os.Executable()
	cfg, err := loadConfig(filepath.Join(filepath.Dir(exe), "config.json"))
	if err != nil {
		log.Fatalf("config.json: %v", err)
	}
	client := &http.Client{Timeout: 60 * time.Second}
	// ponytail: one page, no router — every path gets index.html
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		b, _ := ui.ReadFile("ui/index.html")
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Write(b)
	})
	http.HandleFunc("/ask", newAskHandler(cfg, client, captureScreen))
	log.Println("Lab Assistant on http://127.0.0.1:7788")
	log.Fatal(http.ListenAndServe("127.0.0.1:7788", nil))
}
