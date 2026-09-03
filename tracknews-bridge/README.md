# Ponte TrackNews -> AutoPilot News

Entrega no grupo "AutoPilot News" os alertas que a nuvem **já aprovou**. Nada mais.

A coleta, a validação de cada número contra a fonte, a relevância, a deduplicação e a
redação acontecem em `douglora/tracknews-autopilot` (GitHub Actions, 24/7). Esta ponte
só lê a fila do branch `state` e entrega pelo WAHA local, **sem tocar no texto**.

Para calibrar a expectativa: em 2026-08-29 o repositório de estado registrou 218 linhas —
215 itens bloqueados antes de virarem alerta, 2 alertas segurados pela própria nuvem e
**1 alerta aprovado**. É esse corte que resolve a poluição do fluxo antigo.

## O que a ponte nunca faz

- Não reescreve, resume, encurta, junta nem acrescenta emoji ao texto do alerta.
  O que sai é `alert.text` byte a byte — há teste automatizado provando isso.
- Não envia para nenhum destino que não seja o chat id gravado em `config.json`,
  e recusa qualquer id que não termine em `@g.us`.
- Não inicia, reinicia, repara nem reconfigura o WAHA. Só usa o endpoint de envio
  que já existe. Se o WAHA não responder, ela para e diz isso.
- Não pareia WhatsApp e não escaneia QR.
- Não toca em `autopilot-br` nem em `broadcast-terminal`.
- Não imprime tokens, chaves, telefones ou ids de chat. O id do grupo vira um rótulo
  estável (`id:<hash>`) nos logs e na tela.

## Instalar

**Caminho de um comando só** — cola isto no Ubuntu do WSL e ele faz tudo (instala,
agenda, configura o lado Windows via interop, localiza o grupo, liga o envio e faz o
único teste autorizado), terminando num resumo OK/PENDENTE:

```bash
curl -fsSL -o /tmp/tn.sh https://raw.githubusercontent.com/douglora/broadcast/claude/tracknews-bridge-autopilot-k3avgo/tracknews-bridge/bootstrap.sh && bash /tmp/tn.sh
```

Já com o repo em disco, o caminho curto é `bash ~/src/broadcast/tracknews-bridge/bootstrap.sh`
— ele atualiza o próprio repo antes de seguir.

É idempotente: rodar de novo não duplica nada e não repete o teste de envio.

**Caminho manual**, por partes:

```bash
bash install.sh              # instala em ~/tracknews-bridge, sem ligar o envio
bash install.sh --agendar    # o mesmo + agendamento de 10 em 10 minutos
```

O envio nasce **desligado** (`envio_habilitado: false`). Mesmo com o agendamento rodando,
nada sai até essa chave virar `true`.

`--agendar` escolhe sozinho conforme o sistema; dá para forçar com `--systemd`
(timer de usuário, Linux/WSL) ou `--launchd` (LaunchAgent `com.tracknews.bridge`, macOS).
Nenhuma unit, agente ou tarefa existente é tocada.

Sem systemd no WSL, use `windows/tracknews-bridge-task.xml` (Tarefa Agendada nova,
chamada "TrackNews Bridge" — nenhuma tarefa existente é tocada).

Com systemd, lembre do `sudo loginctl enable-linger $USER` para o timer sobreviver ao
logout e ao reinício da máquina.

## Ordem de uso

```bash
cd ~/tracknews-bridge
python3 bridge.py waha        # 1. acha o grupo, confere participantes, grava o id (só leitura)
python3 bridge.py dry-run     # 2. mostra o texto exato que sairia + simulação dos limites
python3 bridge.py test-send --confirmo   # 3. UM envio, só depois do "pode enviar"
```

