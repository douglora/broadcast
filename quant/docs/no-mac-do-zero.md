# No Mac, do zero — o guia detalhado

Este guia supõe que você nunca abriu o Terminal. Cada passo diz exatamente o que fazer,
o que você deve ver na tela, e o que fazer se aparecer diferente.

Se você já tem o projeto rodando no Mac, pule direto para a **Parte 3**.

---

## Parte 1 — Abrir o Terminal

O Terminal é um programa que já vem instalado no Mac. Ele é uma janela onde você digita
comandos em vez de clicar em botões.

**Jeito mais rápido (recomendado):**

1. Aperte **⌘ Command + Barra de espaço**. Abre uma barra de busca no meio da tela (é o
   Spotlight).
2. Digite `terminal`.
3. Aperte **Enter**.

**Jeito alternativo, pelo Finder:**

1. Abra o **Finder** (o ícone do rostinho azul no Dock).
2. No menu de cima: **Ir → Utilitários** (ou ⇧ Shift + ⌘ Command + U).
3. Dê dois cliques em **Terminal**.

**O que você deve ver:** uma janela branca ou preta com uma linha parecida com esta:

```
douglas@MacBook-Pro ~ %
```

Isso se chama *prompt*. Ele mostra seu usuário, o nome do computador, e onde você está
(`~` quer dizer "minha pasta pessoal"). O `%` é onde você digita.

**Três coisas que ajudam desde já:**

- **Colar** é **⌘ Command + V**, como em qualquer programa do Mac. Não é Ctrl+V.
- Depois de digitar um comando, você precisa apertar **Enter** para ele rodar.
- Se um comando estiver demorando e você quiser cancelar, aperte **Control + C**.

**Truque que economiza muita digitação:** você pode arrastar uma pasta do Finder para dentro
da janela do Terminal, e ele escreve o caminho dela sozinho.

---

## Parte 2 — Colocar o projeto no seu Mac

### 2.1 Descobrir se você já tem

No Terminal, digite isto e aperte Enter:

```bash
ls ~/broadcast
```

- **Se aparecer uma lista de arquivos** (`app.py`, `index.html`, `quant`...), você já tem o
  projeto. Pule para a Parte 3.
- **Se aparecer** `No such file or directory`, siga para 2.2.

### 2.2 Instalar as ferramentas de linha de comando

O Mac precisa de um pacote da Apple para lidar com código. Digite:

```bash
xcode-select --install
```

- Se abrir uma janela pedindo para instalar, clique em **Instalar** e espere (uns 10–20
  minutos, dependendo da internet).
- Se aparecer `command line tools are already installed`, ótimo, já está.

### 2.3 Baixar o projeto

```bash
cd ~
git clone https://github.com/douglora/broadcast.git
cd broadcast
```

O que cada linha faz: a primeira te leva para sua pasta pessoal; a segunda baixa o projeto
do GitHub; a terceira entra na pasta que acabou de ser criada.

**Se pedir usuário e senha do GitHub:** o GitHub não aceita mais senha comum. O caminho
simples é baixar o ZIP: abra `https://github.com/douglora/broadcast` no navegador, clique no
botão verde **Code → Download ZIP**, descompacte, e mova a pasta para a sua pasta pessoal
com o nome `broadcast`.

### 2.4 Pegar a versão com o sistema quant

O sistema quant está num ramo separado. Ainda no Terminal, dentro da pasta:

```bash
cd ~/broadcast
git checkout claude/quantum-trading-b3-system-3bvvld
git pull
```

Deve aparecer algo como `Switched to branch 'claude/quantum-trading-b3-system-3bvvld'`.

---

## Parte 3 — Preparar o Mac (uma vez só)

Abra o **Finder**, vá até a pasta `broadcast`, e dê **dois cliques** no arquivo
**`PREPARAR-MAC.command`**.

**Se o Mac reclamar** que "não pode ser aberto porque é de um desenvolvedor não
identificado": clique com o **botão direito** no arquivo → **Abrir** → **Abrir** de novo na
janela que aparecer. Isso só é preciso na primeira vez.

