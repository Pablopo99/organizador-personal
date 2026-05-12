# Mensaje matutino + Recordatorios proactivos — Diseño

**Fecha:** 2026-05-12
**Estado:** Diseño aprobado, pendiente de plan de implementación
**Sigue a:** tono/comandos/formato (2026-05-12-tono-comandos-formato-design.md)

## Objetivo

Dos funcionalidades proactivas en una iteración (comparten infraestructura de scheduling):

1. **Mensaje matutino** diario a las 09:00 con el resumen del día.
2. **Recordatorios** antes de cada evento: uno 1 día antes y otro 1 hora antes.

Filosofía: el bot deja de ser solo reactivo (espera a que tú le hables) y pasa a ser proactivo (te avisa cuando toca). Cierra el bucle que convierte el bot en asistente real.

## Decisiones clave

- **Hora del matutino:** 09:00 fija (cambio en código si Pablo quiere otra). No configurable por comando en esta iteración.
- **Antelaciones de recordatorios:** dos por evento — 1 día antes y 1 hora antes.
- **Mensaje matutino siempre se envía**, incluso si el día está vacío (Claude redacta un saludo apropiado).
- **Solo eventos no recurrentes** reciben recordatorios. Los recurrentes (gimnasio cada lunes) quedan fuera de esta versión.
- **Scheduler:** se usa `Application.job_queue` de `python-telegram-bot` (APScheduler integrado, sin librerías nuevas).
- **Eventos `done=1`** se excluyen de recordatorios.

## Arquitectura

```
                  ┌──────────────────────────┐
Application       │      job_queue (PTB)     │
  build  ────────>│                          │
                  │  ┌────────────────────┐  │
                  │  │ run_daily(09:00,   │──┼──> scheduler.morning_summary
                  │  │   morning_summary) │  │
                  │  └────────────────────┘  │
                  │  ┌────────────────────┐  │
                  │  │ run_repeating(5min,│──┼──> scheduler.check_reminders
                  │  │   check_reminders) │  │
                  │  └────────────────────┘  │
                  └──────────────────────────┘
```

**Archivos:**

- **`scheduler.py` (nuevo)** — dos funciones async:
  - `morning_summary(context)`: llama a `brain.handle_message()` con un prompt matinal, envía resultado a `ALLOWED_USER_ID`.
  - `check_reminders(context)`: consulta eventos próximos en BD, manda recordatorios pendientes, marca flags.
- **`bot.py` (modificado)** — en `main()`, después de construir `Application`, registra los dos jobs.
- **`db.py` (modificado)** — esquema y migración añaden `reminder_1d_sent` y `reminder_1h_sent` a `events`.
- **`tools.py` (modificado)** — `update_event` resetea flags cuando cambia `datetime`.

## Modelo de datos

Columnas nuevas en tabla `events`:

| Columna | Tipo | Default | Significado |
|---|---|---|---|
| `reminder_1d_sent` | INTEGER | 0 | 1 si ya se envió el aviso de 1 día antes |
| `reminder_1h_sent` | INTEGER | 0 | 1 si ya se envió el aviso de 1 hora antes |

Migración idempotente vía `_migrate()` en `db.py`: si las columnas no existen, las añade con `ALTER TABLE`.

## Comportamiento del matutino

A las 09:00 cada día:

1. Construir prompt: «Es {weekday}, {date}. Genera el saludo matutino para Pablo: empieza con "Buenos días Pablo 🌅", después aplica el formato del resumen de hoy (📅 HOY / 📝 PENDIENTES / ✅ COMPLETADO HOY si aplica). Si no hay nada agendado, salúdale y dile que disfrute el día libre. Cierre motivador opcional.»
2. Llamar a `brain.handle_message(prompt, user_id=ALLOWED_USER_ID)`. Esto reutiliza la memoria conversacional del usuario, así el bot puede contextualizar.
3. Aplicar `_markdown_to_html()` al resultado (defensa anti-Markdown).
4. Enviar a `ALLOWED_USER_ID` con `parse_mode=HTML`.

