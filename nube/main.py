"""Nube: backs up console saves to Google Drive.

- "Subir todo": uploads every save (skips files whose content is already on Drive).
- "Restaurar un juego": one game at a time; current local files are copied to
  /mnt/mmc/anbernic/respaldo_nube/<date>/ before being replaced.
Buttons: D-pad to move, A accept, B back, MENU exit.
"""
import os
import shutil
import sys
import time

import requests

import catalog
import drive
import fbui as ui

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_BACKUP = "/mnt/mmc/anbernic/respaldo_nube"
ROWS = 12


class Quit(Exception):
    pass


def fmt_time(ts):
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts)) if ts else "?"


class App:
    def __init__(self):
        self.scr, self.inp = ui.Screen(), ui.Input()
        self.drv = drive.Drive(APP_DIR)

    # ---------- basic screens ----------
    def key(self, timeout=None):
        ev = self.inp.wait(timeout)
        if ev and ev[0] == ui.MENU:
            raise Quit()
        return ev

    def message(self, title, text, color=ui.FG, wait=True, hint="A / B: Continuar"):
        img, d = ui.canvas(title)
        y = 120
        for line in text.split("\n"):
            for part in ui.wrap(line, 22, ui.W - 80) or [""]:
                d.text((ui.W // 2, y), part, font=ui.font(22), fill=color, anchor="mm")
                y += 34
        if wait:
            ui.footer(d, hint)
        self.scr.show(img)
        if wait:
            while True:
                ev = self.key()
                if ev and ev[0] in (ui.A, ui.B):
                    return

    def confirm(self, title, lines, yes="A: Sí, continuar", no="B: Cancelar"):
        img, d = ui.canvas(title)
        y = 76
        for text, color in lines:
            for part in ui.wrap(text, 19, ui.W - 40) or [""]:
                d.text((20, y), part, font=ui.font(19), fill=color)
                y += 27
        ui.footer(d, f"{yes}     {no}")
        self.scr.show(img)
        while True:
            ev = self.key()
            if ev and ev[0] in (ui.A, ui.B):
                return ev[0] == ui.A

    def choose(self, title, items, hint="A: Elegir     B: Volver     MENU: Salir", start=0):
        """items: list of (label, right_text, color). Returns the chosen index or None (B)."""
        sel = start
        while True:
            img, d = ui.canvas(title)
            top = max(0, min(sel - ROWS // 2, len(items) - ROWS))
            y = 62
            for i in range(top, min(len(items), top + ROWS)):
                label, right, color = items[i]
                if i == sel:
                    d.rounded_rectangle((10, y - 2, ui.W - 10, y + 29), 6, fill=ui.SEL)
                rw = ui.font(17).getlength(right) if right else 0
                d.text((22, y + 2), ui.fit(label, 19, ui.W - 60 - rw), font=ui.font(19), fill=color or ui.FG)
                if right:
                    d.text((ui.W - 22, y + 4), right, font=ui.font(17), fill=ui.DIM, anchor="ra")
                y += 32
            if len(items) > ROWS:
                d.text((ui.W - 20, ui.H - 22), f"{sel + 1}/{len(items)}", font=ui.font(17), fill=ui.DIM, anchor="rm")
            ui.footer(d, hint)
            self.scr.show(img)
            code, value = self.key()
            if code == ui.DY:
                sel = (sel + value) % len(items)
            elif code in (ui.L1, ui.R1) or code == ui.DX:
                step = -ROWS if code == ui.L1 or (code == ui.DX and value < 0) else ROWS
                sel = max(0, min(len(items) - 1, sel + step))
            elif code == ui.A:
                return sel
            elif code == ui.B:
                return None

    # ---------- Google sign-in ----------
    def link(self):
        """Shows the google.com/device code until the user approves it. Returns True if linked."""
        try:
            flow = self.drv.start_device_flow()
        except requests.RequestException as e:
            self.message("Conectar Google Drive", f"No se pudo contactar a Google.\n¿Wi-Fi encendido?\n\n{type(e).__name__}", ui.BAD)
            return False
        while time.time() < flow["deadline"]:
            img, d = ui.canvas("Conectar Google Drive")
            d.text((ui.W // 2, 100), "En tu teléfono o PC abre:", font=ui.font(22), fill=ui.FG, anchor="mm")
            d.text((ui.W // 2, 150), flow.get("verification_url", "google.com/device").replace("https://", ""),
                   font=ui.font(32), fill=ui.OK, anchor="mm")
            d.text((ui.W // 2, 215), "y escribe este código:", font=ui.font(22), fill=ui.FG, anchor="mm")
            d.text((ui.W // 2, 280), flow["user_code"], font=ui.font(52), fill=ui.WARN, anchor="mm")
            d.text((ui.W // 2, 350), "Si dice 'Google no verificó esta app':", font=ui.font(17), fill=ui.DIM, anchor="mm")
            d.text((ui.W // 2, 375), "Configuración avanzada → Ir a Anbernic Saves", font=ui.font(17), fill=ui.DIM, anchor="mm")
            mins = int(flow["deadline"] - time.time()) // 60
            ui.footer(d, f"Esperando confirmación… (vence en {mins} min)     B: Cancelar")
            self.scr.show(img)
            ev = self.key(timeout=int(flow.get("interval", 5)))
            if ev and ev[0] == ui.B:
                return False
            try:
                if self.drv.poll_device_flow(flow):
                    self.message("Conectar Google Drive", "¡Listo! La consola quedó vinculada a tu Google Drive.", ui.OK)
                    return True
            except drive.AuthDenied:
                self.message("Conectar Google Drive", "Se rechazó el acceso.", ui.BAD)
                return False
            except (drive.AuthNeeded, requests.RequestException):
                continue  # transient error or code expired: keep showing until deadline
        self.message("Conectar Google Drive", "El código venció. Intenta de nuevo.", ui.WARN)
        return False

    def ensure_linked(self):
        return self.drv.linked() or self.link()

    def online(self, action):
        """Runs action(); handles expired sign-in (relinks once) and network errors."""
        for _ in range(2):
            if not self.ensure_linked():
                return None
            try:
                return action()
            except drive.AuthNeeded:
                self.message("Google Drive", "La sesión venció (pasa cada 7 días mientras la app está en modo Prueba).\n"
                                             "Vamos a vincularla de nuevo.", ui.WARN)
            except requests.RequestException as e:
                self.message("Google Drive", f"Error de conexión con Google.\n¿Wi-Fi encendido?\n\n{type(e).__name__}", ui.BAD)
                return None
        return None

    # ---------- upload everything ----------
    def upload_all(self):
        self.message("Subir todo", "Buscando partidas en la consola…", wait=False)
        saves = catalog.scan()
        states = [p for p, info in saves if info[0] == catalog.RA_STATES]
        size = lambda paths: ui.human(sum(os.path.getsize(p) for p in paths))
        if not self.confirm("Subir todo a Google Drive", [
                (f"Partidas: {len(saves) - len(states)} archivos "
                 f"({size([p for p, i in saves if i[0] != catalog.RA_STATES])}).", ui.FG),
                (f"Estados de RetroArch: {len(states)} archivos ({size(states)}).", ui.FG),
                ("Los que ya estén iguales en Drive se saltan; la primera vez puede tardar varios minutos.", ui.DIM),
                ("Si un archivo cambió, Drive guarda la versión anterior en su historial.", ui.DIM)]):
            return
        self.online(lambda: self._upload(saves))

    def _upload(self, saves):
        self.message("Subir todo", "Consultando lo que ya hay en Drive…", wait=False)
        remote = self.drv.list_saves()
        sent = same = 0
        failed = []
        for i, (path, info) in enumerate(saves, 1):
            img, d = ui.canvas("Subiendo a Google Drive")
            d.text((20, 90), f"{i} de {len(saves)}", font=ui.font(24), fill=ui.FG)
            d.text((20, 130), ui.fit(f"{info[1]} · {info[2]}", 19, ui.W - 40), font=ui.font(19), fill=ui.DIM)
            d.rounded_rectangle((20, 180, ui.W - 20, 200), 6, fill=ui.BAR_BG)
            d.rounded_rectangle((20, 180, 20 + max(12, int((ui.W - 40) * i / len(saves))), 200), 6, fill=ui.ACCENT)
            d.text((20, 230), f"Subidos: {sent}    Sin cambios: {same}    Errores: {len(failed)}", font=ui.font(18), fill=ui.FG)
            ui.footer(d, "MENU: Detener")
            self.scr.show(img)
            if self.key(timeout=0):
                pass  # MENU raises Quit; other keys are ignored while uploading
            existing = remote.get(path)
            try:
                if existing and existing.get("md5Checksum") == drive.md5_file(path):
                    same += 1
                    continue
                self.drv.upload(path, catalog.drive_folder(info), existing)
                sent += 1
            except drive.AuthNeeded:
                raise
            except (requests.RequestException, OSError) as e:
                failed.append((path, type(e).__name__))
        color = ui.OK if not failed else ui.WARN
        text = f"Subidos: {sent}\nSin cambios: {same}\nErrores: {len(failed)}"
        if failed:
            text += "\n\n" + "\n".join(os.path.basename(p) for p, _ in failed[:4])
        self.message("Subida terminada", text, color)

    # ---------- restore one game ----------
    def restore(self):
        remote = self.online(self.drv.list_saves)
        if remote is None:
            return
        games = {}
        for path, meta in remote.items():
            info = catalog.classify(path)
            if info:
                games.setdefault(info[0], {}).setdefault(info[1], {}).setdefault(info[2], []).append((path, meta))
        if not games:
            self.message("Restaurar", "Todavía no hay partidas en Google Drive.\nUsa primero 'Subir todo'.", ui.WARN)
            return
        cats = sorted(games)
        c = 0
        while True:
            c = self.choose("Restaurar: categoría", [(k, f"{sum(len(g) for g in games[k].values())} juegos", None) for k in cats], start=c)
            if c is None:
                return
            systems = sorted(games[cats[c]])
            s = 0
            while True:
                s = self.choose(f"{cats[c]}", [(k, f"{len(games[cats[c]][k])} juegos", None) for k in systems], start=s)
                if s is None:
                    break
                names = sorted(games[cats[c]][systems[s]])
                g = 0
                while True:
                    g = self.choose(systems[s], [(n, f"{len(games[cats[c]][systems[s]][n])} arch.", None) for n in names], start=g)
                    if g is None:
                        break
                    self.restore_game(systems[s], names[g], games[cats[c]][systems[s]][names[g]])

    def restore_game(self, system, game, files):
        lines = [(f"{system} · {game}", ui.ACCENT), ("", ui.FG)]
        for path, meta in sorted(files):
            cloud_t = int(meta.get("appProperties", {}).get("mtime", 0))
            lines.append((os.path.basename(path), ui.FG))
            lines.append((f"   Drive: {fmt_time(cloud_t)} ({ui.human(int(meta.get('size', 0)))})", ui.OK))
            if os.path.exists(path):
                local_t = os.path.getmtime(path)
                warn = "  ← MÁS NUEVA que la de Drive" if local_t > cloud_t + 60 else ""
                lines.append((f"   Consola: {fmt_time(local_t)}{warn}", ui.BAD if warn else ui.DIM))
            else:
                lines.append(("   Consola: no existe", ui.DIM))
        if len(lines) > 11:
            lines = lines[:10] + [(f"   … y {len(files)} archivos en total", ui.DIM)]
        lines += [("", ui.FG), ("Se reemplazará la partida de la consola. Antes se guarda una copia en "
                                  "SD1/anbernic/respaldo_nube.", ui.WARN)]
        if not self.confirm("Restaurar desde Drive", lines, yes="A: Restaurar"):
            return
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        try:
            data = self.online(lambda: [(p, self.drv.download(m["id"])) for p, m in files])
            if data is None:
                return
            for path, content in data:
                if os.path.exists(path):
                    dst = os.path.join(LOCAL_BACKUP, stamp) + path
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(path, dst)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + ".nube_tmp"
                with open(tmp, "wb") as f:
                    f.write(content)
                os.replace(tmp, path)
            os.sync()
        except OSError as e:
            self.message("Restaurar", f"No se pudo escribir la partida.\n{e}", ui.BAD)
            return
        self.message("Restaurar", f"¡Restaurado!\n{game}\n\nCopia de lo anterior en:\nSD1/anbernic/respaldo_nube/{stamp}", ui.OK)

    # ---------- account ----------
    def account(self):
        if not self.drv.linked():
            self.link()
            return
        if self.confirm("Cuenta de Google", [("La consola está vinculada a tu Google Drive.", ui.OK),
                                             ("¿Quieres desvincularla? Tus partidas en Drive no se borran.", ui.FG)],
                        yes="A: Desvincular", no="B: Volver"):
            self.drv.unlink()
            self.message("Cuenta de Google", "Consola desvinculada.")

    def run(self):
        sel = 0
        while True:
            status = ("vinculada", ui.OK) if self.drv.linked() else ("sin vincular", ui.WARN)
            items = [("Subir todo a Google Drive", "", None),
                     ("Restaurar un juego", "", None),
                     ("Cuenta de Google", status[0], status[1]),
                     ("Salir", "", None)]
            sel = self.choose("Respaldo en Google Drive", items, hint="A: Elegir     B / MENU: Salir", start=sel)
            if sel is None or sel == 3:
                return
            [self.upload_all, self.restore, self.account][sel]()

    def close(self):
        self.inp.close()
        self.scr.close()


def cli():
    """Testing over SSH: python3 main.py --scan | --remote"""
    if sys.argv[1] == "--scan":
        for path, info in catalog.scan():
            print(" | ".join(info), "|", path)
    elif sys.argv[1] == "--remote":
        for path, meta in sorted(drive.Drive(APP_DIR).list_saves().items()):
            print(meta.get("md5Checksum"), path)


def main():
    if len(sys.argv) > 1:
        return cli()
    app = App()
    try:
        app.run()
    except Quit:
        pass
    finally:
        app.close()


if __name__ == "__main__":
    main()