**Se preferir pelo Terminal**, dá no mesmo:

```bash
cd ~/broadcast
./PREPARAR-MAC.command
```

**O que ele faz:** acha o Python, cria um ambiente isolado dentro da pasta (`.venv`),
instala tudo, e roda os 600 testes para provar que funcionou. Demora uns 15 minutos no
total — a maior parte nos testes.

**Por que o ambiente isolado.** Do macOS Sonoma em diante, instalar biblioteca no Python do
sistema dá erro (`externally-managed-environment`): a Apple protege o Python dela de
propósito. O `.venv` é uma cópia separada, só desta pasta. Ele não interfere em nada do seu
Mac e não vai para o git.

**No fim você deve ver:**

```
============================================================
  Tudo pronto.
============================================================
```

Se aparecer erro, a mensagem diz o que fazer. Os dois mais comuns:

| Mensagem | O que fazer |
|---|---|
| `Python 3 nao encontrado` | Baixe em https://www.python.org/downloads/macos/ (versão 3.12 ou 3.13), instale o `.pkg`, e rode o preparador de novo |
| algo sobre compilar ou `wheel` | Rode `xcode-select --install` no Terminal, espere terminar, e rode o preparador de novo |

---

## Parte 4 — O comando que você vai usar todo dia

Sempre que abrir uma janela nova do Terminal para trabalhar no projeto, faça estas duas
coisas primeiro:

```bash
cd ~/broadcast
source .venv/bin/activate
```

Depois do segundo comando, o prompt muda e passa a mostrar `(.venv)` na frente:

```
(.venv) douglas@MacBook-Pro broadcast %
```

**Esse `(.venv)` é o sinal de que está tudo certo.** Enquanto ele estiver aí, você pode
digitar `python3` normalmente que ele usa o ambiente isolado.

Se esquecer de ativar, os comandos falham com `ModuleNotFoundError: No module named
'pandas'`. É só ativar e repetir.

Para sair do ambiente, digite `deactivate`. Fechar a janela também sai.

---

## Parte 5 — A sequência completa, na ordem

### Passo 1 — Os dois e-mails (hoje, antes de tudo)

Estão prontos em `quant/docs/emails-para-enviar.md`. Copie, ajuste o nome do destinatário,
envie. Um vai para o seu assessor no Safra (tabela de custos), outro para o compliance
(Res. CVM 178 e política de conta própria).

**São os dois únicos passos que podem encerrar o projeto**, e nenhum depende de computador.
Faça primeiro.

### Passo 2 — Quando o Safra responder, rode a conta

```bash
cd ~/broadcast
source .venv/bin/activate
python3 -m quant.custos --corretagem 15.00
```

Troque `15.00` pelo valor que vier. O teto no cenário base é **R$ 1,54 por ordem** — o
comando imprime o veredito nos três cenários e diz se cabe.

### Passo 3 — A carga de dados: um duplo-clique

No **Finder**, dentro da pasta `broadcast`, dê **dois cliques** em
**`CARREGAR-DADOS.command`**.

Ele faz a carga inteira e, no fim, confere o que chegou. Três coisas que ele resolve
sozinho:

- **o Mac não adormece** enquanto a janela estiver aberta (usa o `caffeinate` do próprio
  macOS) — Mac que dorme no meio derruba o download;
- **se a internet cair**, nada se perde: clique duas vezes de novo e ele continua de onde
  parou;
- **tudo fica salvo num log** em `quant/saida/carga_<data>.log`, para você me mandar o
  arquivo em vez de tirar print.

**Demora horas.** Pode minimizar a janela e ir fazer outra coisa. Para interromper:
**Control + C** (nada se perde).

Se preferir pelo Terminal, é o mesmo:

```bash
cd ~/broadcast
source .venv/bin/activate
python3 -m quant.primeira_carga --continuar
python3 -m quant.dados.conferir
```

