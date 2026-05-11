#!/bin/bash
# Arranca el bot manteniendo el Mac despierto mientras corre.
# Para parar: Ctrl+C en esta terminal.

set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "No encuentro .venv. Crea el entorno con:"
    echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

source .venv/bin/activate

if [ ! -f ".env" ]; then
    echo "No encuentro .env. Cópialo desde .env.example y rellena las claves."
    exit 1
fi

echo "Arrancando bot (Ctrl+C para parar)…"
caffeinate -i python bot.py
