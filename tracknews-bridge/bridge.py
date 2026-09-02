#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ponte de entrega TrackNews -> WAHA (grupo "AutoPilot News").

A nuvem (douglora/tracknews-autopilot, GitHub Actions) coleta, valida cada numero
contra a fonte, aplica relevancia, deduplica e ESCREVE o alerta. Esta ponte so
ENTREGA o que a nuvem aprovou -- sem tocar em uma virgula do texto.

Somente biblioteca padrao (python3 >= 3.9). Nao depende de rede alem do git do
repo de estado e do endpoint de envio do WAHA.

Comandos:
  status      estado da ponte (config sem segredos, contadores, fila)
  waha        reconhecimento SOMENTE LEITURA do WAHA + localizar o grupo
  dry-run     o que sairia agora + simulacao dos limites (nao envia, nao grava)
  run         modo real (timer): entrega respeitando os limites
  test-send   um unico envio de teste (exige --confirmo)
  seed        marca a fila atual como ja enviada, sem enviar nada
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Fuso: Brasil nao tem horario de verao desde 2019; o offset fixo -03:00 e um
# fallback correto caso o tzdata nao esteja instalado no WSL.
# --------------------------------------------------------------------------
try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("America/Sao_Paulo")
except Exception:  # pragma: no cover - depende do tzdata do sistema
    TZ = timezone(timedelta(hours=-3), "America/Sao_Paulo")

HOME = Path(os.environ.get("TRACKNEWS_BRIDGE_HOME", str(Path.home() / "tracknews-bridge")))
CONFIG_PATH = HOME / "config.json"
ENVIADOS_PATH = HOME / "enviados.json"
LOG_PATH = HOME / "log.jsonl"
PAUSED_PATH = HOME / "PAUSED"
REPO_DIR = HOME / "repo.git"
LOCK_PATH = HOME / ".lock"
ENV_FILE = Path.home() / ".config" / "tracknews-bridge" / ".env"

DEFAULTS = {
    "envio_habilitado": False,
    "waha": {
        "base_url": "http://localhost:3000",
        "session": "default",
        "send_path": "/api/sendText",
        "api_key_env": "WAHA_API_KEY",
        "timeout_s": 20,
    },
    "destino": {
        "nome_grupo": "AutoPilot News",
        "chat_id": None,
        "participantes_esperados": 1,
    },
    "repo": {
        "url": "https://github.com/douglora/tracknews-autopilot.git",
        "branch": "state",
        "dias_janela": 2,
    },
    "limites": {
        "por_hora": 4,
        "por_dia": 12,
        "espacamento_min": 10,
        "silencio_inicio": "22:00",
        "silencio_fim": "06:30",
        "max_por_execucao": 1,
        "max_idade_horas": None,
    },
}

REVISOES_PRIORITARIAS = {"CORRECTED", "RETRACTED"}


# --------------------------------------------------------------------------
# utilidades
# --------------------------------------------------------------------------
def agora_local() -> datetime:
    return datetime.now(TZ)


def mascara(valor: str | None) -> str:
    """Nunca imprimimos chat id, telefone ou chave: so um rotulo estavel."""
    if not valor:
        return "(nao configurado)"
    return "id:" + hashlib.sha256(valor.encode("utf-8")).hexdigest()[:12]


def deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for chave, valor in (extra or {}).items():
        if isinstance(valor, dict) and isinstance(out.get(chave), dict):
            out[chave] = deep_merge(out[chave], valor)
        else:
            out[chave] = valor
    return out


def carrega_env() -> None:
    """Le ~/.config/tracknews-bridge/.env (KEY=VALOR) sem imprimir nada."""
    if not ENV_FILE.is_file():
        return
    for linha in ENV_FILE.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def carrega_config() -> dict:
    bruto = {}
    if CONFIG_PATH.is_file():
        try:
            bruto = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as erro:
            sys.exit(f"config.json invalido: {erro}")
    return deep_merge(DEFAULTS, bruto)


def grava_config(cfg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_PATH)
    os.chmod(CONFIG_PATH, 0o600)