Ligar o piloto automático depois do teste aprovado:

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / "tracknews-bridge/config.json"
c = json.loads(p.read_text()); c["envio_habilitado"] = True
p.write_text(json.dumps(c, ensure_ascii=False, indent=2)); p.chmod(0o600)
PY
```

## Comandos

| comando | o que faz |
|---|---|
| `status` | config sem segredos, contadores, tamanho da fila |
| `waha` | reconhecimento somente leitura do WAHA; localiza o grupo e grava o id |
| `dry-run` | o que sairia agora, texto completo, e a simulação dos limites. Não envia, não grava |
| `run` | modo real, usado pelo agendamento |
| `test-send --confirmo` | um único envio. `--alert-id <id>` escolhe qual |
| `seed` | marca a fila atual como já entregue, sem enviar |
| `autoteste.py` | 31 checagens das regras que não podem quebrar |

## Kill switch

```bash
touch ~/tracknews-bridge/PAUSED    # para tudo, na hora
rm    ~/tracknews-bridge/PAUSED    # volta
```

Vale para o `run` e para o `test-send`. A fila não é descartada: acumula e sai depois.

## Limites

≤ 4 mensagens por hora (janela móvel) · ≤ 12 por dia (dia de São Paulo) ·
≥ 10 minutos entre mensagens · silêncio das 22h00 às 06h30 (America/Sao_Paulo).

O que for barrado **fica na fila** para a próxima janela. Correções (`CORRECTED`) e
retratações (`RETRACTED`) furam a ordem e vão na frente, mas continuam respeitando os
limites.

## Detalhes do contrato que importam

1. **O JSONL tem duas formas de linha.** A maioria é item bloqueado
   (`{"item", "claims", "gate", "recorded_at"}`) e **não tem a chave `alert`**. Só a
   forma com `alert` e `gate.allowed == true` vira mensagem. Um leitor ingênuo que
   assumisse `linha["alert"]` quebraria em 215 das 218 linhas do dia 29.
2. **O nome do arquivo é a data UTC**, não a de São Paulo (`review_queue.py` usa
   `datetime.now(UTC)`). Entre 21h e meia-noite em São Paulo o arquivo do momento já é o
   de "amanhã" em UTC. Por isso a ponte lê uma janela de dias (`repo.dias_janela`,
   padrão 2), nunca um dia só.
3. **`gate.action` pode ser `hold`**, com `held_until`: é a nuvem segurando o alerta.
   A ponte não envia nada disso — quando a nuvem liberar, o alerta reaparece com
   `allowed: true` e aí sim entra na fila.
4. **Idempotência por `alert_id`**, em `enviados.json`. Se esse arquivo sumir, a próxima
   execução **semeia** o histórico: marca tudo que está na janela como já entregue e não
   envia nada. É o comportamento pedido, e é o que impede um despejo acidental.
5. **Resposta incerta não é reenviada.** Se o WAHA aceitar a requisição mas não
   responder (timeout), o alerta é gravado como `incerto` e a ponte para. A mensagem
   pode ter chegado; quem decide reenviar é o Douglas.

## Arquivos

```
~/tracknews-bridge/
  bridge.py         a ponte
  autoteste.py      as regras que não podem quebrar
  config.json       600. Inclui o chat id do grupo
  enviados.json     600. alert_id já entregues
  log.jsonl         600. um registro por envio
  repo.git          clone bare (só o branch state)
  PAUSED            se existir, nada sai
  .lock             trava: uma execução por vez (timer × comando manual)
  atualizar.sh      auto-atualização a cada ciclo (autoteste antes de instalar)
  hermes.py         transporte pelo bridge do Hermes, quando não há WAHA
  hermes-bridge-raw.sh  patch de 2 linhas no bridge.js do Hermes: POST /send com
                    `raw: true` sai sem o cabeçalho "⚕ *Hermes Agent*" (backup em
                    bridge.js.tracknews-bak; reverter = copiar de volta e
                    `systemctl --user restart hermes-gateway.service`)
  cutucar-nuvem.py  se o agendador do GitHub pulou o ciclo da nuvem, dispara o
                    workflow com a credencial do git da própria ponte (dia útil,
                    9h-18h, nunca empilha, no máximo 1 disparo a cada 20 min);
                    pede o digest (7h20) e o fechamento 18h (18h10) se não saíram
  outputs/fechamento/<dia>.md  Fechamento livro 18h: entra na fila como o digest
  heartbeat.sh      estado sem segredos no branch tracknews-heartbeat do repo privado
  atualizar.log     o que atualizar.sh, o patch e o cutucar fizeram
~/.config/tracknews-bridge/.env   600. chave do WAHA, se o seu exigir
```

## Reconhecimento (somente leitura)

```bash
bash recon-antigo.sh > relatorio.txt   # quem manda mensagem hoje para o grupo
bash hermes-check.sh                   # estado do Hermes, com evidência
```

Nenhum dos dois desliga, repara ou reinicia coisa alguma. O `recon-antigo.sh` termina
imprimindo o comando **reversível** de desligar e religar para cada tipo de item — para
serem rodados só depois do OK, um a um.

## A máquina precisa ficar ligada

A coleta e a redação continuam na nuvem, 24/7. A **entrega** depende do WAHA local.
Com a máquina desligada os alertas se acumulam na fila do branch `state` e saem quando
ela voltar — respeitando os limites, sem rajada.

## Queda de luz: a cadeia de religamento

O timer roda dentro do WSL, e o Windows **não** sobe o WSL sozinho no boot. Para a
entrega voltar sem ninguém na frente do PC, cada elo abaixo precisa estar armado —
os dois primeiros são configuração do Windows e ficam a cargo do Douglas:

1. **Energia**: nunca suspender/hibernar (Configurações → Energia). Opcional, na BIOS:
   religar sozinho depois de falta de luz ("Restore on AC Power Loss").
2. **Logon automático** do usuário no Windows (`netplwiz`, desmarcar "exigir nome e
   senha"). Sem logon, nenhuma tarefa de usuário dispara.
3. **WSL de pé**: registrar `windows/wsl-autostart-task.xml` (uma vez, PowerShell como
   administrador). No logon ela sobe o Ubuntu e o mantém vivo.
4. **Timer de volta**: já coberto pelo `install.sh --agendar` — systemd de usuário +
   `loginctl enable-linger`; o `Persistent=true` do timer recupera execuções perdidas
   enquanto o PC esteve desligado.
5. **WAHA de volta**: a ponte não toca no WAHA, então quem garante o retorno dele é a
   configuração do próprio container (decisão do Douglas; tipicamente
   `docker update --restart unless-stopped <container>` + Docker Desktop iniciando com o
   Windows). Enquanto o WAHA não voltar, a ponte apenas retenta a cada 10 minutos e
   nada se perde: a fila continua no branch `state`.

Teste do circuito completo: reiniciar o Windows, não tocar em nada e conferir
`systemctl --user list-timers tracknews-bridge.timer` uns minutos depois do logon
automático.