A conferência tem que sair **sem nenhum `FALHOU`**. Se sair, pare e me mande o log: banco
errado envenena tudo que vem depois, e a falha mais cara (empresa deslistada faltando) não
quebra nada — só deixa o resultado bonito por engano.

### Passo 4 — O gate da Fase 1

```bash
python3 -m quant.validacao.replica_nefin --ini 2008 --fim 2026
```

Ele reconstrói os fatores de momentum e valor a partir dos **seus** dados e compara com os
do NEFIN. Passa com correlação ≥ 0,90 e diferença anual dentro de ±3 p.p.

**Se falhar, pare.** Não é o gate que está apertado — é o banco que está errado.

### Passo 5 — O backtest (Fase 2)

```bash
python3 -m quant.backtest --janela treino
```

Esse você pode rodar quantas vezes quiser: é a janela de exploração (2011–2015).

O holdout é diferente — ele abre **uma vez só** e depois lacra:

```bash
python3 -m quant.backtest --janela holdout --abrir-holdout
```

Não rode esse comando antes de estar satisfeito com o treino. É o teste final, e ele só
vale uma vez.

### Passo 6 — Registrar a linha de base

```bash
python3 -m quant.versoes --registrar "linha de base" "fase 1 e 2 aprovadas" \
  --backtest '{"sharpe": 0.3}'
```

Troque `0.3` pelo Sharpe que o backtest devolveu. A partir daqui, toda mudança de parâmetro
entra num orçamento de **duas por ano**.

### Passo 7 — A rotina diária (Fase 4, de 3 a 6 meses)

**De manhã, antes das 10:20:**

```bash
cd ~/broadcast
source .venv/bin/activate
python3 -m quant.rodar_diario --paper
```

Depois clique duas vezes em **`INICIAR-TERMINAL.command`** e abra
**http://localhost:5051/quant** no navegador → aba **Boleta**.

**Depois do fechamento:**

```bash
python3 -m quant.dados.arquivar_b3
python3 -m quant.execucao.campanha --sessao
```

**Quando errar** (ordem esquecida, preço digitado errado), anote no mesmo dia:

```bash
python3 -m quant.execucao.campanha --erro 2026-09-09 ordem_esquecida "esqueci a venda de ABCD3"
```

**Fim de mês:**

```bash
python3 -m quant.execucao.campanha --conferir 2026-09
python3 -m quant.relatorio --periodo mensal
python3 -m quant.fiscal --ano 2026
python3 -m quant.execucao.campanha --status
```

---

## Se algo der errado

| O que aparece | O que significa | O que fazer |
|---|---|---|
| `command not found: python3` | Python não instalado | Baixe em python.org/downloads/macos |
| `ModuleNotFoundError: No module named 'pandas'` | esqueceu de ativar o ambiente | `source .venv/bin/activate` |
| `No such file or directory` | está na pasta errada | `cd ~/broadcast` |
| `externally-managed-environment` | tentou instalar no Python do sistema | use o `.venv`; rode o `PREPARAR-MAC.command` |
| `Permission denied` ao clicar no `.command` | falta permissão de execução | no Terminal: `chmod +x *.command` |
| o navegador não abre o painel | servidor não está rodando | clique em `INICIAR-TERMINAL.command` e espere aparecer o endereço |
| a carga trava num passo | fonte fora do ar | espere e rode `--continuar`; se insistir, me mande a mensagem |

**Comandos de emergência:**

```bash
pwd        # mostra em que pasta voce esta
ls         # lista o que tem na pasta
cd ~/broadcast   # volta para a pasta do projeto
```

E, para parar qualquer coisa que esteja rodando: **Control + C**.

---

## Uma coisa que vale repetir

Nada disso ainda testou se a estratégia ganha dinheiro. Os passos 3 a 6 existem para
descobrir isso — e o resultado pode ser que não ganha. O plano prevê essa saída: se o
backtest reprovar na Fase 2, o trabalho não foi perdido, ele vira infraestrutura de dados
do BROADCAST. O que não pode acontecer é descobrir isso com dinheiro dentro.
