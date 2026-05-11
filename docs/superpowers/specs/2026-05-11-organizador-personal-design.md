# Organizador Personal — Diseño v1 (MVP)

**Fecha:** 2026-05-11
**Estado:** Diseño aprobado, pendiente de plan de implementación
**Usuario:** Pablo Cansinos (uso personal individual)

## Objetivo

Construir un asistente personal conversacional, accesible desde el móvil, que ayude a Pablo a organizar su día a día: eventos puntuales, reuniones, citas médicas, rutinas recurrentes, objetivos semanales y tareas sueltas. La interacción es 100% por chat en lenguaje natural (español de España).

Filosofía: empezar mínimo y crecer iterativamente. El MVP debe estar funcionando y ser útil cuanto antes; las mejoras (recordatorios proactivos, sincronización con Google Calendar, etc.) se planificarán como proyectos posteriores.

## Decisiones clave

- **Canal de interacción:** bot de Telegram (gratis, móvil-first, API sencilla).
- **Cerebro:** API de Claude (Anthropic) con tool use.
- **Almacenamiento:** SQLite local en un único archivo (`organizador.db`).
- **Hosting (MVP):** proceso de Python corriendo en el Mac del usuario con `caffeinate` para evitar suspensión. Migración futura a Fly.io u Oracle Cloud Free cuando el MVP esté maduro.
- **Modelo de despliegue:** un asistente independiente por usuario (carpeta + base de datos por persona). Multi-usuario compartido queda fuera del alcance.

## Arquitectura

```
Usuario (Telegram móvil)
    │
    ▼
bot.py  ───── verifica ALLOWED_USER_ID ──── ignora si no autorizado
    │
    ▼
brain.py ─── envía mensaje + contexto (fecha/hora, idioma) a Claude API
    │
    ▼
Claude decide qué herramientas llamar
    │
    ▼
tools.py ─── ejecuta funciones contra db.py (SQLite)
    │
    ▼
Claude redacta respuesta natural en español
    │
    ▼
Bot envía respuesta por Telegram
```

### Stack

- Python 3.11+
- `python-telegram-bot` (polling, asíncrono)
- `anthropic` (SDK oficial)
- `sqlite3` (módulo estándar de Python)
- `python-dotenv` (para secretos)

### Estructura de archivos

```
Proyecto Prueba/
├── bot.py              # Entrada, listener de Telegram
├── brain.py            # Orquestación Claude + tool use
├── tools.py            # Implementación de herramientas
├── db.py               # Conexión y queries SQLite, migraciones
├── config.py           # Carga .env y constantes
├── organizador.db      # Base de datos (creada al primer arranque)
├── .env                # TELEGRAM_TOKEN, ANTHROPIC_API_KEY, ALLOWED_USER_ID
├── .env.example        # Plantilla pública sin secretos
├── start.sh            # caffeinate -i python bot.py
├── requirements.txt    # Dependencias
└── docs/
    └── superpowers/
        └── specs/      # Este documento y futuros diseños
```

## Modelo de datos

Tres tablas en SQLite:

### `events`
| Campo | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | Autoincrement |
| title | TEXT NOT NULL | Título del evento |
| datetime | TEXT NOT NULL | ISO 8601 (`2026-05-22T17:00:00`), zona Europe/Madrid |
| category | TEXT | `medical` / `work` / `personal` / `other` |
| recurring_rule | TEXT | RRULE simple (`WEEKLY:MON`, `DAILY`) o NULL |
| notes | TEXT | Opcional |
| created_at | TEXT NOT NULL | Timestamp ISO 8601 |

### `objectives`
| Campo | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | |
| text | TEXT NOT NULL | |
| week_start | TEXT NOT NULL | Fecha del lunes (YYYY-MM-DD) |
| done | INTEGER NOT NULL DEFAULT 0 | 0/1 |
| created_at | TEXT NOT NULL | |

### `tasks`
| Campo | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | |
| text | TEXT NOT NULL | |
| done | INTEGER NOT NULL DEFAULT 0 | |
| created_at | TEXT NOT NULL | |

Las rutinas recurrentes se modelan como `events` con `recurring_rule` no nulo. No requieren tabla propia.

## Herramientas expuestas a Claude

### Eventos
- `add_event(title, datetime, category, recurring_rule?, notes?)` → devuelve id creado.
- `query_events(date_from, date_to, category?)` → lista de eventos en el rango, expandiendo recurrentes.
- `update_event(id, fields)` → modifica campos.
- `delete_event(id)` → borra (con confirmación previa de Claude).

### Objetivos
- `add_objective(text, week_start)` → guarda objetivo. Si `week_start` no se da, asume la semana actual.
- `query_objectives(week_start?)` → si se da semana, solo de esa; si no, todas las activas.
- `mark_objective_done(id)` → marca como hecho.

