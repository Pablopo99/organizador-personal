# Cómo desplegar tu propia copia del bot

Esta guía te lleva desde cero hasta tener tu propio asistente personal por Telegram corriendo en Fly.io, completamente aislado del de la persona que te ha pasado este repo.

Cada uno tiene **su propio bot, su propia base de datos, su propio Fly y su propia clave de Anthropic**. No se cruza absolutamente nada entre instancias: dos personas siguiendo esta guía acaban con dos bots independientes que solo se parecen en el código.

Tiempo total estimado: **45-60 minutos** la primera vez. Si te pierdes en algún paso, lee dos veces y respira — todo es reversible.

---

## Lo que vas a necesitar

- Un ordenador (Mac, Linux o Windows con WSL).
- Un móvil con **Telegram** instalado.
- Una **tarjeta de crédito** para verificar Fly.io (no te van a cobrar nada mientras te quedes en el plan gratuito).
- **5 €** para cargar tu cuenta de Anthropic (te dura meses de uso personal).
- Comodidad básica con la terminal (saber abrirla y pegar comandos vale).

---

## Paso 1: Crear tu bot en Telegram (5 min)

Telegram tiene un "bot que crea bots". Se llama **BotFather**.

1. Abre Telegram en tu móvil.
2. Busca `@BotFather` y abre el chat con él. Dale a **Start**.
3. Escribe el comando:
   ```
   /newbot
   ```
4. Te pedirá un **nombre** (lo que verás en el chat) — algo como *"Mi Secretaria"* o *"Asistente de Marta"*.
5. Te pedirá un **username** que tiene que acabar en `bot` (ej. `marta_secretaria_bot`).
6. BotFather te dará un **token** tipo:
   ```
   1234567890:ABCdefGhIjKlMnOpQrStUvWxYz
   ```
   **Cópialo y pégatelo en un sitio seguro.** Este token es la "llave" que permite controlar tu bot. Si lo pierdes o se filtra, se puede regenerar en BotFather con `/revoke`.

**Importante**: nunca compartas este token. Si alguien lo tiene, puede hablar como tu bot.

---

## Paso 2: Obtener tu Telegram user ID (1 min)

El bot solo aceptará mensajes de tu cuenta (autenticación por ID). Necesitas tu ID numérico.

1. En Telegram, busca `@userinfobot` y abre el chat.
2. Dale a **Start**.
3. Te responderá con tus datos. Mira el campo **Id**, es un número de unos 9-10 dígitos.
4. **Apúntatelo.** Esto se llamará `ALLOWED_USER_ID`.

---

## Paso 3: Sacar tu clave de Anthropic (5 min)

Anthropic es la empresa que hace Claude (la IA detrás del bot).

