"""Minimal Google Drive client for the console: OAuth device flow + drive.file scope.

The app can only see files it created itself (drive.file). Every uploaded file keeps its
console path in `description` and the console modification time in appProperties.mtime,
so restores go back to the exact same place.
"""
import hashlib
import json
import os
import time
import uuid

import requests

SCOPE = "https://www.googleapis.com/auth/drive.file"
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
FOLDER = "application/vnd.google-apps.folder"
ROOT_NAME = "Anbernic Saves"
TIMEOUT = 30
MULTIPART_LIMIT = 4 * 1024 * 1024


class AuthNeeded(Exception):
    """No valid sign-in (never linked, revoked, or the 7-day testing token expired)."""


class AuthDenied(Exception):
    pass


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Drive:
    def __init__(self, app_dir):
        secret = next(f for f in os.listdir(app_dir) if f.startswith("client_secret") and f.endswith(".json"))
        with open(os.path.join(app_dir, secret)) as f:
            data = json.load(f)
        client = data.get("installed") or data.get("web") or data
        self.client_id, self.client_secret = client["client_id"], client["client_secret"]
        self.token_path = os.path.join(app_dir, "token.json")
        self.token = None
        if os.path.exists(self.token_path):
            with open(self.token_path) as f:
                self.token = json.load(f)
        self.http = requests.Session()
        self._folders = {}

    # ---------- sign-in ----------
    def linked(self):
        return bool(self.token and self.token.get("refresh_token"))

    def _save_token(self, tok):
        tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
        if self.token and "refresh_token" not in tok:
            tok["refresh_token"] = self.token.get("refresh_token")
        self.token = tok
        tmp = self.token_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(tok, f)
        os.replace(tmp, self.token_path)

    def unlink(self):
        if self.token:
            try:
                self.http.post("https://oauth2.googleapis.com/revoke",
                               params={"token": self.token.get("refresh_token")}, timeout=10)
            except requests.RequestException:
                pass
        self.token = None
        if os.path.exists(self.token_path):
            os.remove(self.token_path)

    def start_device_flow(self):
        r = self.http.post(DEVICE_URL, data={"client_id": self.client_id, "scope": SCOPE}, timeout=TIMEOUT)
        r.raise_for_status()
        flow = r.json()
        flow["deadline"] = time.time() + int(flow.get("expires_in", 1800))
        return flow  # verification_url, user_code, device_code, interval

    def poll_device_flow(self, flow):
        """One poll. True = linked, False = still waiting. Raises AuthDenied / AuthNeeded (expired)."""
        r = self.http.post(TOKEN_URL, data={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "device_code": flow["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, timeout=TIMEOUT)
        body = r.json()
        if r.ok:
            self._save_token(body)
            return True
        err = body.get("error")
        if err == "authorization_pending":
            return False
        if err == "slow_down":
            flow["interval"] = int(flow.get("interval", 5)) + 5
            return False
        if err == "access_denied":
            raise AuthDenied()
        raise AuthNeeded(err or r.text)

    def _access_token(self):
        if not self.linked():
            raise AuthNeeded("not linked")
        if time.time() < self.token.get("expires_at", 0):
            return self.token["access_token"]
        r = self.http.post(TOKEN_URL, data={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "refresh_token": self.token["refresh_token"], "grant_type": "refresh_token"}, timeout=TIMEOUT)
        if r.status_code in (400, 401):
            # invalid_grant: revoked or (testing app) older than 7 days -> link again
            self.token = None
            if os.path.exists(self.token_path):
                os.remove(self.token_path)
            raise AuthNeeded(r.text)
        r.raise_for_status()
        self._save_token(r.json())
        return self.token["access_token"]

    def _req(self, method, url, **kw):
        for attempt in range(2):
            headers = kw.pop("headers", {})
            headers["Authorization"] = f"Bearer {self._access_token()}"
            r = self.http.request(method, url, headers=headers, timeout=TIMEOUT, **kw)
            if r.status_code == 401 and attempt == 0:
                self.token["expires_at"] = 0  # force a refresh and retry once
                kw["headers"] = {k: v for k, v in headers.items() if k != "Authorization"}
                continue
            r.raise_for_status()
            return r

    # ---------- folders ----------
    def _find_or_create(self, name, parent):
        q = (f"name = '{name.replace(chr(92), chr(92) * 2).replace(chr(39), chr(92) + chr(39))}' "
             f"and mimeType = '{FOLDER}' and '{parent}' in parents and trashed = false")
        found = self._req("GET", f"{API}/files", params={"q": q, "fields": "files(id)", "spaces": "drive"}).json()["files"]
        if found:
            return found[0]["id"]
        meta = {"name": name, "mimeType": FOLDER, "parents": [parent]}
        return self._req("POST", f"{API}/files", json=meta, params={"fields": "id"}).json()["id"]

    def folder(self, parts):
        """Drive folder id for ['RetroArch', 'GBA'] under 'Anbernic Saves' (created on demand)."""
        key = tuple(parts)
        if key in self._folders:
            return self._folders[key]
        parent = self.folder(parts[:-1]) if parts else None
        fid = self._find_or_create(parts[-1], parent) if parts else self._find_or_create(ROOT_NAME, "root")
        self._folders[key] = fid
        return fid

    # ---------- files ----------
    def list_saves(self):
        """All save files this app uploaded: {console path: file metadata}."""
        out, token = {}, None
        while True:
            params = {"q": f"mimeType != '{FOLDER}' and trashed = false", "pageSize": 1000, "spaces": "drive",
                      "fields": "nextPageToken, files(id, name, md5Checksum, size, description, modifiedTime, appProperties)"}
            if token:
                params["pageToken"] = token
            data = self._req("GET", f"{API}/files", params=params).json()
            for f in data.get("files", []):
                path = f.get("description") or ""
                if path.startswith("/mnt/"):
                    out[path] = f
            token = data.get("nextPageToken")
            if not token:
                return out

    def upload(self, path, parts, existing=None):
        """Creates or updates the Drive copy of `path`. Updates keep Drive's revision history."""
        with open(path, "rb") as f:
            content = f.read()
        meta = {"description": path, "appProperties": {"mtime": str(int(os.path.getmtime(path)))}}
        if not existing:
            meta.update(name=os.path.basename(path), parents=[self.folder(parts)])
        if len(content) > MULTIPART_LIMIT:
            return self._upload_resumable(meta, content, existing)
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
                f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + content + \
            f"\r\n--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/related; boundary={boundary}"}
        params = {"uploadType": "multipart", "fields": "id, md5Checksum"}
        if existing:
            r = self._req("PATCH", f"{UPLOAD}/files/{existing['id']}", params=params, headers=headers, data=body)
        else:
            r = self._req("POST", f"{UPLOAD}/files", params=params, headers=headers, data=body)
        return r.json()

    def _upload_resumable(self, meta, content, existing):
        """Drive only takes multipart uploads up to 5 MB; bigger files (save states) go resumable."""
        params = {"uploadType": "resumable", "fields": "id, md5Checksum"}
        headers = {"X-Upload-Content-Type": "application/octet-stream", "X-Upload-Content-Length": str(len(content))}
        if existing:
            r = self._req("PATCH", f"{UPLOAD}/files/{existing['id']}", params=params, headers=headers, json=meta)
        else:
            r = self._req("POST", f"{UPLOAD}/files", params=params, headers=headers, json=meta)
        session = r.headers["Location"]
        # Single PUT of the whole file; the session URL itself carries the authorization
        r = self.http.put(session, data=content, headers={"Content-Type": "application/octet-stream"},
                          timeout=max(TIMEOUT, len(content) // 50_000))
        r.raise_for_status()
        return r.json()

    def download(self, file_id):
        return self._req("GET", f"{API}/files/{file_id}", params={"alt": "media"}).content
