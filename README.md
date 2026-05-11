# Organizador Personal

Asistente personal por Telegram para gestionar eventos, objetivos semanales y tareas. Hablas con él en español natural y guarda todo en una base de datos local en tu Mac.

Diseño completo: `docs/superpowers/specs/2026-05-11-organizador-personal-design.md`

## Qué necesitas antes de empezar

1. **Python 3.11+** — comprueba con `python3 --version`.
2. **Un bot de Telegram** — gratis, lo creas hablando con [@BotFather](https://t.me/BotFather):
   - Abre Telegram, busca `@BotFather`, dale a Start.
   - Escribe `/newbot`.
   - Sigue las instrucciones (nombre + username terminado en `bot`).
   - Te dará un **token** tipo `1234567:ABC-DEF...`. Guárdalo.
3. **Tu Telegram user ID** — abre [@userinfobot](https://t.me/userinfobot) en Telegram y dale a Start. Te mostrará tu ID numérico.
4. **Una clave de API de Anthropic** — en [console.anthropic.com](https://console.anthropic.com):
   - Crea una cuenta o entra.
   - Ve a `API Keys` → `Create Key`.
   - Cárgale unos pocos € (con 5 € te llega para meses de uso personal normal).

## Instalación

```bash
cd "/Users/pablocansinos/Desktop/Proyecto Prueba"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Ahora edita `.env` y rellena las tres variables con lo que has recopilado.

## Arrancar

```bash
./start.sh
```

Se quedará corriendo en la terminal. El Mac no se dormirá mientras esté activo (`caffeinate`). Para pararlo: `Ctrl+C`.

## Uso

Abre Telegram, busca tu bot por el username que le pusiste y escríbele. Ejemplos:

- "Apunta cita médico el 22 a las 5 de la tarde"
- "¿Qué tengo el 15 de mayo?"
- "Esta semana mis objetivos son terminar el informe y hacer deporte 3 veces"
- "¿Qué objetivos pusimos el domingo?"
- "Añade comprar pan a la lista"
- "¿Qué tareas tengo pendientes?"

## Backup de tus datos

Tus datos viven en `organizador.db`. Para respaldarlos, copia ese archivo donde quieras (iCloud, Dropbox, USB). Para restaurarlos, simplemente vuelve a poner el archivo en su sitio.

## Tests

```bash
source .venv/bin/activate
python -m pytest -v
```

## Estructura

| Archivo | Qué hace |
|---|---|
| `bot.py` | Escucha mensajes de Telegram |
| `brain.py` | Conversa con Claude y gestiona herramientas |
| `tools.py` | Las funciones que Claude puede invocar (CRUD) |
| `db.py` | Acceso a SQLite |
| `config.py` | Carga `.env` y constantes |
| `date_utils.py` | Helpers de fechas |
| `organizador.db` | Tu base de datos (se crea sola) |
