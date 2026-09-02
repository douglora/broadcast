#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Transporte alternativo: o bridge.js do Hermes.

O WAHA sumiu da maquina do Douglas, mas o Hermes mantem um bridge de WhatsApp
ja pareado e conectado em 127.0.0.1:3000. Este modulo descobre sozinho o
contrato dessa API -- lendo as rotas do proprio bridge.js e, na falta dele,
sondando convencoes conhecidas -- e entrega por ali.

O Hermes aqui e SO TRANSPORTE. O texto continua vindo pronto e auditado da
nuvem, byte a byte: nada neste arquivo reescreve, resume ou enfeita alerta.

Somente biblioteca padrao (python3 >= 3.9).
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_PADRAO = "http://localhost:3000"

# Nomes de campo, em ordem de preferencia, para destino e para texto.
CAMPOS_DESTINO = ("chatId", "chat_id", "jid", "remoteJid", "to", "groupId", "chat", "id")
CAMPOS_TEXTO = ("text", "message", "body", "content", "msg", "mensagem")

# Convencoes usadas quando o bridge.js nao pode ser lido.
ROTAS_ENVIO_CONHECIDAS = ("/send", "/send-message", "/sendText", "/message",
                          "/messages", "/api/send", "/api/sendText")
ROTAS_LISTAGEM_CONHECIDAS = ("/chats", "/groups", "/api/chats", "/api/groups",
                             "/chats/groups", "/conversations")


def caminho_bridge_js() -> Path | None:
    """Acha o bridge.js do Hermes sem depender de caminho fixo."""
    base = Path.home() / ".hermes"
    fixo = base / "hermes-agent/scripts/whatsapp-bridge/bridge.js"
    if fixo.is_file():
        return fixo
    if base.is_dir():
        for achado in base.glob("*/scripts/whatsapp-bridge/bridge.js"):
            if achado.is_file():
                return achado
        for achado in base.rglob("bridge.js"):
            if "whatsapp" in str(achado).lower() and achado.is_file():
                return achado
    return None


def _campos_do_corpo(trecho: str) -> list[str]:
    """Nomes lidos de req.body no corpo de uma rota."""
    campos: list[str] = []
    for chaves in re.findall(r"\{([^{}]*)\}\s*=\s*(?:req\.body|payload|dados|data)", trecho):
        for bruto in chaves.split(","):
            nome = bruto.split(":")[0].split("=")[0].strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nome or ""):
                campos.append(nome)
    campos += re.findall(r"req\.body\.([A-Za-z_][A-Za-z0-9_]*)", trecho)
    campos += re.findall(r"req\.body\[['\"]([^'\"]+)['\"]\]", trecho)
    vistos, saida = set(), []
    for nome in campos:
        if nome not in vistos:
            vistos.add(nome)
            saida.append(nome)
    return saida


def le_api_do_fonte(caminho: Path) -> dict:
    """Extrai rotas e campos esperados direto do bridge.js."""
    try:
        fonte = caminho.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    linhas = fonte.splitlines()
    rotas: list[dict] = []
    padrao = re.compile(
        r"""(?:app|router|server)\.(get|post|put|patch)\s*\(\s*['"`]([^'"`]+)['"`]""",
        re.IGNORECASE)
    for numero, linha in enumerate(linhas):
        achado = padrao.search(linha)
        if not achado:
            continue
        metodo, rota = achado.group(1).upper(), achado.group(2)
        trecho = "\n".join(linhas[numero:numero + 25])
        rotas.append({"metodo": metodo, "rota": rota, "campos": _campos_do_corpo(trecho)})

    cabecalho_auth = None
    achado = re.search(r"""req\.headers\s*\[\s*['"]([^'"]+)['"]\s*\]""", fonte)
    if achado and achado.group(1).lower() in ("x-api-key", "authorization", "x-auth-token"):
        cabecalho_auth = achado.group(1)

    return {"arquivo": str(caminho), "rotas": rotas, "cabecalho_auth": cabecalho_auth}


