# Respaldo Drive para Anbernic (sistema original)

App para la sección **APPS** del sistema original de Anbernic (consolas H700 como la RG34XX SP)
que respalda las partidas de la consola en **Google Drive** y las restaura **juego por juego**.

![Menú](docs/menu.png)

## Qué hace

- **Subir todo:** sube todas las partidas de una vez. Los archivos que ya están iguales en Drive
  se saltan (compara el MD5) y, si un archivo cambió, Drive conserva la versión anterior en su historial.
- **Restaurar un juego:** eliges categoría → sistema → juego. Muestra la fecha de la copia en Drive y la
  de la consola, y **avisa en rojo si la de la consola es más nueva**. Antes de reemplazar, guarda lo
  que había en `SD1/anbernic/respaldo_nube/<fecha>/`.
- **Inicio de sesión con código** (como en una TV): la consola muestra un código que se escribe en
  `google.com/device` desde el teléfono. La consola nunca ve tu contraseña.
- **Permiso mínimo** (`drive.file`): la app solo puede ver los archivos que ella misma creó, no el
  resto de tu Drive.

### Qué se respalda

| Categoría | Ubicación en la consola |
|---|---|
| RetroArch (partidas) | `saves_RA/` (`.srm`, `.sav`, `.eeprom`, …) |
| RetroArch (estados) | `states_RA/` (`.state`, `.stateN`, `.state.auto`), agrupados por juego |
| Emuladores independientes | `save/` (p. ej. GBC), `save_nds/backup/*.dsv` (DraStic), memorias VMU de Flycast |
| Ports | GTA III y Vice City (`userfiles/*.b`, **un slot por juego**), Ship of Harkinian (`soh/Save/*.sav`) |

Se revisan ambas tarjetas (`/mnt/sdcard` y `/mnt/mmc`). En Drive todo queda en la carpeta
**"Anbernic Saves"**, organizado por categoría y sistema.

## Instalación

### 1. Credenciales de Google (una sola vez)

Cada persona usa **sus propias** credenciales; no vienen incluidas en el repositorio.

1. En [console.cloud.google.com](https://console.cloud.google.com) crea un proyecto.
2. **APIs y servicios → Biblioteca → Google Drive API → Habilitar**.
3. **Google Auth Platform → Comenzar:** nombre de la app, tu correo y público **Externo**.
4. **Público → Usuarios de prueba:** agrega tu cuenta de Gmail.
5. **Clientes → Crear cliente:** tipo **"TVs y dispositivos de entrada limitada"**. Descarga el JSON.

> Mientras la app esté en estado **"Prueba"**, Google cierra la sesión cada 7 días: la app lo detecta
> y vuelve a mostrar un código. Si publicas la app ("En producción"), eso deja de pasar.

### 2. Copiar a la consola

Copia el contenido del repositorio en `Roms/APPS` de cualquiera de las dos tarjetas, y pon el JSON
descargado dentro de `nube/`:

```
Roms/APPS/Respaldo Drive.sh
Roms/APPS/nube/main.py, catalog.py, drive.py, fbui.py
Roms/APPS/nube/client_secret_XXXX.json      <- tu credencial (no la subas a GitHub)
Roms/APPS/Imgs/Respaldo Drive.png
```

No necesita instalar nada: usa `python3`, `requests` y `Pillow`, que ya vienen en el sistema.
La consola necesita **Wi-Fi** y la hora correcta (se sincroniza sola al conectarse).

## Cómo funciona

| Archivo | Qué hace |
|---|---|
| `nube/main.py` | Pantallas y flujo: menú, subida con barra de progreso, navegación para restaurar y confirmaciones. |
| `nube/catalog.py` | Encuentra las partidas y las clasifica en **categoría / sistema / juego** solo a partir de la ruta (`classify()`), así los archivos listados desde Drive se agrupan igual aunque ya no existan en la consola. |
| `nube/drive.py` | Cliente mínimo de Google Drive con `requests`. |
| `nube/fbui.py` | Dibujo en el framebuffer y lectura de botones (el mismo módulo del Monitor). |

Detalles de `drive.py`:

- **OAuth "device flow":** `POST /device/code` devuelve el código que se muestra en pantalla; la app
  consulta `/token` cada pocos segundos hasta que lo apruebas. El `refresh_token` se guarda en
  `nube/token.json` y se renueva solo. Si Google lo rechaza (`invalid_grant`, por ejemplo a los 7 días
  en modo Prueba), lo borra y pide vincular de nuevo.
- **Cada archivo en Drive guarda su ruta de la consola** en el campo `description` y la fecha de
  modificación local en `appProperties.mtime`. Así la restauración vuelve exactamente al mismo lugar
  y puede comparar fechas.
- **Subidas:** `multipart` para archivos de hasta 4 MB; **subida reanudable** (`uploadType=resumable`)
  para los más grandes, como los estados de Dreamcast (Drive no acepta multipart por encima de 5 MB).
  Las actualizaciones usan `PATCH` sobre el mismo archivo, por lo que Drive conserva el historial.
- **Restauración segura:** descarga todo primero, copia lo local a `respaldo_nube/<fecha>/`, escribe a
  un archivo temporal y lo reemplaza con `os.replace()`, para no dejar partidas a medio escribir.

Para probar por SSH sin pantalla:

```bash
python3 nube/main.py --scan     # lista las partidas encontradas y su clasificación
python3 nube/main.py --remote   # lista lo que hay en Drive (requiere haber vinculado)
```

## Seguridad

- El `.gitignore` excluye `client_secret*.json` y `token.json`. **Nunca subas esos archivos**:
  con ellos alguien podría acceder a lo que la app guardó en tu Drive.
- Para desvincular la consola: **Cuenta de Google → Desvincular** (revoca el token y lo borra).
  También puedes quitar el acceso en [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

## Compatibilidad

Probado en una **RG34XX SP** con el sistema original **1.0.6**.