### Tareas
- `add_task(text)` → añade.
- `list_tasks(include_done?)` → lista pendientes (o todas si `include_done=true`).
- `complete_task(id)` → marca hecha.

## Interacción conversacional

### Contexto del sistema (system prompt)

Claude recibe en cada turno:
- Fecha y hora actuales en zona Europe/Madrid.
- Instrucción: responder en español de España.
- Tono: directo, amable, sin floritura.
- Reglas de comportamiento:
  - Si una fecha es ambigua, preguntar antes de actuar.
  - Antes de borrar algo, mostrar lo que va a borrar y pedir confirmación.
  - Puede llamar varias herramientas en un mismo turno si el mensaje lo requiere.
  - Si la herramienta devuelve un error, explicarlo al usuario con palabras claras.

### Resolución de fechas

- "mañana", "el viernes", "la semana que viene" → resueltas por Claude a fechas absolutas usando la fecha actual del contexto.
- Una fecha sin año (ej. "el 5 de mayo") cuya fecha en el año en curso ya ha pasado → asumir año siguiente, pero confirmar.
- "a las 5" sin am/pm → preguntar.

### Ejemplo end-to-end

> Usuario: "Apunta dentista el lunes a las 9 y añade comprar pasta a la lista"
>
> Claude:
> 1. Resuelve "lunes" → 2026-05-18.
> 2. Llama `add_event("Dentista", "2026-05-18T09:00:00", "medical")`.
> 3. Llama `add_task("Comprar pasta")`.
> 4. Responde: "Hecho. Dentista el lunes 18 a las 9:00 y 'comprar pasta' añadido a tu lista."

## Seguridad

- **Autorización:** el bot solo procesa mensajes cuyo `from.id` coincida con `ALLOWED_USER_ID` en `.env`. Cualquier otro mensaje se ignora silenciosamente (no responder evita confirmar la existencia del bot a terceros).
- **Secretos:** `.env` nunca se comparte ni se commitea. Se incluye `.env.example` como plantilla.
- **Privacidad de datos:** todos los datos en `organizador.db` viven solo en el Mac del usuario. Los mensajes transitan por la API de Anthropic (política: no se entrena con datos de API).

## Manejo de errores

| Situación | Comportamiento |
|---|---|
| API de Claude falla (red, 5xx) | Bot responde "ahora mismo no puedo procesar esto, inténtalo en un momento" |
| Herramienta lanza excepción | Claude recibe el error y lo explica al usuario en lenguaje natural |
| SQLite error (raro) | Mensaje claro al usuario; se loguea el error en consola |
| Bot reiniciado | Recupera estado desde `organizador.db`; los mensajes recibidos durante la caída se pierden si Telegram no los retiene |
| Mensaje de usuario no autorizado | Se ignora sin respuesta |

## Operación

- **Arranque:** `./start.sh` (lanza `caffeinate -i python bot.py`).
- **Parar:** `Ctrl+C` en la terminal donde corre.
- **Logs:** salida estándar a la terminal. Para v1 no se persisten a archivo.
- **Backup:** copiar `organizador.db` periódicamente (manual de momento).

## Fuera del alcance del MVP

Documentado explícitamente para gestionar expectativas:

- ❌ Recordatorios proactivos (notificaciones antes de un evento).
- ❌ Integración con Google Calendar / Apple Calendar.
- ❌ Multi-usuario / asistente compartido.
- ❌ Sincronización entre dispositivos (Telegram cubre esto en la práctica).
- ❌ Mensajes de voz / transcripción.
- ❌ Adjuntos (fotos, documentos).
- ❌ Logs persistentes a archivo.
- ❌ Despliegue en la nube.

Cada uno de estos se planificará como su propio proyecto cuando proceda.

## Patrón para añadir funcionalidades en el futuro

Cuando surja una mejora:
1. Identificar si requiere nuevos datos → añadir tabla/columna en `db.py` con migración.
2. Implementar la(s) nueva(s) función(es) en `tools.py`.
3. Registrar la herramienta en la lista que se pasa a Claude en `brain.py`.
4. Probar.

El sistema está deliberadamente modular para que añadir piezas no requiera tocar las existentes.

## Criterios de éxito del MVP

- Puedo añadir un evento, una tarea o un objetivo escribiendo en lenguaje natural desde Telegram en el móvil.
- Puedo consultar qué tengo en una fecha o rango de fechas.
- Puedo consultar objetivos de una semana pasada referenciándola por fecha.
- El bot rechaza mensajes de cualquier usuario que no sea yo.
- El bot resiste reinicios sin perder datos.
- Coste mensual de API < 5 €/mes para uso personal típico.