def _pede(base: str, caminho: str, metodo: str = "GET", corpo: dict | None = None,
          chave: str | None = None, cabecalho_auth: str | None = None, timeout: int = 20):
    """(status, dados) ou (None, motivo). Nunca levanta."""
    url = base.rstrip("/") + caminho
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo)
    if dados is not None:
        req.add_header("Content-Type", "application/json")
    if chave and cabecalho_auth:
        req.add_header(cabecalho_auth, chave)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            bruto = resp.read(200_000).decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as erro:
        try:
            bruto = erro.read(2000).decode("utf-8", "replace")
        except OSError:
            bruto = ""
        return erro.code, bruto
    except (urllib.error.URLError, OSError, socket.timeout) as erro:
        return None, str(erro)
    try:
        return status, json.loads(bruto)
    except json.JSONDecodeError:
        return status, bruto


def saude(base: str = BASE_PADRAO) -> dict | None:
    status, dados = _pede(base, "/health", timeout=5)
    return dados if status == 200 and isinstance(dados, dict) else None


# --------------------------------------------------------------------------
# grupos
# --------------------------------------------------------------------------
def _extrai_id(valor) -> str | None:
    if isinstance(valor, str):
        return valor
    if isinstance(valor, dict):
        for chave in ("_serialized", "id", "jid", "user"):
            achado = valor.get(chave)
            if isinstance(achado, str):
                return achado
    return None


def _extrai_nome(entrada: dict) -> str | None:
    for chave in ("name", "subject", "formattedTitle", "title", "pushName"):
        valor = entrada.get(chave)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    meta = entrada.get("groupMetadata")
    if isinstance(meta, dict):
        for chave in ("subject", "name"):
            valor = meta.get(chave)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()
    return None


def _achata(dados):
    """Encontra a lista de chats dentro de qualquer envelope JSON."""
    if isinstance(dados, list):
        return [i for i in dados if isinstance(i, dict)]
    if isinstance(dados, dict):
        for chave in ("chats", "groups", "data", "result", "results", "items"):
            interno = dados.get(chave)
            if isinstance(interno, list):
                return [i for i in interno if isinstance(i, dict)]
    return []


def lista_grupos(base: str, api: dict, chave: str | None = None) -> tuple[list[dict], str | None]:
    """([{id, nome}], rota_usada). So GET: nao muda nada no Hermes."""
    candidatas: list[str] = []
    for rota in api.get("rotas", []):
        if rota["metodo"] == "GET" and re.search(r"chat|group|conversa", rota["rota"], re.I):
            if "{" not in rota["rota"] and ":" not in rota["rota"]:
                candidatas.append(rota["rota"])
    candidatas += [r for r in ROTAS_LISTAGEM_CONHECIDAS if r not in candidatas]

    for caminho in candidatas:
        status, dados = _pede(base, caminho, chave=chave,
                              cabecalho_auth=api.get("cabecalho_auth"))
        if status != 200:
            continue
        grupos = []
        for entrada in _achata(dados):
            ident = _extrai_id(entrada.get("id") or entrada.get("jid")
                               or entrada.get("chatId") or entrada.get("key"))
            if not ident or not ident.endswith("@g.us"):
                continue
            grupos.append({"id": ident, "nome": _extrai_nome(entrada) or ""})
        if grupos:
            return grupos, caminho
    return [], None


def acha_grupo(base: str, api: dict, nome: str, chave: str | None = None):
    """(chat_id, rota, erro). Nome tem de bater exatamente, e so pode haver um."""
    grupos, rota = lista_grupos(base, api, chave)
    if not grupos:
        return None, rota, ("nenhuma rota do bridge listou grupos "
                            f"(tentadas: {', '.join(ROTAS_LISTAGEM_CONHECIDAS)})")
    procurado = nome.strip().casefold()
    achados = [g for g in grupos if g["nome"].strip().casefold() == procurado]
    if not achados:
        return None, rota, f'grupo "{nome}" nao esta entre os {len(grupos)} grupos visiveis'
    if len(achados) > 1:
        return None, rota, f'{len(achados)} grupos com o nome exato "{nome}"; nao dá para escolher'
    return achados[0]["id"], rota, None


