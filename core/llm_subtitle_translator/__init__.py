"""Motore di traduzione sottotitoli basato su LLM open-weight.

Volutamente vuoto: l'import di questo package tira dentro torch/transformers,
che non devono entrare nel processo GUI all'avvio. I moduli vanno importati
esplicitamente e in modo lazy dal punto d'uso (vedi AyaTranslator.__init__).
"""
