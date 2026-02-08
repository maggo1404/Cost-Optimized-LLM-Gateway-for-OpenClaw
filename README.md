# LLM Gateway v2.0

**Kostenoptimiertes AI-Routing für OpenClaw**

> Lokales LLM + Intelligentes Caching + Drei-Tier-Routing = Minimale Kosten

## 🚀 Features

- **Lokales LLM zuerst**: Ollama, LM Studio, LocalAI, vLLM - kostenlos und privat
- **Intelligentes Routing**: Einfache Anfragen → lokal, Komplexe → Claude
- **Zwei-Stufen-Caching**: Exakter Cache + Semantischer Cache (bis 80% Cache-Rate)
- **Anthropic Prompt Caching**: 90% Rabatt auf wiederholte Prefixe
- **Budget-Kontrolle**: Tägliche Limits mit automatischem Kill-Switch
- **Dashboard**: Echtzeit-Statistiken im GitHub Dark Mode Stil

## 📦 Schnellstart

### 1. Repository klonen

```bash
git clone https://github.com/maggo1404/Cost-Optimized-LLM-Gateway-for-OpenClaw.git
cd Cost-Optimized-LLM-Gateway-for-OpenClaw
```

### 2. Konfiguration

```bash
# Environment-Datei erstellen
cp .env.example .env

# .env bearbeiten und mindestens setzen:
# - GATEWAY_SECRET (beliebiger geheimer String)
# - LOCAL_LLM_URL (falls Ollama nicht auf localhost:11434)
# - ANTHROPIC_API_KEY (für Premium-Tier)
```

### 3. Starten

```bash
# Nur Gateway
docker-compose up -d

# Mit Dashboard
docker-compose --profile dashboard up -d

# Mit Monitoring (Prometheus + Grafana)
docker-compose --profile monitoring up -d
```

Das Gateway läuft auf **http://localhost:8000**
Das Dashboard auf **http://localhost:3000**

## 🔧 Konfiguration

### Environment-Variablen (.env)

| Variable | Beschreibung | Default |
|----------|--------------|---------|
| `GATEWAY_SECRET` | API-Schlüssel für Authentifizierung | *pflicht* |
| `LOCAL_LLM_ENABLED` | Lokales LLM aktivieren | `true` |
| `LOCAL_LLM_URL` | OpenAI-kompatibler Endpunkt | `http://host.docker.internal:11434/v1` |
| `LOCAL_LLM_MODEL` | Standard-Modell | `llama3.2:latest` |
| `ANTHROPIC_API_KEY` | Claude API-Key | - |
| `ANTHROPIC_SETUP_TOKEN` | Token von `claude setup-token` | - |
| `GROQ_API_KEY` | Groq API-Key (Fallback) | - |
| `ROUTER_PROVIDER` | Routing-Provider (`local`/`groq`) | `local` |
| `DAILY_BUDGET_SOFT` | Warnung bei (USD) | `5.0` |
| `DAILY_BUDGET_HARD` | Stopp bei (USD) | `50.0` |

### Anthropic Setup Token

Für Claude-Integration mit `setup-token`:

```bash
# Auf einem Rechner mit Claude CLI
claude setup-token

# Token kopieren und in .env einfügen:
ANTHROPIC_SETUP_TOKEN=dein-token-hier
```

### Lokales LLM konfigurieren

**Ollama** (empfohlen):
```bash
# Ollama installieren
curl -fsSL https://ollama.com/install.sh | sh

# Modell herunterladen
ollama pull llama3.2

# In .env:
LOCAL_LLM_URL=http://host.docker.internal:11434/v1
LOCAL_LLM_MODEL=llama3.2:latest
```

**LM Studio**:
```bash
# In .env:
LOCAL_LLM_URL=http://host.docker.internal:1234/v1
LOCAL_LLM_MODEL=your-loaded-model
```

### Erweiterte Konfiguration (config.yaml)

Für komplexere Setups, kopiere `config/config.yaml.example`:

```bash
cp config/config.yaml.example config/config.yaml
```

Siehe Kommentare in der Datei für alle Optionen.