1. Ve a [console.anthropic.com](https://console.anthropic.com) y regístrate.
2. Una vez dentro, busca la sección **Billing** o **Plans** y carga al menos **5 €** (con tarjeta). Es prepago: solo te cobran lo que consume el bot, que en uso personal son céntimos al mes.
3. Ve a **API Keys** en el menú lateral.
4. Pulsa **Create Key**, ponle un nombre tipo "Bot de Telegram", y créala.
5. Te mostrarán la clave **una sola vez**, formato:
   ```
   sk-ant-api03-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
   ```
   **Copia la clave inmediatamente y guárdala en un sitio seguro.** Si la pierdes, tendrás que crear otra.

---

## Paso 4: (Opcional) Clave de Groq para mensajes de voz (3 min)

Si quieres poder enviar **audios** al bot (te los transcribe y procesa), necesitas una clave de Groq. Si no te interesa la voz, **sáltate este paso** — el bot funcionará perfectamente con solo texto.

1. Ve a [console.groq.com](https://console.groq.com) y regístrate (es gratuito).
2. Ve a **API Keys** → **Create API Key**.
3. Cópiate la clave (formato `gsk_...`).

---

## Paso 5: Instalar y configurar Fly.io (10 min)

Fly.io es donde vivirá tu bot las 24h del día, sin depender de tu ordenador.

### 5a. Instala flyctl

En **Mac** (con Homebrew):
```bash
brew install flyctl
```

En **Linux**:
```bash
curl -L https://fly.io/install.sh | sh
```

En **Windows**: usa WSL y sigue los pasos de Linux.

### 5b. Crea tu cuenta y logueate

```bash
flyctl auth signup
```

Te abrirá el navegador para crear cuenta. Te pedirá tarjeta de crédito para verificar (no te van a cobrar nada con uso personal — el bot cabe sobrado en el plan gratuito).

Si ya tenías cuenta, usa:
```bash
flyctl auth login
```

---

## Paso 6: Clonar el repo y posicionarte (2 min)

Necesitas tener Git instalado (`git --version` para comprobarlo; si no lo tienes, instálalo).

```bash
git clone https://github.com/Pablopo99/organizador-personal.git mi-bot
cd mi-bot
```

A partir de aquí, **todos los comandos los ejecutas desde dentro de esta carpeta `mi-bot`**.

---

## Paso 7: Crear tu app en Fly y su volumen (3 min)

Elige un nombre único para tu app. Será parte de la URL pública. Solo letras minúsculas, números y guiones. Ejemplos: `marta-secretaria`, `bot-de-juan`.

```bash
flyctl apps create TU-NOMBRE-AQUI
```

(Reemplaza `TU-NOMBRE-AQUI`. Si te dice que ya existe, prueba con otro.)

Crea el volumen persistente para la base de datos (1 GB, sobra):

```bash
flyctl volumes create data --app TU-NOMBRE-AQUI --region cdg --size 1 --yes
```

> **Por qué `cdg`** (París): Madrid no está disponible en Fly. París es lo más cercano para España.

---

## Paso 8: Editar `fly.toml` con tu nombre de app (1 min)

Abre el archivo `fly.toml` que está en la carpeta (con cualquier editor de texto: VS Code, TextEdit, lo que sea).

En la primera línea verás:

```toml
app = "mi-secretaria-pablo"
```

Cámbiala por:

```toml
app = "TU-NOMBRE-AQUI"
```

Guarda el archivo.

---

## Paso 9: Configurar los secretos en Fly (3 min)

Vas a meter tus claves como **secrets** de Fly (cifradas, no se ven en logs). Reemplaza los valores entre comillas por los que conseguiste antes:

```bash
flyctl secrets set --app TU-NOMBRE-AQUI \
  TELEGRAM_TOKEN='1234567890:ABCdefGhIjKlMnOpQrStUvWxYz' \
  ANTHROPIC_API_KEY='sk-ant-api03-XXXXX' \
  ALLOWED_USER_ID='123456789' \
  GROQ_API_KEY=''
```

Si NO vas a usar voz, deja `GROQ_API_KEY=''` (vacío). Si SÍ, pega tu clave.

### (Opcional) Si quieres usar el atajo de Siri

Genera un token aleatorio y añádelo:

```bash
flyctl secrets set --app TU-NOMBRE-AQUI SIRI_TOKEN="$(openssl rand -hex 32)"
```

**Guarda lo que sale en algún sitio**, lo necesitarás para configurar el atajo en tu iPhone después (ver apéndice).

Si NO quieres Siri por ahora, también necesitas poner el secret (aunque sea con basura), porque el bot lo requiere al arrancar:

```bash
flyctl secrets set --app TU-NOMBRE-AQUI SIRI_TOKEN="no-uso-siri"
```

---

## Paso 10: Asignar IPs públicas (1 min)

Fly necesita IPs públicas para que tu bot sea accesible:

```bash
flyctl ips allocate-v4 --shared --app TU-NOMBRE-AQUI
flyctl ips allocate-v6 --app TU-NOMBRE-AQUI
```

---

## Paso 11: Desplegar (5 min)

El momento de la verdad:

```bash
flyctl deploy --app TU-NOMBRE-AQUI
```

Tardará 2-3 minutos la primera vez (compila la imagen Docker y la sube). Si todo va bien, al final verás algo como:
```
✔ Machine xxxxxxxxxx is now in a good state
Visit your newly deployed app at https://TU-NOMBRE-AQUI.fly.dev/
```

---

## Paso 12: Verificar que el bot está vivo (1 min)

Mira los logs:

```bash
flyctl logs --app TU-NOMBRE-AQUI --no-tail | tail -10
```

Deberías ver líneas tipo:
```
Base de datos lista en /data/organizador.db
Bot arrancando (polling + HTTP en :8080)…
Scheduler started
```

Y ahora abre Telegram, busca tu bot por el username que le pusiste, y escríbele:

> Hola

Debería responderte. Si lo hace, **enhorabuena, tienes tu bot funcionando** 🎉.

---

## Apéndice A: Atajo de Siri (opcional, ~15 min en iPhone)

Solo si tienes iPhone y quieres dictar al bot por voz desde cualquier sitio sin abrir Telegram.

1. Abre la app **Atajos** en tu iPhone (la del icono morado, viene preinstalada).
2. Crea un atajo nuevo con tres acciones, en este orden:
   - **Dictar texto** (icono micrófono, idioma español).
   - **Obtener contenido de URL** (icono verde):
     - URL: `https://TU-NOMBRE-AQUI.fly.dev/ingest`
     - Método: `POST`
     - Cabeceras:
       - `Authorization` → `Bearer TU-SIRI-TOKEN-AQUI` (el que generaste en el paso 9)
       - `Content-Type` → `application/json`
     - Cuerpo de la solicitud: tipo `JSON`, un campo:
       - Clave: `text` (escrito como texto)
       - Valor: variable **"Texto dictado"** (la del paso 1)
   - **Obtener valor del diccionario**:
     - Clave: `reply`
     - Diccionario: variable "Contenido de URL"
   - **Leer texto con voz** (icono altavoz rojo):
     - Texto a leer: variable "Valor del diccionario" (del paso anterior)
3. Renombra el atajo a algo corto como **"Apuntar"**.
4. Pruébalo tocando ▶ arriba. Te pedirá permisos (dictado, acceso a URL) — Permitir.
5. Después podrás decir *"Oye Siri, apuntar"* y dictar lo que quieras.

---

## Apéndice B: Comandos útiles del día a día

Ver logs en directo:
```bash
flyctl logs --app TU-NOMBRE-AQUI
```

Reiniciar el bot (si algo se atasca):
```bash
flyctl machine restart --app TU-NOMBRE-AQUI
```

Ver el estado de la app:
```bash
flyctl status --app TU-NOMBRE-AQUI
```

Actualizar el bot cuando el repo tenga novedades:
```bash
git pull
flyctl deploy --app TU-NOMBRE-AQUI
```

Cambiar un secret (ej. rotar la clave de Anthropic):
```bash
flyctl secrets set --app TU-NOMBRE-AQUI ANTHROPIC_API_KEY='sk-ant-XXX-nuevo'
```

Ver qué secrets están configurados (no muestra los valores):
```bash
flyctl secrets list --app TU-NOMBRE-AQUI
```

---

## Garantías de privacidad: por qué tus datos están aislados

Esta es la pregunta clave si te pasaron el repo desde el bot de otra persona. Te lo explico claro:

- **Tu bot de Telegram es exclusivamente tuyo.** El token de BotFather es único e intransferible. Ningún otro bot puede recibir tus mensajes ni mandar nada en tu nombre.
- **Tu base de datos vive en tu volumen de Fly.** El SQLite `organizador.db` está en `/data` dentro de **tu** máquina de Fly. Nadie tiene acceso salvo tú a través de tu cuenta de Fly.
- **Tu cuenta de Anthropic procesa solo tus mensajes.** Tu clave de API es tuya y solo tú la usas. El historial conversacional vive en memoria de **tu** máquina.
- **No hay servidor central.** Cada instancia del bot es un proceso completamente independiente corriendo en una máquina de Fly distinta, con datos distintos y claves distintas.
- **Los desarrolladores del código (yo, la persona que te pasó esto) no tienen acceso a tu instancia.** Comparten contigo el código fuente — exactamente lo mismo que si te bajaras el código abierto de un proyecto público. Lo que tú haces con ese código en tu cuenta es tuyo.

La única forma de que algo se cruzara sería si te pasaras tu propio token de Telegram a otra persona, o le dieras acceso a tu cuenta de Fly. Mientras tus credenciales sean tuyas, tus datos son tuyos.

---

## Si algo va mal

**El bot no responde a mis mensajes en Telegram**:
- Mira `flyctl logs --app TU-NOMBRE-AQUI`. Si ves errores, mándalos a quien te pasó el repo.
- Comprueba que `ALLOWED_USER_ID` en los secrets es exactamente tu user ID (sin espacios, sin comillas extra).
- Comprueba que el `TELEGRAM_TOKEN` no se haya quedado pegado mal.

**Fly dice "no machines"**:
- Despliega otra vez: `flyctl deploy --app TU-NOMBRE-AQUI`.

**El bot arranca pero al primer mensaje responde "problema técnico"**:
- Casi seguro tu clave de Anthropic está mal o no tienes créditos. Comprueba en console.anthropic.com.

**Error 409 Conflict en los logs**:
- Tienes otro proceso polleando el mismo bot. ¿Tienes el repo corriendo también en local? Para el local con `Ctrl+C` o cierra el terminal.

Para cualquier otra cosa, lee los logs con atención (`flyctl logs --app TU-NOMBRE-AQUI --no-tail | tail -50`) y pasa el output a quien te haya compartido esto. Casi todo lo que pasa está ahí escrito.
