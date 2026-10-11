"""Isolamento dos testes: as decisoes do Douglas gravadas em quant/saida (fora do git) nao podem mudar o resultado da suite."""
import pytest


@pytest.fixture(autouse=True)
def _livro_do_douglas_fora_dos_testes(tmp_path, monkeypatch):
    """`quant/saida/risco_livro.json` liga pesos por classe e a mao por volatilidade no robo de verdade. Nos testes vale o
    padrao do codigo (livro desligado); quem testa o livro passa o proprio arquivo ou troca `livro.ARQ` de novo."""
    from quant.risco import livro
    monkeypatch.setattr(livro, "ARQ", str(tmp_path / "_sem_risco_livro.json"))
    monkeypatch.setattr(livro, "ARQ_ORCAMENTO", str(tmp_path / "_sem_orcamento.json"))
    monkeypatch.setattr(livro, "ARQ_SAIDA", str(tmp_path / "_livro.json"))
    monkeypatch.setattr(livro, "ARQ_HISTORICO", str(tmp_path / "_livro_historico.json"))