def carrega_enviados() -> dict | None:
    """None = arquivo ausente (primeira execucao ou perda: tudo anterior conta como enviado)."""
    if not ENVIADOS_PATH.is_file():
        return None
    try:
        dados = json.loads(ENVIADOS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(dados, dict) or "alertas" not in dados:
        return None
    return dados


def grava_enviados(dados: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = ENVIADOS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(ENVIADOS_PATH)
    os.chmod(ENVIADOS_PATH, 0o600)


_TRAVA = None


def trava_execucao() -> bool:
    """Uma execucao por vez. O timer e um comando manual rodando juntos leriam o
    mesmo enviados.json antes de qualquer um gravar -- e o mesmo alerta sairia
    duas vezes no grupo. flock e liberado sozinho quando o processo termina."""
    global _TRAVA
    HOME.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a")
    try:
        os.chmod(LOCK_PATH, 0o600)
    except OSError:
        pass
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _TRAVA = handle
    return True


def registra_log(evento: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    evento = {"ts": agora_local().isoformat(), **evento}
    with LOG_PATH.open("a", encoding="utf-8") as saida:
        saida.write(json.dumps(evento, ensure_ascii=False) + "\n")
    try:
        os.chmod(LOG_PATH, 0o600)
    except OSError:
        pass


# --------------------------------------------------------------------------
# repo de estado (somente leitura)
# --------------------------------------------------------------------------
def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=check,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def garante_repo(cfg: dict) -> None:
    if (REPO_DIR / "HEAD").is_file():
        return
    HOME.mkdir(parents=True, exist_ok=True)
    branch = cfg["repo"]["branch"]
    print(f"clonando o repo de estado (bare, --depth 1, branch {branch})...")
    git(
        "clone", "--bare", "--depth", "1", "--single-branch",
        "--branch", branch, cfg["repo"]["url"], str(REPO_DIR),
    )


def atualiza_repo(cfg: dict) -> None:
    branch = cfg["repo"]["branch"]
    git("--git-dir", str(REPO_DIR), "fetch", "--depth", "1", "--force",
        "origin", f"{branch}:refs/heads/{branch}")


def le_arquivo_do_estado(cfg: dict, caminho: str) -> str | None:
    """Le um arquivo do branch de estado. None se ele nao existe naquele dia."""
    proc = git("--git-dir", str(REPO_DIR), "show",
               f"{cfg['repo']['branch']}:{caminho}", check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout


def caminhos_da_janela(cfg: dict) -> list[str]:
    """
    O nome do arquivo e a data UTC (review_queue.py usa datetime.now(UTC)).
    Sao Paulo e UTC-3, entao das 21h a meia-noite o arquivo do dia ja e o de
    amanha em UTC. Por isso lemos uma janela de dias, nunca um dia so.
    """
    hoje_utc = datetime.now(timezone.utc).date()
    dias = max(1, int(cfg["repo"]["dias_janela"]))
    return [
        f"outputs/review/{(hoje_utc - timedelta(days=i)).isoformat()}.jsonl"
        for i in range(dias)
    ]


def parse_ts(valor: str | None) -> datetime:
    if not valor:
        return datetime.now(timezone.utc)
    texto = valor.strip()
    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(texto)
    except ValueError:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def coleta_aprovados(cfg: dict) -> tuple[list[dict], dict]:
    """
    Retorna (aprovados, estatisticas).

    O JSONL real tem DUAS formas de linha:
      - item bloqueado : {"item", "claims", "gate", "recorded_at"}  <- sem "alert"
      - alerta         : {"alert", "gate", "blocked_reasons", "source_url", "recorded_at"}
    So a segunda forma, e so com gate.allowed == true, pode virar mensagem.
    """
    estat = {"linhas": 0, "com_alerta": 0, "aprovados": 0, "segurados": 0,
             "bloqueados": 0, "arquivos": [], "invalidas": 0, "digests": 0}
    por_id: dict[str, dict] = {}

    # Digest matinal (07:00, dias uteis): a nuvem grava em outputs/digest/<dia>.md,
    # fora do JSONL de revisao. E a "camada do grupo" do formato-mensagens, entao
    # entra na mesma fila, com o mesmo dedup e os mesmos limites. O arquivo
    # .longo.md e a camada privada e NUNCA entra aqui.
    hoje_utc = datetime.now(timezone.utc).date()
    for i in range(max(1, int(cfg["repo"]["dias_janela"]))):
        dia = (hoje_utc - timedelta(days=i)).isoformat()
        caminho = f"outputs/digest/{dia}.md"
        conteudo = le_arquivo_do_estado(cfg, caminho)
        if conteudo is None:
            continue
        texto = conteudo.rstrip()
        if not texto or texto.startswith("[SILENT]"):
            continue
        estat["arquivos"].append(caminho)
        estat["digests"] += 1
        ano, mes, d = (int(p) for p in dia.split("-"))
        por_id[f"digest-{dia}"] = {
            "alert_id": f"digest-{dia}",
            "text": texto,
            "priority": "DIGEST",
            "revision_type": "DIGEST",
            "parent_alert_id": None,
            "story_id": None,
            "recorded_at": datetime(ano, mes, d, 7, 0, tzinfo=TZ),
            "source_url": None,
            "origem": caminho,
        }

    for caminho in caminhos_da_janela(cfg):
        conteudo = le_arquivo_do_estado(cfg, caminho)
        if conteudo is None:
            continue
        estat["arquivos"].append(caminho)
        for linha in conteudo.splitlines():
            linha = linha.strip()
            if not linha:
                continue
            estat["linhas"] += 1
            try:
                registro = json.loads(linha)
            except json.JSONDecodeError:
                estat["invalidas"] += 1
                continue
            gate = registro.get("gate") or {}
            alerta = registro.get("alert")
            if not isinstance(alerta, dict):
                estat["bloqueados"] += 1
                continue
            estat["com_alerta"] += 1
            if gate.get("allowed") is not True:
                if gate.get("action") == "hold":
                    estat["segurados"] += 1
                else:
                    estat["bloqueados"] += 1
                continue
            alert_id = alerta.get("alert_id")
            texto = alerta.get("text")
            if not alert_id or not isinstance(texto, str) or not texto.strip():
                estat["invalidas"] += 1
                continue
            estat["aprovados"] += 1
            # a ultima ocorrencia do mesmo alert_id vence (a nuvem pode reemitir)
            por_id[alert_id] = {
                "alert_id": alert_id,
                "text": texto,
                "priority": alerta.get("priority"),
                "revision_type": alerta.get("revision_type") or "NEW",
                "parent_alert_id": alerta.get("parent_alert_id"),
                "story_id": alerta.get("story_id"),
                "recorded_at": parse_ts(registro.get("recorded_at")),
                "source_url": registro.get("source_url") or alerta.get("source_url"),
                "origem": caminho,
            }
    return list(por_id.values()), estat


def ordena_fila(itens: list[dict]) -> list[dict]:
    """Correcao e retratacao na frente; depois FIFO por recorded_at."""
    return sorted(
        itens,
        key=lambda i: (
            0 if (i["revision_type"] or "").upper() in REVISOES_PRIORITARIAS else 1,
            i["recorded_at"],
        ),
    )


# --------------------------------------------------------------------------
# limites
# --------------------------------------------------------------------------
def historico_envios(enviados: dict) -> list[datetime]:
    """So envio real conta para os limites. 'seed' e 'incerto' nao contam."""
    saida = []
    for registro in (enviados.get("alertas") or {}).values():
        if registro.get("resultado") != "enviado":
            continue
        quando = registro.get("enviado_em")
        if quando:
            saida.append(parse_ts(quando).astimezone(TZ))
    return sorted(saida)


def hora_minuto(texto: str) -> tuple[int, int]:
    hora, _, minuto = texto.partition(":")
    return int(hora), int(minuto or 0)


def em_silencio(cfg: dict, agora: datetime) -> bool:
    ini_h, ini_m = hora_minuto(cfg["limites"]["silencio_inicio"])
    fim_h, fim_m = hora_minuto(cfg["limites"]["silencio_fim"])
    inicio = agora.replace(hour=ini_h, minute=ini_m, second=0, microsecond=0)
    fim = agora.replace(hour=fim_h, minute=fim_m, second=0, microsecond=0)
    if inicio <= fim:  # janela no mesmo dia
        return inicio <= agora < fim
    return agora >= inicio or agora < fim  # janela cruza a meia-noite


def proxima_janela(cfg: dict, agora: datetime) -> datetime:
    fim_h, fim_m = hora_minuto(cfg["limites"]["silencio_fim"])
    alvo = agora.replace(hour=fim_h, minute=fim_m, second=0, microsecond=0)
    if alvo <= agora:
        alvo += timedelta(days=1)
    return alvo


def avalia_limites(cfg: dict, enviados: dict, agora: datetime) -> tuple[bool, str, datetime | None]:
    """(pode_enviar, motivo, liberado_em)."""
    limites = cfg["limites"]
    if PAUSED_PATH.exists():
        return False, "kill switch ativo (arquivo PAUSED)", None
    if em_silencio(cfg, agora):
        alvo = proxima_janela(cfg, agora)
        return False, (f"silencio {limites['silencio_inicio']}-{limites['silencio_fim']} "
                       f"(America/Sao_Paulo)"), alvo

    historico = historico_envios(enviados)
    if historico:
        ultimo = historico[-1]
        espera = timedelta(minutes=limites["espacamento_min"])
        if agora - ultimo < espera:
            return False, f"espacamento minimo de {limites['espacamento_min']} min", ultimo + espera

    ultima_hora = [t for t in historico if agora - t < timedelta(hours=1)]
    if len(ultima_hora) >= limites["por_hora"]:
        liberado = ultima_hora[0] + timedelta(hours=1)
        return False, f"teto de {limites['por_hora']} mensagens por hora", liberado

    hoje = [t for t in historico if t.date() == agora.date()]
    if len(hoje) >= limites["por_dia"]:
        amanha = (agora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return False, f"teto de {limites['por_dia']} mensagens por dia", amanha

    return True, "ok", None


def simula_limites(cfg: dict, fila: list[dict], enviados: dict, agora: datetime) -> tuple[list, list]:
    """Roda o relogio para a frente e diz quem sai hoje e quem fica na fila."""
    limites = cfg["limites"]
    virtual = {"alertas": dict(enviados.get("alertas") or {})}
    sairiam, ficariam = [], []
    relogio = agora
    fim_do_dia = agora.replace(hour=23, minute=59, second=59, microsecond=0)

    for item in fila:
        pode = False
        while True:
            pode, motivo, liberado = avalia_limites(cfg, virtual, relogio)
            if pode:
                break
            if liberado is None or liberado > fim_do_dia:
                ficariam.append((item, motivo))
                break
            # o relogio sempre anda: sem isto um liberado no passado travaria o laco
            relogio = max(liberado, relogio + timedelta(seconds=1))
        if not pode:
            continue
        sairiam.append((item, relogio))
        virtual["alertas"][item["alert_id"]] = {
            "resultado": "enviado",
            "enviado_em": relogio.isoformat(),
        }
        relogio = relogio + timedelta(minutes=limites["espacamento_min"])
    return sairiam, ficariam


# --------------------------------------------------------------------------
# WAHA (uso do endpoint existente; nunca reinicia, nunca reconfigura)
# --------------------------------------------------------------------------
def waha_request(cfg: dict, caminho: str, metodo: str = "GET", corpo: dict | None = None):
    waha = cfg["waha"]
    url = waha["base_url"].rstrip("/") + caminho
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo)
    if dados is not None:
        req.add_header("Content-Type", "application/json")
    chave = os.environ.get(waha.get("api_key_env") or "", "")
    if chave:
        req.add_header("X-Api-Key", chave)
    with urllib.request.urlopen(req, timeout=waha["timeout_s"]) as resp:
        texto = resp.read().decode("utf-8", "replace")
    try:
        return resp.status, json.loads(texto)
    except json.JSONDecodeError:
        return resp.status, texto


def waha_envia(cfg: dict, chat_id: str, texto: str) -> tuple[str, int | None, str]:
    """
    (resultado, status_http, detalhe)
      enviado  -> WAHA aceitou
      falhou   -> nao chegou / recusado; pode tentar de novo na proxima janela
      incerto  -> a requisicao saiu mas nao houve resposta: NAO reenviar sozinho

    Quando `transporte` e "hermes", o envio sai pelo bridge.js do Hermes, que ja
    tem sessao pareada nesta maquina. O texto vai igual nos dois caminhos: o
    transporte muda, o conteudo nunca.
    """
    if (cfg.get("transporte") or "waha") == "hermes":
        import hermes

        conf = cfg.get("hermes") or {}
        api = {"rotas": conf.get("rotas") or [],
               "cabecalho_auth": conf.get("cabecalho_auth"),
               "envio": conf.get("envio") or {}}
        return hermes.envia(
            conf.get("base_url") or hermes.BASE_PADRAO, api, chat_id, texto,
            chave=os.environ.get(conf.get("api_key_env") or "") or None,
            timeout=conf.get("timeout_s", 30),
        )

    waha = cfg["waha"]
    url = waha["base_url"].rstrip("/") + waha["send_path"]
    payload = {"session": waha["session"], "chatId": chat_id, "text": texto}
    dados = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=dados, method="POST")
    req.add_header("Content-Type", "application/json")
    chave = os.environ.get(waha.get("api_key_env") or "", "")
    if chave:
        req.add_header("X-Api-Key", chave)
    try:
        with urllib.request.urlopen(req, timeout=waha["timeout_s"]) as resp:
            corpo = resp.read(2000).decode("utf-8", "replace")
            return "enviado", resp.status, corpo[:400]
    except urllib.error.HTTPError as erro:
        corpo = erro.read(2000).decode("utf-8", "replace")
        return "falhou", erro.code, corpo[:400]
    except urllib.error.URLError as erro:
        motivo = erro.reason
        if isinstance(motivo, (socket.timeout, TimeoutError)):
            return "incerto", None, f"timeout: {motivo}"
        return "falhou", None, f"sem conexao: {motivo}"
    except (socket.timeout, TimeoutError) as erro:
        return "incerto", None, f"timeout: {erro}"
    except OSError as erro:
        return "falhou", None, f"erro de rede: {erro}"


def extrai_id(valor) -> str | None:
    """WAHA devolve id ora como string, ora como objeto {_serialized: ...}."""
    if isinstance(valor, str):
        return valor
    if isinstance(valor, dict):
        for chave in ("_serialized", "id", "user"):
            achado = valor.get(chave)
            if isinstance(achado, str):
                return achado
    return None


def extrai_nome(entrada: dict) -> str | None:
    for chave in ("name", "subject", "formattedTitle", "title"):
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


def extrai_participantes(entrada: dict):
    for fonte in (entrada, entrada.get("groupMetadata") or {}):
        if isinstance(fonte, dict):
            participantes = fonte.get("participants")
            if isinstance(participantes, list):
                return participantes
    return None


# --------------------------------------------------------------------------
# preparo comum
# --------------------------------------------------------------------------
def prepara(cfg: dict, *, atualizar: bool = True, escrever: bool = True):
    """Retorna (fila_pendente, estatisticas, enviados, seed_feito)."""
    garante_repo(cfg)
    if atualizar:
        atualiza_repo(cfg)
    aprovados, estat = coleta_aprovados(cfg)

    enviados = carrega_enviados()
    primeira_vez = enviados is None
    if primeira_vez:
        enviados = {"criado_em": agora_local().isoformat(), "alertas": {}}

    conhecidos = enviados["alertas"]
    pendentes = [i for i in aprovados if i["alert_id"] not in conhecidos]
    pendentes = ordena_fila(pendentes)

    seed_feito = False
    if primeira_vez:
        # Regra do briefing: se enviados.json sumir, tudo o que ja esta na fila
        # conta como enviado. Isso impede que a primeira execucao dispare o
        # historico inteiro de uma vez.
        for item in pendentes:
            conhecidos[item["alert_id"]] = {
                "resultado": "seed",
                "enviado_em": None,
                "registrado_em": agora_local().isoformat(),
            }
        seed_feito = True
        if escrever:
            grava_enviados(enviados)
            registra_log({"evento": "seed", "quantidade": len(pendentes)})
        pendentes = []

    return pendentes, estat, enviados, seed_feito


def imprime_alerta(item: dict, indice: int | None = None) -> None:
    cabecalho = f"[{indice}] " if indice is not None else ""
    idade = agora_local() - item["recorded_at"].astimezone(TZ)
    horas = idade.total_seconds() / 3600
    print(f"{cabecalho}alert_id={item['alert_id']}  prioridade={item['priority']}  "
          f"revisao={item['revision_type']}  idade={horas:.1f}h  "
          f"caracteres={len(item['text'])}")
    print("---8<--- texto exato que sairia ---8<---")
    print(item["text"])
    print("---8<--------------------------------8<---")


# --------------------------------------------------------------------------
# comandos
# --------------------------------------------------------------------------
def cmd_status(cfg: dict, args) -> int:
    print("== ponte TrackNews -> AutoPilot News ==")
    print(f"diretorio        : {HOME}")
    print(f"envio habilitado : {cfg['envio_habilitado']}")
    print(f"kill switch      : {'ATIVO (PAUSED existe)' if PAUSED_PATH.exists() else 'inativo'}")
    print(f"WAHA             : {cfg['waha']['base_url']}  sessao={cfg['waha']['session']}  "
          f"envio={cfg['waha']['send_path']}")
    print(f"chave de API     : variavel {cfg['waha']['api_key_env']} "
          f"({'definida' if os.environ.get(cfg['waha']['api_key_env'] or '') else 'ausente'})")
    print(f"destino          : grupo \"{cfg['destino']['nome_grupo']}\" "
          f"{mascara(cfg['destino']['chat_id'])}")
    lim = cfg["limites"]
    print(f"limites          : <= {lim['por_hora']}/hora, <= {lim['por_dia']}/dia, "
          f">= {lim['espacamento_min']} min entre mensagens, "
          f"silencio {lim['silencio_inicio']}-{lim['silencio_fim']} America/Sao_Paulo")

    enviados = carrega_enviados()
    if enviados is None:
        print("enviados.json    : ausente (a proxima execucao apenas semeia o historico)")
    else:
        historico = historico_envios(enviados)
        agora = agora_local()
        hoje = [t for t in historico if t.date() == agora.date()]
        hora = [t for t in historico if agora - t < timedelta(hours=1)]
        incertos = [k for k, v in (enviados.get("alertas") or {}).items()
                    if v.get("resultado") == "incerto"]
        print(f"enviados.json    : {len(enviados.get('alertas') or {})} alert_id conhecidos; "
              f"{len(historico)} entregues no total")
        print(f"contadores       : {len(hoje)} hoje, {len(hora)} na ultima hora"
              + (f"; {len(incertos)} INCERTOS aguardando decisao" if incertos else ""))
        if historico:
            print(f"ultima entrega   : {historico[-1].isoformat()}")

    if not args.sem_fila:
        try:
            fila, estat, _, seed = prepara(cfg, escrever=False)
        except subprocess.CalledProcessError as erro:
            print(f"\nrepo de estado indisponivel: {erro.stderr.strip()[:200]}")
            return 1
        print(f"\narquivos lidos   : {', '.join(estat['arquivos']) or 'nenhum'}")
        print(f"linhas           : {estat['linhas']} "
              f"({estat['com_alerta']} com alerta, {estat['aprovados']} aprovados, "
              f"{estat['segurados']} segurados pela nuvem, {estat['bloqueados']} bloqueados)")
        if seed:
            print(f"fila             : {estat['aprovados']} aprovados seriam semeados "
                  "(marcados como ja entregues) na proxima execucao real")
        else:
            print(f"fila pendente    : {len(fila)}")
    return 0


def cmd_waha(cfg: dict, args) -> int:
    """Reconhecimento SOMENTE LEITURA. Nao reinicia, nao repara, nao repareia."""
    print("== WAHA (somente leitura) ==")
    try:
        status, sessoes = waha_request(cfg, "/api/sessions")
    except urllib.error.HTTPError as erro:
        print(f"GET /api/sessions -> HTTP {erro.code}. "
              "Se for 401/403, defina a chave em ~/.config/tracknews-bridge/.env")
        return 1
    except (urllib.error.URLError, OSError) as erro:
        print(f"WAHA nao respondeu em {cfg['waha']['base_url']}: {erro}")
        print("PARANDO. Regra 2: nao subir, nao reiniciar, nao reconfigurar o WAHA.")
        return 1

    alvo = None
    if isinstance(sessoes, list):
        for sessao in sessoes:
            nome = sessao.get("name") if isinstance(sessao, dict) else None
            estado = sessao.get("status") if isinstance(sessao, dict) else None
            print(f"  sessao: {nome}  status: {estado}")
            if nome == cfg["waha"]["session"]:
                alvo = estado
    if alvo != "WORKING":
        print(f"\nsessao \"{cfg['waha']['session']}\" nao esta WORKING (status={alvo}).")
        print("PARANDO. Nada de reparear nem escanear QR.")
        return 1

    sessao = urllib.parse.quote(cfg["waha"]["session"])
    grupos, usado = None, None
    for caminho in (f"/api/{sessao}/groups",
                    f"/api/{sessao}/chats?limit=1000",
                    f"/api/{sessao}/chats/overview?limit=1000"):
        try:
            _, dados = waha_request(cfg, caminho)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            continue
        if isinstance(dados, list):
            grupos, usado = dados, caminho.split("?")[0]
            break
    if grupos is None:
        print("nao consegui listar grupos por nenhum endpoint conhecido.")
        return 1

    apenas_grupos = [g for g in grupos if isinstance(g, dict)
                     and (extrai_id(g.get("id")) or "").endswith("@g.us")]
    print(f"\nlistagem via {usado}: {len(grupos)} chats, {len(apenas_grupos)} grupos")

    procurado = cfg["destino"]["nome_grupo"].strip().casefold()
    achados = [g for g in apenas_grupos if (extrai_nome(g) or "").strip().casefold() == procurado]
    if not achados:
        print(f"grupo \"{cfg['destino']['nome_grupo']}\" NAO encontrado. Nada foi gravado.")
        return 1
    if len(achados) > 1:
        print(f"ATENCAO: {len(achados)} grupos com esse nome exato. Nada foi gravado.")
        return 1

    grupo = achados[0]
    chat_id = extrai_id(grupo.get("id"))
    participantes = extrai_participantes(grupo)
    if participantes is None:
        try:
            _, dados = waha_request(
                cfg, f"/api/{sessao}/groups/{urllib.parse.quote(chat_id)}/participants")
            if isinstance(dados, list):
                participantes = dados
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            participantes = None

    esperado = cfg["destino"]["participantes_esperados"]
    if participantes is None:
        print("participantes: nao foi possivel contar por este endpoint.")
    else:
        print(f"participantes: {len(participantes)} (esperado: {esperado})")
        if len(participantes) != esperado:
            print("ATENCAO: contagem diferente do esperado. Confira antes de liberar o envio.")

    cfg["destino"]["chat_id"] = chat_id
    grava_config(cfg)
    print(f"\nid do grupo: gravado em {CONFIG_PATH} (modo 600). Rotulo: {mascara(chat_id)}")
    print("Fila/rate limit do WAHA: nao sao expostos pela API; use recon-antigo.sh,")
    print("que lista os NOMES das variaveis de ambiente do container, sem valores.")
    return 0


def cmd_hermes(cfg: dict, args) -> int:
    """
    Reconhecimento SOMENTE LEITURA do bridge.js do Hermes + gravacao do destino.

    Nao inicia, nao reinicia, nao reconfigura o Hermes, nao pareia e nao escaneia
    QR: le o fonte do bridge para deduzir a API e faz GET para listar os grupos.
    """
    import hermes

    base = args.base_url or (cfg.get("hermes") or {}).get("base_url") or hermes.BASE_PADRAO
    print("== Hermes (somente leitura) ==")

    estado = hermes.saude(base)
    if not estado:
        print(f"o bridge do Hermes nao respondeu /health em {base}.")
        print("PARANDO. Nao subo, nao reinicio e nao reconfiguro o Hermes.")
        return 1
    print(f"  bridge     : {base}")
    print(f"  status     : {estado.get('status')}  fila: {estado.get('queueLength')}")
    if str(estado.get("status", "")).lower() not in ("connected", "open", "ready"):
        print("\nsessao do WhatsApp nao esta conectada. PARANDO: nada de reparear nem QR.")
        return 1

    api = hermes.descobre(base)
    fonte = api.get("arquivo")
    print(f"  fonte lido : {fonte or '(bridge.js nao encontrado; uso convencoes conhecidas)'}")
    print(f"  rotas      : {len(api.get('rotas') or [])}")
    envio = api.get("envio") or {}
    if envio.get("rota"):
        print(f"  envio      : POST {envio['rota']} "
              f"({envio['campo_destino']}/{envio['campo_texto']})")
    else:
        print("  envio      : nao deduzido do fonte; vou tentar as convencoes conhecidas")
    if api.get("cabecalho_auth"):
        print(f"  autentica  : cabecalho {api['cabecalho_auth']}")

    chave = os.environ.get((cfg.get("hermes") or {}).get("api_key_env") or "HERMES_API_KEY") or None
    chat_id, rota, erro = hermes.acha_grupo(base, api, cfg["destino"]["nome_grupo"], chave)
    if erro:
        print(f"\n{erro}")
        print("Nada foi gravado. PARANDO: nenhum outro destino.")
        return 1
    print(f"  grupos via : GET {rota}")

    cfg["transporte"] = "hermes"
    cfg["hermes"] = {
        "base_url": base,
        "api_key_env": (cfg.get("hermes") or {}).get("api_key_env") or "HERMES_API_KEY",
        "cabecalho_auth": api.get("cabecalho_auth"),
        "envio": envio,
        "timeout_s": 30,
    }
    cfg["destino"]["chat_id"] = chat_id
    grava_config(cfg)
    print(f"\ntransporte = hermes; id do grupo gravado em {CONFIG_PATH} (modo 600).")
    print(f"Rotulo do destino: {mascara(chat_id)}")
    print("O texto do alerta continua vindo pronto da nuvem: o Hermes so transporta.")
    return 0


def cmd_dry_run(cfg: dict, args) -> int:
    agora = agora_local()
    print(f"== DRY-RUN {agora.isoformat()} (America/Sao_Paulo) ==")
    print("Nenhuma mensagem sai daqui. Nenhum estado e gravado.\n")
    try:
        fila, estat, enviados, seed = prepara(cfg, escrever=False)
    except subprocess.CalledProcessError as erro:
        print(f"repo de estado indisponivel: {erro.stderr.strip()[:300]}")
        return 1

    print(f"arquivos lidos : {', '.join(estat['arquivos']) or 'nenhum'}")
    print(f"linhas do dia  : {estat['linhas']}")
    print(f"  sem alerta (bloqueados pela nuvem) : {estat['bloqueados']}")
    print(f"  alertas segurados (hold)           : {estat['segurados']}")
    print(f"  alertas aprovados (gate.allowed)   : {estat['aprovados']}")
    if estat["invalidas"]:
        print(f"  linhas invalidas ignoradas         : {estat['invalidas']}")

    if seed:
        print("\nenviados.json ausente: a primeira execucao real vai SEMEAR "
              f"{estat['aprovados']} alert_id como ja entregues e nao enviar nada.")
        print("Isso e proposital: evita despejar o historico no grupo.")
        return 0

    print(f"\nfila pendente  : {len(fila)}")
    if not fila:
        print("nada a entregar agora.")
        return 0

    for indice, item in enumerate(fila, 1):
        print()
        imprime_alerta(item, indice)

    sairiam, ficariam = simula_limites(cfg, fila, enviados, agora)
    print("\n== simulacao dos limites ==")
    pode, motivo, liberado = avalia_limites(cfg, enviados, agora)
    print(f"agora: {'liberado' if pode else 'bloqueado -> ' + motivo}"
          + (f" (libera {liberado.isoformat()})" if liberado else ""))
    print(f"sairiam ainda hoje : {len(sairiam)}")
    for item, quando in sairiam:
        print(f"   {quando.strftime('%H:%M')}  {item['alert_id']}  {item['text'].splitlines()[0][:70]}")
    print(f"ficariam na fila   : {len(ficariam)}")
    for item, motivo_item in ficariam:
        print(f"   ---     {item['alert_id']}  ({motivo_item})")
    if ficariam:
        print("Fila nao descarta: o que sobra sai na proxima janela.")
    return 0


def entrega(cfg: dict, item: dict, enviados: dict, *, rotulo: str) -> tuple[str, int | None]:
    chat_id = cfg["destino"]["chat_id"]
    texto = item["text"]
    assinatura = hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]
    resultado, status, detalhe = waha_envia(cfg, chat_id, texto)
    registro = {
        "resultado": resultado,
        "enviado_em": agora_local().isoformat() if resultado == "enviado" else None,
        "registrado_em": agora_local().isoformat(),
        "revisao": item["revision_type"],
        "sha_texto": assinatura,
        "modo": rotulo,
    }
    if resultado in ("enviado", "incerto"):
        # 'incerto' tambem entra no historico: a mensagem pode ter chegado.
        # Nunca reenviamos sozinhos; a decisao e do Douglas.
        enviados["alertas"][item["alert_id"]] = registro
        grava_enviados(enviados)
    registra_log({
        "evento": "envio",
        "alert_id": item["alert_id"],
        "resultado": resultado,
        "http": status,
        "destino": mascara(chat_id),
        "sha_texto": assinatura,
        "modo": rotulo,
        "detalhe": detalhe if resultado != "enviado" else "",
    })
    return resultado, status


def valida_destino(cfg: dict) -> str | None:
    if not cfg["destino"]["chat_id"]:
        return ("destino nao configurado: rode `bridge.py waha` para localizar e gravar "
                "o id do grupo AutoPilot News.")
    if not str(cfg["destino"]["chat_id"]).endswith("@g.us"):
        return "o chat id gravado nao e de grupo (@g.us). PARANDO: nenhum outro destino."
    return None


def cmd_run(cfg: dict, args) -> int:
    agora = agora_local()
    if PAUSED_PATH.exists():
        registra_log({"evento": "pulado", "motivo": "PAUSED"})
        print("kill switch ativo (PAUSED). Nada enviado.")
        return 0
    if not cfg["envio_habilitado"]:
        print("envio_habilitado=false em config.json. Nada enviado.")
        return 0
    problema = valida_destino(cfg)
    if problema:
        print(problema)
        return 1

    try:
        fila, _, enviados, seed = prepara(cfg)
    except subprocess.CalledProcessError as erro:
        registra_log({"evento": "erro", "onde": "git", "detalhe": erro.stderr.strip()[:200]})
        print(f"repo de estado indisponivel: {erro.stderr.strip()[:200]}")
        return 1
    if seed:
        print("historico semeado na primeira execucao; nada enviado.")
        return 0
    if not fila:
        return 0

    maximo = args.ate or cfg["limites"]["max_por_execucao"]
    entregues = 0
    for item in fila:
        if entregues >= maximo:
            break
        pode, motivo, liberado = avalia_limites(cfg, enviados, agora_local())
        if not pode:
            registra_log({"evento": "retido", "alert_id": item["alert_id"], "motivo": motivo})
            print(f"retido: {motivo}. {len(fila)} na fila."
                  + (f" Libera {liberado.isoformat()}." if liberado else ""))
            return 0
        resultado, status = entrega(cfg, item, enviados, rotulo="run")
        print(f"{item['alert_id']}: {resultado}" + (f" (HTTP {status})" if status else ""))
        if resultado == "enviado":
            entregues += 1
        elif resultado == "incerto":
            print("resposta incerta: NAO vou reenviar sozinho. Confira o grupo.")
            return 1
        else:
            print("falha na entrega; fica na fila para a proxima janela.")
            return 1
    return 0


def cmd_test_send(cfg: dict, args) -> int:
    if not args.confirmo:
        print("Envio de teste exige --confirmo (autorizacao explicita do Douglas).")
        return 2
    problema = valida_destino(cfg)
    if problema:
        print(problema)
        return 1
    if PAUSED_PATH.exists():
        print("kill switch ativo (PAUSED). Remova o arquivo antes do teste.")
        return 1

    try:
        fila, _, enviados, seed = prepara(cfg)
    except subprocess.CalledProcessError as erro:
        print(f"repo de estado indisponivel: {erro.stderr.strip()[:200]}")
        return 1

    escolhido = None
    if args.alert_id:
        aprovados, _ = coleta_aprovados(cfg)
        for item in aprovados:
            if item["alert_id"] == args.alert_id:
                escolhido = item
                break
        if escolhido is None:
            print(f"alert_id {args.alert_id} nao esta entre os aprovados da janela.")
            return 1
    elif fila:
        escolhido = fila[0]
    else:
        print("fila vazia. Use --alert-id <id> para escolher um alerta aprovado da janela.")
        return 1

    agora = agora_local()
    if em_silencio(cfg, agora) and not args.ignorar_silencio:
        print(f"janela de silencio ({cfg['limites']['silencio_inicio']}-"
              f"{cfg['limites']['silencio_fim']}). Use --ignorar-silencio para testar mesmo assim.")
        return 1

    print("Vai sair exatamente isto, uma unica mensagem:")
    imprime_alerta(escolhido)
    resultado, status = entrega(cfg, escolhido, enviados, rotulo="teste")
    print(f"\nresultado: {resultado}" + (f" (HTTP {status})" if status else ""))
    if resultado != "enviado":
        print("PARANDO. Nao vou tentar outro destino nem outro endpoint.")
        return 1
    return 0


def cmd_seed(cfg: dict, args) -> int:
    if ENVIADOS_PATH.is_file() and not args.forcar:
        print("enviados.json ja existe; use --forcar para semear de novo.")
        return 1
    if ENVIADOS_PATH.is_file():
        ENVIADOS_PATH.unlink()
    _, estat, _, _ = prepara(cfg)
    print(f"semeado: {estat['aprovados']} alert_id marcados como ja entregues.")
    return 0


def main() -> int:
    carrega_env()
    cfg = carrega_config()

    parser = argparse.ArgumentParser(description="Ponte TrackNews -> WAHA (AutoPilot News)")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("status", help="estado da ponte")
    p.add_argument("--sem-fila", action="store_true", help="nao consulta o repo de estado")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("waha", help="reconhecimento somente leitura do WAHA")
    p.set_defaults(func=cmd_waha)

    p = sub.add_parser("hermes", help="reconhecimento somente leitura do bridge do Hermes")
    p.add_argument("--base-url", default=None, help="padrao: http://localhost:3000")
    p.set_defaults(func=cmd_hermes)

    p = sub.add_parser("dry-run", help="o que sairia agora, sem enviar nada")
    p.set_defaults(func=cmd_dry_run)

    p = sub.add_parser("run", help="modo real (usado pelo timer)")
    p.add_argument("--ate", type=int, default=None, help="maximo de mensagens nesta execucao")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("test-send", help="um unico envio de teste")
    p.add_argument("--confirmo", action="store_true", required=False)
    p.add_argument("--alert-id", default=None)
    p.add_argument("--ignorar-silencio", action="store_true")
    p.set_defaults(func=cmd_test_send)

    p = sub.add_parser("seed", help="marca a fila atual como ja entregue")
    p.add_argument("--forcar", action="store_true")
    p.set_defaults(func=cmd_seed)

    args = parser.parse_args()
    HOME.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(HOME, 0o700)
    except OSError:
        pass
    if args.comando in ("run", "test-send", "seed"):
        if not trava_execucao():
            print("outra execucao da ponte ja esta em andamento; nada feito.")
            registra_log({"evento": "pulado", "motivo": "lock"})
            return 0
    return args.func(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
