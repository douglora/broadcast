"""
Liga no MetaTrader o leitor de negocios (AutopilotFeed 1.3), confere a fita e, so se ela
estiver chegando com o lado agressor, troca o robo de day trade para a regra de leitura de
fluxo (`"regra": "fluxo"` em quant/saida/modo_robo.json).

POR QUE EXISTE. A regra de fluxo depende de um arquivo que so a versao 1.3 do robo do
MetaTrader grava. Trocar esse robo mexe na fonte das cotacoes do terminal, entao so se faz
com o pregao regular fechado (depois das 18h; os futuros ainda negociam ate 18h25, o que da
para conferir a fita). Este roteiro faz a troca inteira e desfaz sozinho se algo falhar.

O QUE FAZ, na ordem:
  1. descobre o contrato vigente do mini-dolar e do mini-indice no motor do terminal;
  2. pede a fita do mini e do contrato cheio (autopilot_tape.txt);
  3. guarda uma copia do robo em uso (AutopilotFeed_antes_da_1.3.*) e compila a 1.3 no lugar;
  4. espera o MetaTrader recarregar o robo; se nao recarregar, fecha e abre o MetaTrader;
  5. confere a fita: tem linha do mini-dolar? o lado agressor vem preenchido? o cheio chega?
  6. se sim, grava "regra": "fluxo" e pede as barras de 1 minuto para o teste historico;
     se nao, volta o robo antigo e deixa o modo como estava.

Com a 1.3 ja instalada, rodar de novo so confere a fita e liga a regra: isso pode a qualquer hora.

Uso:  python -m quant.daytrade.ligar_fita            (faz; recusa trocar o robo antes das 18h)
      python -m quant.daytrade.ligar_fita --ensaio   (so mostra o que faria; nao grava nada)
      python -m quant.daytrade.ligar_fita --voltar   (volta o robo antigo do MetaTrader e a regra antiga)
Sai com 0 se a regra de fluxo ficou ligada, 1 se desfez, 2 se recusou.
"""
import argparse
import filecmp
import json
import os
import threading
import re
import shutil
import subprocess
import sys
import time

from quant.comum import agora_brt, garantir_dir, gravar_atomico, ler_json, log
from quant.daytrade import estrategia_fluxo as ef
from quant.daytrade import fluxo as fx
from quant.daytrade.robo import ATIVOS, DIR_DT, MOTOR, ler_motor
from quant.daytrade.robo_fluxo import codigo_da_fonte
from quant.robo import ARQ_MODO

MT5 = os.path.dirname(os.path.dirname(fx.PASTA_MT5))                  # .../MetaTrader 5
EXPERTS = os.path.join(MT5, "MQL5", "Experts")
PREFIXO_WINE = os.path.dirname(os.path.dirname(os.path.dirname(MT5)))  # .../net.metaquotes.wine.metatrader5
WINE = "/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine"
FONTE_13 = os.path.expanduser(os.environ.get("QUANT_EA_13", "~/Desktop/terminal-artefato/ferramentas/mt5/AutopilotFeed13.mq5"))
EM_USO = "AutopilotFeed"
COPIA = "AutopilotFeed_antes_da_1.3"
MARCA_13 = "AutopilotFeed 1.3: ligado"
HORA_MINIMA = "18:00"


def _registro_mt5(dia):
    arq = os.path.join(MT5, "MQL5", "Logs", f"{dia}.log")
    try:
        with open(arq, "rb") as f:
            return f.read().decode("utf-16-le", errors="ignore")
    except OSError:
        return ""


def _ligou_13(dia, depois_de):
    """A linha de inicio da 1.3 apareceu no registro do MetaTrader depois do instante `depois_de` (HH:MM:SS)?"""
    for ln in _registro_mt5(dia).splitlines():
        if MARCA_13 in ln:
            partes = ln.split("\t")
            if len(partes) > 2 and partes[2][:8] >= depois_de:
                return True
    return False


