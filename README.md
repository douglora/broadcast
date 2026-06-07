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

## Sistema Autopilot (pushes via ntfy)

O backend (`app.py`) inclui o **autopilot**, que envia notificações automáticas via [ntfy](https://ntfy.sh):

- **Pushes intraday** — alertas durante o pregão
- **Resumo de fechamento** — fim do pregão
- **Master briefing** — panorama consolidado
- **Morning call** — abertura do dia

### Trabalhar no autopilot pelo desktop E pelo celular

Para mexer no autopilot de qualquer lugar (desktop ou celular, via Claude Code na web),
o **código do backend precisa estar neste repositório Git**. As sessões da nuvem/celular
só enxergam o que está commitado aqui — nunca os arquivos locais do PC.

**Passo único, feito a partir do desktop** (onde estão os arquivos):

```bash
cd BROADCAST                      # pasta do projeto no seu PC
git checkout claude/autopilot-mobile-prompts-Zn2Oq   # ou crie/troque pela branch desejada

# 1. Garanta que segredos NÃO sejam commitados (já coberto pelo .gitignore):
#    tokens do ntfy, chaves de API e URLs de túnel devem ficar em um arquivo .env

# 2. Adicione o backend e os scripts do autopilot:
git add app.py requirements.txt   # + quaisquer outros arquivos .py do autopilot
git commit -m "Adiciona backend + autopilot ao repositorio"
git push -u origin claude/autopilot-mobile-prompts-Zn2Oq
```

Depois disso, é só abrir uma sessão (desktop ou celular), mandar o prompt de melhoria,
e as alterações são feitas e enviadas (push) direto pra esta branch.

> ⚠️ **Segredos:** nunca commite o token do ntfy nem chaves de API. Use um arquivo `.env`
> (ignorado pelo `.gitignore`) e carregue com `python-dotenv`.

---

Built with Flask + yfinance + Yahoo Finance API
