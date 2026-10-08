"""Fontes de dados do livro. Cada modulo expoe funcoes puras de parse (testaveis
sem rede) e uma funcao de coleta que usa livro.http.Cliente. Falha de uma
fonte nunca derruba as outras: quem orquestra (livro.coletar) registra o
status por perna no manifest."""
