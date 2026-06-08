"""Agente de conteúdo: BROADCAST → rascunhos de LinkedIn.

Fluxo com dois pontos de aprovação humana:
  collect  -> tira um snapshot dos dados do servidor BROADCAST
  propose  -> Gate 1: sugere pautas (você escolhe o ângulo)
  draft    -> Gate 2: rascunha o post no seu estilo (você edita e publica)
"""