# --------------------------------------------------------------------------
# envio
# --------------------------------------------------------------------------
def rota_de_envio(api: dict) -> tuple[str | None, str | None, str | None]:
    """(rota, campo_destino, campo_texto) deduzidos do fonte, quando possivel."""
    melhores = []
    for rota in api.get("rotas", []):
        if rota["metodo"] != "POST":
            continue
        caminho = rota["rota"]
        if re.search(r"media|image|foto|file|audio|video|sticker|document", caminho, re.I):
            continue
        peso = 0
        if re.search(r"send|message|msg|enviar", caminho, re.I):
            peso += 2
        campos = rota.get("campos") or []
        destino = next((c for c in CAMPOS_DESTINO if c in campos), None)
        texto = next((c for c in CAMPOS_TEXTO if c in campos), None)
        if destino and texto:
            peso += 3
        if peso:
            melhores.append((peso, caminho, destino, texto))
    if melhores:
        melhores.sort(key=lambda item: -item[0])
        _, caminho, destino, texto = melhores[0]
        return caminho, destino or CAMPOS_DESTINO[0], texto or CAMPOS_TEXTO[0]
    return None, None, None


def envia(base: str, api: dict, chat_id: str, texto: str,
          chave: str | None = None, timeout: int = 30):
    """
    (resultado, status, detalhe) com resultado em {enviado, falhou, incerto}.

    'incerto' e reservado a timeout: a mensagem pode ter saido, entao a ponte
    nunca reenvia sozinha.
    """
    if not chat_id.endswith("@g.us"):
        return "falhou", None, "destino nao e grupo (@g.us); nada foi enviado"

    tentativas = []
    # Rota ja confirmada por `bridge.py hermes` e gravada no config: vai primeiro.
    fixo = api.get("envio") or {}
    if fixo.get("rota") and fixo.get("campo_destino") and fixo.get("campo_texto"):
        tentativas.append((fixo["rota"], fixo["campo_destino"], fixo["campo_texto"]))

    rota, campo_destino, campo_texto = rota_de_envio(api)
    if rota and (rota, campo_destino, campo_texto) not in tentativas:
        tentativas.append((rota, campo_destino, campo_texto))
    for caminho in ROTAS_ENVIO_CONHECIDAS:
        for destino in ("chatId", "jid", "to"):
            for campo in ("text", "message", "body"):
                if (caminho, destino, campo) not in tentativas:
                    tentativas.append((caminho, destino, campo))

    ultimo = "nenhuma tentativa"
    vistos = set()
    for caminho, destino, campo in tentativas:
        assinatura = (caminho, destino, campo)
        if assinatura in vistos:
            continue
        vistos.add(assinatura)
        # `raw: true` pede ao bridge do Hermes que NAO cole o cabecalho de
        # self-chat ("⚕ *Hermes Agent*" + regua) na frente do alerta. Bridges
        # sem o patch ignoram o campo.
        status, dados = _pede(base, caminho, "POST", {destino: chat_id, campo: texto, "raw": True},
                              chave=chave, cabecalho_auth=api.get("cabecalho_auth"),
                              timeout=timeout)
        if status is None:
            if "timed out" in str(dados).lower():
                return "incerto", None, f"timeout em {caminho}: {dados}"
            return "falhou", None, f"sem conexao com o bridge: {dados}"
        if 200 <= status < 300:
            return "enviado", status, f"{caminho} ({destino}/{campo})"
        if status in (401, 403):
            return "falhou", status, (f"{caminho} exige autenticacao; grave a chave em "
                                      "~/.config/tracknews-bridge/.env")
        ultimo = f"{caminho} -> HTTP {status}: {str(dados)[:120]}"
        # 404/405 significam rota errada: seguimos tentando a proxima convencao.
        if status not in (404, 405, 400, 422):
            return "falhou", status, ultimo
    return "falhou", None, f"nenhuma rota de envio aceitou; ultima: {ultimo}"