Si el LLM falla: log de error, no se reintenta (al día siguiente vuelve a haber matutino).

## Comportamiento de los recordatorios

Cada 5 minutos:

1. Consultar BD: eventos no recurrentes, `done=0`, con `datetime` entre ahora y ahora+26h.
2. Para cada evento, calcular `delta = event.datetime - now`.
3. **Recordatorio de 1 día:**
   - Si `23h ≤ delta ≤ 25h` y `reminder_1d_sent=0`:
     - Enviar: «📅 Mañana a las HH:MM tienes: <b>{título}</b>»
     - UPDATE events SET reminder_1d_sent=1 WHERE id=...
4. **Recordatorio de 1 hora:**
   - Si `50min ≤ delta ≤ 70min` y `reminder_1h_sent=0`:
     - Enviar: «⏰ En 1h tienes: <b>{título}</b>»
     - UPDATE events SET reminder_1h_sent=1 WHERE id=...
5. Si hay error con un evento concreto (no se puede enviar), loguear y continuar con los siguientes.

**Ventanas amplias** (2h para el de 1 día, 20min para el de 1h) absorben:
- Retrasos pequeños del tick de 5 min.
- Caídas breves del bot (hasta el tamaño de la ventana).

## Reseteo de flags al actualizar

Cuando se llama a `update_event(event_id, fields)`:
- Si `fields` contiene `datetime`: resetear `reminder_1d_sent=0` y `reminder_1h_sent=0`.
- Si solo cambian otros campos (título, notas, etc.): no tocar los flags.

Esto evita avisos perdidos cuando se mueve un evento.

## Limitaciones aceptadas

- El bot debe estar **corriendo** para que el scheduler funcione. Con Mac local, si está cerrado/apagado, no se enviarán. Esto se resuelve definitivamente al migrar a Fly.io (siguiente proyecto pendiente).
- Recordatorios para eventos recurrentes: fuera del alcance esta versión.
- Configuración de antelaciones: hardcoded a 1d/1h. Si Pablo quiere otras, edit de código.
- No hay manera (todavía) de silenciar recordatorios para eventos concretos.

## Seguridad

- El scheduler envía solo a `ALLOWED_USER_ID`. Mismo gate que el resto del bot.
- No accede a más datos que los ya disponibles.

## Tests

1. `scheduler.morning_summary` con `brain.handle_message` mockeado y `context.bot` mockeado → llama a Claude, manda mensaje a `ALLOWED_USER_ID`.
2. `scheduler.check_reminders` con eventos a 24h, 1h, 30min de distancia → envía los esperados, no envía los ya marcados.
3. `scheduler.check_reminders` marca correctamente los flags después de enviar.
4. `scheduler.check_reminders` ignora eventos recurrentes y `done=1`.
5. `tools.update_event` con cambio de datetime → flags resetean a 0.
6. `tools.update_event` con cambio de título → flags no se tocan.
7. `db._migrate` añade ambas columnas idempotentemente.

## Criterios de éxito

- A las 09:00, recibo en Telegram un mensaje matutino con el resumen del día.
- 1 día antes de un evento, recibo un aviso.
- 1 hora antes del mismo evento, recibo otro aviso.
- No recibo avisos duplicados para el mismo evento.
- Si modifico la fecha de un evento, recibo nuevos avisos con la nueva fecha.
- Si marco un evento como hecho, no recibo más avisos.

## Fuera del alcance

- ❌ Configuración de hora/antelaciones por usuario.
- ❌ Recordatorios para eventos recurrentes.
- ❌ Silencio configurable por evento.
- ❌ Recordatorios para tareas u objetivos (no aplican, no tienen hora).
- ❌ Notificaciones push fuera de Telegram.
