#!/usr/bin/env bash
# Descobre POR ONDE dá para entregar no WhatsApp nesta máquina.
#
# Só leitura: não sobe, não para, não reinicia, não repareia e não escaneia QR.
# Não imprime valores de variáveis, chaves, telefones nem ids de chat -- só
# nomes de porta, de processo e o começo das respostas HTTP, com o que parecer
# segredo mascarado.
#
#   bash ~/tracknews-bridge/diagnostico-entrega.sh
set -uo pipefail

mascara() { sed -E 's/(key|token|secret|senha|pass|apikey|authorization)([=: ])[^ ]*/\1\2<omitido>/Ig'; }
titulo()  { printf '\n===== %s =====\n' "$*"; }

titulo "1. portas ouvindo dentro do WSL"
if command -v ss >/dev/null 2>&1; then
  ss -ltnp 2>/dev/null | mascara || ss -ltn 2>/dev/null
else
  echo "(ss ausente; instale com: sudo apt install iproute2)"
fi

titulo "2. processos que parecem servir WhatsApp"
ps -eo pid,comm,args 2>/dev/null \
  | grep -iE 'waha|whatsapp|hermes|baileys|venom|wppconnect|evolution|node|bun|python' \
  | grep -v grep | cut -c1-160 | mascara | head -25

titulo "3. docker, procurado em todo lugar"
for cmd in docker docker.exe podman nerdctl; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "-- $cmd encontrado em $(command -v "$cmd")"
    timeout 20 "$cmd" ps --format '{{.Image}} | {{.Names}} | {{.Ports}} | {{.Status}}' 2>&1 | head -15 | mascara
  fi
done
command -v docker >/dev/null 2>&1 || echo "(docker nao esta no PATH deste shell)"
[ -S /var/run/docker.sock ] && echo "(existe /var/run/docker.sock)" || echo "(sem /var/run/docker.sock)"

titulo "4. o que responde em cada porta aberta"
# Descobre as portas do proprio ss e junta as candidatas conhecidas.
PORTAS="$( (ss -ltn 2>/dev/null | awk 'NR>1{print $4}' | sed -E 's/.*:([0-9]+)$/\1/' ;
            echo 3000; echo 3001; echo 3002; echo 3003; echo 8000; echo 8080;
            echo 4000; echo 21465) | sort -un | head -30 )"
python3 - <<PY
import urllib.error, urllib.request

portas = [p for p in """$PORTAS""".split() if p.isdigit()]

# Um 404 tambem identifica: o corpo do erro e os cabecalhos entregam o servidor
# ("Cannot GET /..." e Express; X-Powered-By, Server etc.). Por isso lemos o
# corpo mesmo quando o status e de erro.
caminhos = [
    "/", "/api", "/api/sessions", "/api/version", "/health", "/api/health",
    "/status", "/api/status", "/ping", "/sessions", "/docs", "/api/docs",
    "/instance/fetchInstances",     # Evolution API
    "/api/default/status-session",  # WPPConnect
]

def pede(url):
    """(status, cabecalhos_interessantes, trecho_do_corpo) ou (None, '', '')."""
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status, r.headers, r.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            corpo = e.read(200).decode("utf-8", "replace")
        except Exception:
            corpo = ""
        return e.code, e.headers, corpo
    except Exception:
        return None, None, ""

def limpa(texto):
    return " ".join((texto or "").split())[:120]

for porta in portas:
    base = f"http://localhost:{porta}"
    status, cabecalhos, corpo = pede(base + "/")
    if status is None:
        continue
    print(f"\n  porta {porta}:")
    if cabecalhos is not None:
        assinatura = [f"{c}: {cabecalhos.get(c)}"
                      for c in ("Server", "X-Powered-By", "Content-Type")
                      if cabecalhos.get(c)]
        if assinatura:
            print("    assinatura   " + " | ".join(assinatura))
    print(f"    /            HTTP {status}  {limpa(corpo)}")
    # Um 404 igual ao da raiz nao acrescenta nada: so mostramos o que difere.
    padrao = (status, limpa(corpo)[:60])
    iguais = []
    for caminho in caminhos[1:]:
        st, _, cp = pede(base + caminho)
        if st is None:
            continue
        if (st, limpa(cp)[:60]) == padrao:
            iguais.append(caminho)
        elif st in (401, 403):
            print(f"    {caminho:28} HTTP {st}  (EXISTE, pede autenticacao)")
        elif st < 400:
            print(f"    {caminho:28} HTTP {st}  {limpa(cp)}")
        else:
            print(f"    {caminho:28} HTTP {st}  {limpa(cp)[:70]}")
    if iguais:
        print(f"    (mesma resposta da raiz em: {', '.join(iguais)})")
PY

titulo "5. rastros de instalacao do WAHA"
for caminho in "$HOME/waha" "$HOME/.waha" /opt/waha "$HOME/docker/waha" "$HOME/src/waha"; do
  [ -e "$caminho" ] && echo "existe: $caminho"
done
command -v npm >/dev/null 2>&1 && npm ls -g --depth 0 2>/dev/null | grep -i -- 'waha\|whatsapp' | head -5
echo "(fim da busca por WAHA)"

titulo "6. Hermes"
for caminho in "$HOME/.hermes" "$HOME/.hermes/whatsapp/session" "$HOME/.hermes/logs"; do
  if [ -e "$caminho" ]; then
    echo "existe: $caminho  ($(find "$caminho" -maxdepth 1 2>/dev/null | wc -l) itens)"
  else
    echo "ausente: $caminho"
  fi
done
if [ -d "$HOME/.hermes/logs" ]; then
  echo "-- ultimas linhas de log (mascaradas):"
  tail -n 5 "$HOME"/.hermes/logs/*.log 2>/dev/null | cut -c1-160 | mascara | head -20
fi
systemctl --user list-units --type=service --no-pager 2>/dev/null \
  | grep -iE 'hermes|waha|whats' | mascara || true

titulo "7. veredito"
echo "Se a secao 4 mostrar uma porta respondendo JSON em /api/sessions, e o WAHA:"
echo "  ajuste waha.base_url no config.json e rode o bootstrap de novo."
echo "Se nenhuma responder, o WAHA nao esta no ar. Quem sobe e o Douglas -- este"
echo "diagnostico nao sobe, nao reinicia e nao repareia nada."