def descobre(base: str = BASE_PADRAO) -> dict:
    """Retrato completo da API, para o comando `bridge.py hermes`."""
    caminho = caminho_bridge_js()
    api = le_api_do_fonte(caminho) if caminho else {}
    api.setdefault("rotas", [])
    api["base_url"] = base
    api["saude"] = saude(base)
    rota, destino, texto = rota_de_envio(api)
    api["envio"] = {"rota": rota, "campo_destino": destino, "campo_texto": texto}
    return api


# --------------------------------------------------------------------------
# grupo pelos arquivos locais (quando o bridge nao lista grupos)
# --------------------------------------------------------------------------
JID_GRUPO = re.compile(r"\b(\d{10,}@g\.us)\b")
EXCLUIR_DIRS = ("node_modules", ".git", ".cache", ".npm", ".cargo", ".rustup",
                "venv", ".venv", "site-packages", "__pycache__", ".local/share/Trash")


def grupos_da_sessao() -> set[str]:
    """JIDs de grupo em que a sessao pareada do Hermes realmente esta.

    O Baileys grava um arquivo sender-key-<jid-do-grupo>--<participante>.json
    por grupo/participante em ~/.hermes/whatsapp/session. Serve de prova de
    pertencimento: um id achado em texto solto so vale se estiver aqui.
    """
    pasta = Path.home() / ".hermes" / "whatsapp" / "session"
    achados: set[str] = set()
    if not pasta.is_dir():
        return achados
    try:
        for entrada in os.scandir(pasta):
            nome = entrada.name
            if nome.startswith("sender-key-") and "@g.us" in nome:
                achado = JID_GRUPO.search(nome.replace("sender-key-", "", 1))
                if achado:
                    achados.add(achado.group(1))
    except OSError:
        pass
    return achados


def acha_grupo_local(nome: str, raizes: list[Path] | None = None):
    """
    (chat_id, fonte, erro). Procura o NOME do grupo em arquivos de texto da
    maquina (config e logs do Hermes, do agente antigo, do proprio Douglas) e
    pega o id @g.us que aparece perto dele. So leitura; nada e impresso alem do
    caminho do arquivo. O id so e aceito se a sessao pareada estiver nesse grupo
    (ver grupos_da_sessao) -- e se houver um unico candidato.
    """
    nome = nome.strip()
    if not nome:
        return None, None, "nome do grupo vazio"
    raizes = raizes or [Path.home()]
    excluir = [f"--exclude-dir={d}" for d in EXCLUIR_DIRS]
    arquivos: list[str] = []
    for raiz in raizes:
        if not raiz.is_dir():
            continue
        try:
            proc = subprocess.run(
                ["grep", "-rlIF", "--binary-files=without-match", *excluir, "-e", nome, str(raiz)],
                capture_output=True, text=True, timeout=150)
        except (subprocess.TimeoutExpired, OSError):
            continue
        arquivos += [a for a in proc.stdout.splitlines() if a.strip()]
    arquivos = arquivos[:200]
    if not arquivos:
        return None, None, f'"{nome}" nao aparece em nenhum arquivo de texto sob {", ".join(str(r) for r in raizes)}'

    pertence = grupos_da_sessao()
    candidatos: dict[str, str] = {}
    for caminho in arquivos:
        try:
            if os.path.getsize(caminho) > 20_000_000:
                continue
            texto = Path(caminho).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ocorrencia in re.finditer(re.escape(nome), texto):
            # Primeiro a propria linha (log/JSON compacto); so sem id nela e que
            # olhamos uma janela em volta (JSON indentado). Isso evita pegar o
            # id de um chat vizinho num log que lista varios grupos seguidos.
            ini = texto.rfind("\n", 0, ocorrencia.start()) + 1
            fim = texto.find("\n", ocorrencia.end())
            linha = texto[ini: fim if fim != -1 else len(texto)]
            achados = JID_GRUPO.findall(linha)
            if not achados:
                janela = texto[max(0, ocorrencia.start() - 600): ocorrencia.end() + 600]
                achados = JID_GRUPO.findall(janela)
            for jid in achados:
                candidatos.setdefault(jid, caminho)
    if not candidatos:
        return None, None, (f'"{nome}" aparece em {len(arquivos)} arquivo(s), mas sem id @g.us '
                            "por perto em nenhum deles")
    if pertence:
        validos = {j: c for j, c in candidatos.items() if j in pertence}
        if not validos:
            return None, None, (f"{len(candidatos)} id(s) achado(s) perto do nome, mas a sessao "
                                "pareada nao esta em nenhum desses grupos")
        candidatos = validos
    if len(candidatos) > 1:
        return None, None, (f"{len(candidatos)} grupos diferentes aparecem com esse nome nos "
                            "arquivos; nao da para escolher sozinho")
    jid, fonte = next(iter(candidatos.items()))
    return jid, fonte, None