def _compilar(nome):
    env = dict(os.environ, WINEPREFIX=PREFIXO_WINE, WINEDEBUG="-all")
    try:
        subprocess.run([WINE, "metaeditor64.exe", f"/compile:MQL5\\Experts\\{nome}.mq5", f"/log:MQL5\\Experts\\{nome}.log"],
                       cwd=MT5, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"{type(e).__name__}: {e}"
    try:
        with open(os.path.join(EXPERTS, f"{nome}.log"), "rb") as f:
            texto = f.read().decode("utf-16-le", errors="ignore")
    except OSError:
        return False, "sem registro da compilacao"
    fim = next((ln.strip() for ln in reversed(texto.splitlines()) if "Result" in ln or "error" in ln.lower()), "")
    return "0 errors" in fim, fim


PADRAO_XP = r"MetaTrader 5\\terminal64\.exe"                          # a instancia da XP (pasta "MetaTrader 5")
PADRAO_SEGUNDA = r"Global\\terminal64\.exe|terminal64\.exe /portable"   # a segunda instancia (MetaQuotes Global), que o vigia sobe


def _pids(padrao):
    r = subprocess.run(["pgrep", "-f", padrao], capture_output=True, text=True)
    return [int(x) for x in str(r.stdout or "").split() if x.strip().isdigit()] if r.returncode == 0 else []


def _frente():
    """(bundle id, nome) do aplicativo na frente da tela, pelo lsappinfo (nao pede permissao ao macOS). As janelas do MetaTrader aparecem
    como "wine", sem bundle id."""
    try:
        asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, timeout=5).stdout.strip()
        info = subprocess.run(["lsappinfo", "info", "-only", "bundleid", "-only", "name", asn], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None, None
    b = re.search(r'"CFBundleIdentifier"="([^"]+)"', info)
    n = re.search(r'"LSDisplayName"="([^"]+)"', info)
    return (b.group(1) if b else None), (n.group(1) if n else None)


def _eh_metatrader(bundle, nome):
    return (bundle or "").startswith("net.metaquotes") or (nome or "").lower() in ("wine", "wine64-preloader", "metatrader 5", "terminal64.exe")


def devolver_foco(bundle, segundos=120.0):
    """22/10/2026 ("o MT5 fica abrindo toda hora na minha tela"): a janela do MetaTrader (Wine) toma a frente da tela ao abrir, mesmo com
    `open -g`. Durante `segundos` depois de uma reabertura (a XP e, ~10 s depois, a segunda instancia que o vigia sobe), sempre que o
    MetaTrader estiver na frente, a frente volta para o aplicativo `bundle` (o que estava na frente antes). Sem `bundle`, nada."""
    if not bundle or _eh_metatrader(bundle, None):
        return
    fim = time.time() + segundos
    while time.time() < fim:
        b, n = _frente()
        if _eh_metatrader(b, n):
            subprocess.run(["open", "-b", bundle], capture_output=True, timeout=10)
        time.sleep(0.5)


def _reabrir_metatrader(log=None):
    """Fecha e reabre o MetaTrader da XP. 14/10/2026: na 4a reabertura do dia a XP nao voltou e a B3 ficou sem tempo real das
    11h52 ate o fim do pregao. Causa: a segunda instancia (Global) tinha ficado orfa de um wineserver que ja saiu; a espera por
    "nenhum terminal64.exe" estourava sempre e, com ela viva, o `open` nao sobe a XP. Agora: espera SO pelo processo da XP; uma
    segunda instancia que sobrou sem a XP e encerrada pelo pid (nunca `taskkill /im`, que leva a XP junto); depois do `open`
    confere em ate 60 s que a XP voltou e tenta uma segunda vez, registrando no log. Devolve True se a XP esta de pe."""
    anota = log or (lambda m: None)
    antes, _ = _frente()                                      # quem estava na frente da tela volta para a frente quando o MetaTrader abrir
    if antes and not _eh_metatrader(antes, None):
        threading.Thread(target=devolver_foco, args=(antes, 150.0), daemon=True).start()
    subprocess.run(["osascript", "-e", 'tell application "MetaTrader 5" to quit'], capture_output=True, timeout=30)
    for _ in range(30):
        if not _pids(PADRAO_XP):
            break
        time.sleep(1.0)
    if not _pids(PADRAO_XP):
        for pid in _pids(PADRAO_SEGUNDA):                     # sobrou so a segunda: orfa, segura o aplicativo aberto sem a XP
            try:
                os.kill(pid, 15)
                anota(f"MetaTrader: segunda instância órfã encerrada (pid {pid}) para a XP poder reabrir")
            except (ProcessLookupError, PermissionError):
                pass
    time.sleep(2.0)
    for tentativa in (1, 2):
        subprocess.run(["open", "-g", "-a", "MetaTrader 5"], capture_output=True, timeout=30)
        for _ in range(30):
            time.sleep(2.0)
            if _pids(PADRAO_XP):
                return True
        anota(f"MetaTrader da XP não voltou em 60 s depois do open (tentativa {tentativa} de 2)")
    return False


def _esperar(condicao, segundos, passo=2.0):
    fim = time.time() + segundos
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(passo)
    return condicao()


def contratos(motor=MOTOR):
    """{WDOFUT: WDOX26, WINFUT: WINV26} pelo motor do terminal."""
    fora = {}
    for a in ATIVOS:
        s = ler_motor(f"/vivo/intradia?s={a}&dias=1", motor, timeout=8.0) or {}
        if s.get("codigo"):
            fora[a] = str(s["codigo"])
    return fora


def simbolos_da_fita(cods):
    """O mini, o contrato onde a regra le o fluxo e, para medir, o cheio dos dois."""
    s = set(cods.values()) | {codigo_da_fonte(a, c) for a, c in cods.items()}
    for a, c in cods.items():
        s.add({"WDO": "DOL", "WIN": "IND"}.get(c[:3], c[:3]) + c[3:])
    return sorted(s)


def medir_fita(arquivo, desde_byte=0):
    """Por simbolo: linhas, volume de compra, de venda e sem lado, e se a linha traz o tamanho do negocio."""
    fora = {}
    try:
        with open(arquivo, "r", encoding="latin-1", errors="ignore") as f:
            f.seek(desde_byte)
            for ln in f:
                x = fx.linha_da_fita(ln)
                if x is None:
                    continue
                d = fora.setdefault(x["simbolo"], {"linhas": 0, "compra": 0.0, "venda": 0.0, "sem_lado": 0.0, "com_tamanho": 0})
                d["linhas"] += 1
                d["compra"] += x["compra"]
                d["venda"] += x["venda"]
                d["sem_lado"] += x["indef"]
                d["com_tamanho"] += 1 if "compra_media" in x else 0
    except OSError:
        pass
    for d in fora.values():
        total = d["compra"] + d["venda"] + d["sem_lado"]
        d["com_lado"] = round((d["compra"] + d["venda"]) / total, 4) if total > 0 else None
    return fora


def instalada():
    """A 1.3 ja esta no lugar do robo em uso (mesmo codigo, com a copia do antigo guardada)?"""
    em_uso = os.path.join(EXPERTS, EM_USO + ".mq5")
    try:
        return os.path.exists(os.path.join(EXPERTS, COPIA + ".ex5")) and filecmp.cmp(FONTE_13, em_uso, shallow=False)
    except OSError:
        return False


def _modo(regra):
    m = ler_json(ARQ_MODO, padrao=None) or {}
    if regra:
        m.update(regra=regra, regra_desde=agora_brt().isoformat(timespec="seconds"))
    else:
        m.pop("regra", None)
        m.pop("regra_desde", None)
    gravar_atomico(ARQ_MODO, json.dumps(m, ensure_ascii=False))


def _voltar_robo_antigo():
    feito = False
    for ext in (".mq5", ".ex5"):
        origem = os.path.join(EXPERTS, COPIA + ext)
        if os.path.exists(origem):
            shutil.copy2(origem, os.path.join(EXPERTS, EM_USO + ext))
            feito = True
    return feito


def voltar():
    if not _voltar_robo_antigo():
        print("Nao ha copia do robo antigo (AutopilotFeed_antes_da_1.3): nada a voltar no MetaTrader.")
    else:
        _reabrir_metatrader()
        print("Robo antigo do MetaTrader de volta; MetaTrader reaberto.")
    _modo(None)
    print("Regra do robo de day trade: de volta a versao 0 (rompimento).")
    return 0


def ligar(ensaio=False, forcar_hora=False, motor=MOTOR, espera_fita_s=150):
    agora = agora_brt()
    dia, hm = agora.strftime("%Y%m%d"), agora.strftime("%H:%M")
    res = {"quando": agora.isoformat(timespec="seconds"), "ensaio": ensaio, "passos": []}

    def passo(nome, ok, detalhe=""):
        res["passos"].append({"passo": nome, "ok": bool(ok), "detalhe": detalhe})
        print(("ok    " if ok else "FALHA ") + nome + (": " + detalhe if detalhe else ""))
        return ok

    def fim(codigo, resumo):
        res.update(resultado=codigo, resumo=resumo)
        print("\n" + resumo)
        if not ensaio:
            garantir_dir(DIR_DT)
            gravar_atomico(os.path.join(DIR_DT, f"ligar_fita_{agora.strftime('%Y-%m-%d')}.json"), json.dumps(res, ensure_ascii=False, indent=1))
        return codigo

    ja_13 = instalada()
    if not ensaio and not forcar_hora and not ja_13 and (hm < HORA_MINIMA or agora.weekday() >= 5):
        return fim(2, f"Recusado: sao {hm}. A troca do robo do MetaTrader so se faz em dia util depois das {HORA_MINIMA}.")
    if not passo("fonte da versao 1.3", os.path.exists(FONTE_13), FONTE_13):
        return fim(2, "Recusado: nao achei o codigo da versao 1.3.")
    if not passo("robo em uso no MetaTrader", os.path.exists(os.path.join(EXPERTS, EM_USO + ".ex5")), EXPERTS):
        return fim(2, "Recusado: nao achei o robo em uso no MetaTrader.")
    cods = contratos(motor)
    if not passo("contratos vigentes", len(cods) == len(ATIVOS), json.dumps(cods)):
        return fim(2, "Recusado: o motor do terminal nao informou os contratos vigentes.")
    simbolos = simbolos_da_fita(cods)
    passo("simbolos da fita", True, ", ".join(simbolos))
    if ensaio:
        passo("versao 1.3 ja instalada", ja_13, "sim: so conferiria a fita" if ja_13 else "nao: seria compilada no lugar do robo em uso, com copia de seguranca")
        return fim(0, "Ensaio: nada foi gravado. No modo normal eu pediria a fita, trocaria o robo, conferiria e ligaria a regra de fluxo.")

    fx.Leitor(dia=dia).pedir(simbolos)
    arq_fita = fx.Leitor(dia=dia).arquivo_da_fita()
    inicio_byte = os.path.getsize(arq_fita) if os.path.exists(arq_fita) else 0
    if not ja_13:
        for ext in (".mq5", ".ex5"):                       # copia de seguranca, uma vez so
            destino = os.path.join(EXPERTS, COPIA + ext)
            if not os.path.exists(destino):
                shutil.copy2(os.path.join(EXPERTS, EM_USO + ext), destino)
        passo("copia do robo em uso", os.path.exists(os.path.join(EXPERTS, COPIA + ".ex5")), COPIA + ".ex5")
        marca_hora = agora_brt().strftime("%H:%M:%S")
        shutil.copy2(FONTE_13, os.path.join(EXPERTS, EM_USO + ".mq5"))
        ok, detalhe = _compilar(EM_USO)
        if not passo("compilacao da 1.3", ok, detalhe):
            _voltar_robo_antigo()
            return fim(1, "Desfeito: a versao 1.3 nao compilou. O robo antigo do MetaTrader foi posto de volta e a regra do robo nao mudou.")
        if not passo("MetaTrader recarregou o robo sozinho", _esperar(lambda: _ligou_13(dia, marca_hora), 30), ""):
            marca_hora = agora_brt().strftime("%H:%M:%S")
            _reabrir_metatrader()
            if not passo("MetaTrader reaberto com a 1.3", _esperar(lambda: _ligou_13(dia, marca_hora), 120), ""):
                _voltar_robo_antigo()
                _reabrir_metatrader()
                return fim(1, "Desfeito: a versao 1.3 nao subiu no MetaTrader. Voltei o robo antigo e reabri o MetaTrader; a regra do robo nao mudou.")

    def tem_fita():
        m = medir_fita(arq_fita, inicio_byte)
        return any(m.get(c, {}).get("linhas", 0) >= 5 for c in cods.values())
    chegou = _esperar(tem_fita, espera_fita_s, passo=5.0)
    medida = medir_fita(arq_fita, inicio_byte)
    res["fita"] = medida
    wdo, dol = medida.get(cods.get("WDOFUT", ""), {}), medida.get(codigo_da_fonte("WDOFUT", cods.get("WDOFUT", "")), {})
    passo("fita do mini-dolar chegando", chegou and wdo.get("linhas", 0) >= 5, json.dumps(wdo))
    passo("fita do dolar cheio chegando", dol.get("linhas", 0) >= 1, json.dumps(dol))
    lado_ok = wdo.get("com_lado") is not None and wdo["com_lado"] >= 0.8
    passo("lado agressor preenchido (mini-dolar)", lado_ok, f"{(wdo.get('com_lado') or 0) * 100:.0f}% do volume com lado")
    passo("tamanho do negocio na fita", wdo.get("com_tamanho", 0) > 0, "")
    livro = fx.Leitor(dia=dia).livro()
    passo("livro de ofertas", bool(livro), ", ".join(sorted(livro)) if livro else "foto vazia")
    saude = ler_motor("/vivo/saude", motor, timeout=4.0) or {}
    mt5 = next((f for f in (saude.get("fontes") or []) if f.get("id") == "mt5"), {})
    passo("cotacoes do terminal seguem chegando", mt5.get("estado") in ("ok", "vivo", "atrasado") or bool(mt5), str(mt5.get("estado")))

    if not (chegou and lado_ok):
        motivo = ("a fita nao chegou (os futuros podem ja ter fechado)" if not chegou
                  else "a fita chegou sem o lado agressor, e sem ele nao ha leitura de fluxo")
        return fim(1, f"A versao 1.3 ficou ligada no MetaTrader, mas NAO troquei a regra do robo: {motivo}. "
                      "Amanha ele segue na regra antiga; rode de novo com o pregao aberto para conferir.")
    regra_atual = (ler_json(ARQ_MODO, padrao=None) or {}).get("regra")
    if not regra_atual:                                      # regra escolhida pelo Douglas nao se troca aqui
        _modo("fluxo")
    try:                                                     # barras de 1 minuto para o teste historico
        with open(os.path.join(fx.PASTA_MT5, "autopilot_historia.txt"), "w", encoding="ascii") as f:
            f.write("WDO$N;1;150000\nWIN$N;1;150000\nDOL$N;1;150000\n")
        passo("pedido de barras de 1 minuto", True, "WDO$N, WIN$N, DOL$N")
    except OSError as e:
        passo("pedido de barras de 1 minuto", False, str(e))
    cheio = "com o dolar cheio" if dol.get("linhas", 0) >= 1 else "SEM o dolar cheio (o robo vai ler o mini e avisar)"
    regra_txt = (f"Regra '{regra_atual}' mantida (a fita esta pronta para ela)" if regra_atual
                 else "Regra de fluxo LIGADA para o proximo pregao")
    return fim(0, f"{regra_txt}, {cheio}. Fita do mini-dolar: {wdo.get('linhas')} linhas, "
                  f"{(wdo.get('com_lado') or 0) * 100:.0f}% do volume com lado agressor.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Liga a fita no MetaTrader e a regra de fluxo no robo de day trade")
    ap.add_argument("--ensaio", action="store_true")
    ap.add_argument("--voltar", action="store_true")
    ap.add_argument("--forcar-hora", action="store_true", help="aceita rodar antes das 18h (nao use com a bolsa aberta)")
    args = ap.parse_args(argv)
    if args.voltar:
        return voltar()
    return ligar(ensaio=args.ensaio, forcar_hora=args.forcar_hora)


if __name__ == "__main__":
    sys.exit(main())
