# telejoin

[![Licença: MIT](https://img.shields.io/github/license/joaomgabaldi/telejoin)](LICENSE)

Entre em grupos e canais do Telegram em lote.

## Links aceitos (um por linha; `#` comenta)

| Formato | Chamada |
|---|---|
| `t.me/+HASH`, `t.me/joinchat/HASH`, `tg://join?invite=HASH` (privados) | `messages.importChatInvite` |
| `t.me/nome`, `t.me/nome/123`, `@nome`, `tg://resolve?domain=nome` (públicos) | `channels.joinChannel` |

Repetidos entram uma vez só. `t.me/c/...` é recusado: esse link não carrega convite.

## Uso

```sh
python3 -m venv venv && venv/bin/pip install telethon pytest
cp .env.example .env && chmod 600 .env   # preencha API_ID/API_HASH
venv/bin/python telejoin.py --dry-run    # só interpreta links.txt
venv/bin/python telejoin.py              # na 1ª vez pede telefone, código e 2FA
venv/bin/python telejoin.py outra.txt    # ou `-` para ler da entrada padrão
```

O resultado de cada link vai para `telejoin.estado.json`. Rodar de novo pula os que já têm resultado definitivo
(`entrou`, `ja_membro`, `pedido_enviado`, `expirado`, `invalido`, ...) e tenta de novo os `erro`. `--refazer` ignora o estado.

## Limites do Telegram

O Telegram limita quantos chats uma conta pode entrar por período, sem publicar os números. O telejoin não
contorna o limite: ele se adapta e tenta novamente após o tempo informado.

- **FLOOD_WAIT**, de qualquer duração (minutos ou um dia): mostra até quando vai esperar, avisa o tempo que falta a
  cada 10 min, espera e tenta o mesmo link de novo.
- **Intervalo adaptativo**: começa em `TELEJOIN_INTERVALO_S` (+até 50% aleatório). Cada FLOOD_WAIT dobra o
  intervalo, até `TELEJOIN_INTERVALO_MAX_S`; cada entrada sem flood reduz 10%, de volta à base.
  Só há pausa depois de uma entrada de fato (`entrou`/`pedido_enviado`).
- **Queda de rede**: tenta reconectar a cada 60 s, sem desistir.
- **Paradas** (as únicas, além de Ctrl+C):
  - `PEER_FLOOD`: o Telegram marcou a conta como possível spam; insistir pode restringi-la. Espere pelo menos um dia.
  - Limite de 500 canais/supergrupos (1000 com Premium).
- **Chats com aprovação** viram `pedido_enviado`; entram quando um admin aceitar.

## Testes

```sh
venv/bin/python -m pytest -q tests
```