# --------------------------------------------------------------------------
# grupo perguntando ao bridge chat por chat (GET /chat/:id)
# --------------------------------------------------------------------------
ROTAS_CHAT_CONHECIDAS = ("/chat/{jid}", "/chats/{jid}", "/api/chat/{jid}",
                         "/group/{jid}", "/groups/{jid}", "/api/groups/{jid}")


def rotas_de_chat(api: dict) -> list[str]:
    """Modelos de URL para um chat especifico, deduzidos do fonte + conhecidos."""
    modelos: list[str] = []
    for rota in api.get("rotas", []):
        caminho = rota["rota"]
        if rota["metodo"] == "GET" and re.search(r"chat|group", caminho, re.I) \
                and re.search(r":[A-Za-z_]+|\{[A-Za-z_]+\}", caminho):
            modelos.append(re.sub(r":[A-Za-z_]+|\{[A-Za-z_]+\}", "{jid}", caminho))
    for modelo in ROTAS_CHAT_CONHECIDAS:
        if modelo not in modelos:
            modelos.append(modelo)
    return modelos


def nome_do_chat(base: str, api: dict, jid: str, chave: str | None = None,
                 modelos: list[str] | None = None) -> tuple[str | None, str | None]:
    """(nome, modelo_que_funcionou). Tenta o jid cru e depois URL-encoded."""
    for modelo in modelos or rotas_de_chat(api):
        for alvo in (jid, urllib.parse.quote(jid, safe="")):
            status, dados = _pede(base, modelo.replace("{jid}", alvo), chave=chave,
                                  cabecalho_auth=api.get("cabecalho_auth"), timeout=6)
            if status == 200 and isinstance(dados, dict):
                interno = dados.get("chat") if isinstance(dados.get("chat"), dict) else dados
                nome = _extrai_nome(interno)
                if nome:
                    return nome, modelo
                return None, modelo   # o chat existe, mas veio sem nome
            if status not in (404, 405, None):
                break
    return None, None


def acha_grupo_por_sessao(base: str, api: dict, nome: str, chave: str | None = None):
    """
    (chat_id, detalhe, erro). Pega os grupos em que a sessao pareada esta (arquivos
    sender-key do Baileys), pergunta o nome de cada um ao bridge via GET /chat/:id
    e casa o nome exato. Um unico match, ou nada.
    """
    jids = sorted(grupos_da_sessao())
    if not jids:
        return None, None, "sessao sem arquivos sender-key: nao sei em que grupos ela esta"
    modelos = rotas_de_chat(api)
    procurado = nome.strip().casefold()
    achados, com_nome, modelo_ok = [], 0, None
    for jid in jids:
        nome_chat, modelo = nome_do_chat(base, api, jid, chave, modelos)
        if modelo and modelo_ok is None:
            modelo_ok = modelo
            modelos = [modelo]          # daqui em diante so o que funcionou
        if nome_chat:
            com_nome += 1
            if nome_chat.strip().casefold() == procurado:
                achados.append(jid)
    detalhe = f"{len(jids)} grupos na sessao, {com_nome} com nome via {modelo_ok or 'nenhuma rota'}"
    if not achados:
        return None, detalhe, f'nenhum dos grupos se chama "{nome}" ({detalhe})'
    if len(achados) > 1:
        return None, detalhe, f'{len(achados)} grupos com o nome exato "{nome}"; nao da para escolher'
    return achados[0], detalhe, None