## 🔌 OpenClaw Integration

### Gateway-Konfiguration

In deiner OpenClaw-Konfiguration (`~/.openclaw/agents/main/agent/gateway.yaml`):

```yaml
# LLM Gateway als Provider
providers:
  llm-gateway:
    type: openai-compatible
    base_url: http://localhost:8000/v1
    api_key: ${GATEWAY_SECRET}
    models:
      - gateway-auto  # Automatisches Routing
      - gateway-local  # Nur lokales LLM
      - gateway-premium  # Nur Claude

# Standard-Modell
default_model: llm-gateway/gateway-auto
```

### Tier erzwingen

```bash
# Nur lokales LLM
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Erkläre mir Python"}],
    "force_tier": "local"
  }'
```

## 📊 Dashboard

Das Dashboard zeigt:
- **Requests**: Anzahl Anfragen pro Zeitraum
- **Cache-Rate**: Exact + Semantic Cache Hits
- **Modell-Verteilung**: Welche Modelle wie oft genutzt
- **Kosten**: Tägliche/Monatliche Ausgaben
- **Tier-Statistiken**: LOCAL vs CHEAP vs PREMIUM

Starten mit:
```bash
docker-compose --profile dashboard up -d
```

Öffne **http://localhost:3000**

## 🛡️ Sicherheit

- **Policy Gate**: Blockiert gefährliche Anfragen (Malware, Credentials)
- **Rate Limiting**: Requests/Minute und Tokens/Minute
- **Budget Guard**: Automatischer Stopp bei Budget-Überschreitung
- **Kill Switch**: Manuelles Abschalten über API

```bash
# Kill Switch aktivieren
curl -X POST "http://localhost:8000/admin/kill-switch?action=enable" \
  -H "Authorization: Bearer $GATEWAY_SECRET"
```

## 📈 Monitoring

Mit `--profile monitoring`:
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3001 (admin/admin)

## 🏗️ Architektur

```
┌─────────────────────────────────────────────────────────────┐
│                      LLM Gateway v2.0                       │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────────────┐ │
│  │ Policy  │→ │  Rate   │→ │ Budget  │→ │ Exact + Semantic│ │
│  │  Gate   │  │ Limiter │  │  Guard  │  │     Cache       │ │
│  └─────────┘  └─────────┘  └─────────┘  └─────────────────┘ │
│                                              ↓               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                   Tier Router                         │  │
│  │  ┌───────────┐  ┌───────────┐  ┌────────────────────┐ │  │
│  │  │   LOCAL   │  │   CHEAP   │  │      PREMIUM       │ │  │
│  │  │  Ollama   │  │ Local/Groq│  │   Claude Sonnet    │ │  │
│  │  │  $0/req   │  │ ~$0.001   │  │     ~$0.02         │ │  │
│  │  └───────────┘  └───────────┘  └────────────────────┘ │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 📝 API-Referenz

### POST /v1/chat/completions

OpenAI-kompatibel mit zusätzlichen Gateway-Parametern:

```json
{
  "messages": [{"role": "user", "content": "..."}],
  "model": "auto",
  "temperature": 0.7,
  "max_tokens": 4096,
  "force_tier": "local|cheap|premium",
  "context": {"file_path": "..."},
  "idempotency_key": "unique-key"
}
```

### GET /health
Health-Check ohne Authentifizierung.

### GET /api/metrics
Metriken (Authentifizierung erforderlich).

### GET /api/budget
Budget-Status (Authentifizierung erforderlich).

### GET /api/local/models
Liste verfügbarer lokaler Modelle.

## 🤝 Contributing

1. Fork das Repository
2. Feature-Branch erstellen (`git checkout -b feature/amazing`)
3. Änderungen committen (`git commit -m 'Add amazing feature'`)
4. Branch pushen (`git push origin feature/amazing`)
5. Pull Request erstellen

## 📄 Lizenz

MIT License - siehe [LICENSE](LICENSE)

---

**Erstellt für OpenClaw** | [Dokumentation](https://docs.openclaw.ai) | [Discord](https://discord.com/invite/clawd)
