# Ferramentas do modo local (computador do Douglas)

So fazem sentido com internet aberta. Na nuvem o proxy bloqueava Yahoo, CVM e B3 e
tudo passava pela fila do GitHub Actions; rodando no Mac a mesa busca direto. Regras
de uso: `CLAUDE.md` (secao "Modo local") e skill `livro` (secao "Modo local").

| Arquivo | Para que serve | Exemplo |
|---|---|---|
| `preparar.sh` | Hook de inicio de sessao: cria o `.venv` (Python 3.12), instala as dependencias, poe `python3` e `gh` no PATH, busca o branch `dados` e imprime a linha "MODO LOCAL". Na nuvem sai sem fazer nada | `bash ferramentas/local/preparar.sh` |
| `coletar.py` | Coleta direta de um ativo (e dos pares) com o mesmo `coletar_dados.py` do Actions, em cerca de 1 minuto por ativo. Grava em `dados_local/` (fora do git), que o `mesa.py` le enquanto for mais novo que o branch `dados`; avisa o Actions para o branch alcancar | `python3 ferramentas/local/coletar.py CURY3 --pares auto` |
| `fita.py` | Fita intradia hora a hora, direto do Yahoo, e a hora em que um ativo se descolou do outro | `python3 ferramentas/local/fita.py CURY3 DIRR3 TEND3 --dia 2026-09-30` |
| `porque.py` | "Por que mexeu": ativo contra os pares proximos, o que e do setor e o que e so dele, a hora da divergencia, volume, documentos da CVM do dia, dias parecidos e o roteiro do que conferir na web | `python3 ferramentas/local/porque.py CURY3` |
| `opcoes.py` | Cadeia de opcoes da B3 com o premio real do fechamento (arquivos publicos do Boletim Diario), volatilidade implicita, delta e liquidez | `python3 ferramentas/local/opcoes.py VALE3 --venc 2026-11` |
| `livro_local.sh` | Plano C do livro: roda o runner aqui, sem o Actions, numa copia em `livro_out/previa/` (previa, nada vai para o branch `dados`). Para quando o Actions falha ou atrasa | `bash ferramentas/local/livro_local.sh fechamento` |
| `rotinas.md` | Prompts das tres rotinas do livro para as tarefas agendadas do Claude Desktop | |
| `disparar.py` | Dispara um workflow pelo `gh` e espera o resultado chegar ao branch `dados` (substitui a ferramenta do GitHub que so existia na nuvem) | `python3 ferramentas/local/disparar.py livro fechamento --ids "..."` |

O que nao muda: o branch `dados` e escrito so pelo Actions; `dados_local/` e
`livro_out/` nunca entram no git; a fita e a ficha do "por que mexeu" sao apoio para
explicar e nao substituem os numeros do runner do livro.

Testes sem rede: `python3 -m pytest tests/test_local.py -q`.