def pares_de_messages(base: str, api: dict, chave: str | None = None) -> dict[str, str]:
    """{jid_de_grupo: nome} extraidos de GET /messages, quando o bridge expoe."""
    pares: dict[str, str] = {}
    for caminho in ("/messages?limit=500", "/messages", "/api/messages"):
        status, dados = _pede(base, caminho, chave=chave,
                              cabecalho_auth=api.get("cabecalho_auth"), timeout=8)
        if status != 200:
            continue
        for item in _achata(dados) or ([dados] if isinstance(dados, dict) else []):
            jid = _extrai_id(item.get("chatId") or item.get("chat_id") or item.get("jid")
                             or item.get("remoteJid") or item.get("from") or item.get("chat"))
            if not jid or not jid.endswith("@g.us"):
                continue
            nome = None
            for chave_nome in ("chatName", "chat_name", "groupName", "group_name",
                               "subject", "name", "title"):
                valor = item.get(chave_nome)
                if isinstance(valor, str) and valor.strip():
                    nome = valor.strip()
                    break
            if nome:
                pares.setdefault(jid, nome)
        if pares:
            break
    return pares


def acha_grupo_por_messages(base: str, api: dict, nome: str, chave: str | None = None):
    pares = pares_de_messages(base, api, chave)
    if not pares:
        return None, None, "GET /messages nao trouxe grupos com nome"
    procurado = nome.strip().casefold()
    achados = [j for j, n in pares.items() if n.strip().casefold() == procurado]
    if not achados:
        return None, None, f'"{nome}" nao aparece entre os {len(pares)} grupos com mensagens recentes'
    if len(achados) > 1:
        return None, None, f"{len(achados)} grupos com esse nome nas mensagens recentes"
    return achados[0], "GET /messages", None


def _mascara_jid(texto: str) -> str:
    return re.sub(r"\d{10,}@(g\.us|c\.us|s\.whatsapp\.net)", r"<id-omitido>@\1", texto or "")


def diagnostico(base: str, nome_grupo: str) -> dict:
    """Retrato SEM SEGREDOS do que a descoberta enxerga -- vai para o heartbeat."""
    api = descobre(base)
    saida = {
        "bridge_js": api.get("arquivo"),
        "saude": api.get("saude"),
        "rotas": [f"{r['metodo']} {r['rota']}" for r in api.get("rotas", [])][:20],
        "envio_deduzido": api.get("envio"),
        "cabecalho_auth": api.get("cabecalho_auth"),
    }
    grupos, rota = lista_grupos(base, api)
    saida["listagem_de_grupos"] = {"rota": rota, "grupos_vistos": len(grupos),
                                   "nome_bate": sum(1 for g in grupos
                                                    if g["nome"].strip().casefold() == nome_grupo.strip().casefold())}
    jid_s, detalhe_s, erro_s = acha_grupo_por_sessao(base, api, nome_grupo)
    saida["por_sessao"] = {"achou": bool(jid_s), "detalhe": detalhe_s, "erro": _mascara_jid(erro_s or "")}
    jid_m, _, erro_m = acha_grupo_por_messages(base, api, nome_grupo)
    saida["por_messages"] = {"achou": bool(jid_m), "erro": _mascara_jid(erro_m or "")}
    jid, fonte, erro = acha_grupo_local(nome_grupo)
    saida["busca_local"] = {"achou": bool(jid), "fonte": fonte, "erro": _mascara_jid(erro or "")}
    saida["grupos_da_sessao"] = len(grupos_da_sessao())
    return saida
