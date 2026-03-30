# BROADCAST - The Invest Post

Portal financeiro profissional em tempo real, estilo Bloomberg. Cotacoes, noticias, analises corporativas e curva DI.

## Acesso para Clientes

Este portal e servido via GitHub Pages e conecta-se automaticamente ao servidor BROADCAST.

Ao abrir pela primeira vez, insira a URL do servidor fornecida pelo administrador.

---

## Setup do Administrador

### 1. Requisitos
- Python 3.9+
- pip install flask flask-cors yfinance feedparser beautifulsoup4 deep_translator curl_cffi
- ngrok (gratuito) ou Cloudflare Tunnel

### 2. Rodar o servidor
```bash
cd BROADCAST
python app.py
```
O servidor inicia na porta 5050.

### 3. Expor para a internet (ngrok)
```bash
ngrok http 5050
```
Copie a URL gerada (ex: https://abc123.ngrok-free.app) e envie aos clientes.

### 4. Expor para a internet (Cloudflare Tunnel - alternativa gratuita)
```bash
cloudflared tunnel --url http://localhost:5050
```

### 5. Atualizar a URL no GitHub Pages
Os clientes podem configurar a URL diretamente no portal ao abrir pela primeira vez.

---

Built with Flask + yfinance + Yahoo Finance API
