"""Administrator-owned proxy settings; credentials never leave the service."""

import json
from urllib.parse import urlsplit


class ProxySettings:
    def __init__(self, store):
        self.store = store

    def stored(self):
        with self.store.connection() as db:
            row = db.execute("SELECT value FROM settings WHERE name='proxy'").fetchone()
        return json.loads(row[0]) if row else {"url": "", "credentials": ""}

    def public(self):
        value = self.stored()
        return {"url": value["url"], "hasCredentials": bool(value["credentials"])}

    def runtime(self):
        value = self.stored()
        credentials = value.pop("credentials")
        if credentials:
            value.update(json.loads(self.store.vault.decrypt(credentials)))
        return value

    def save(self, patch):
        if not isinstance(patch, dict) or patch.keys() - {"url", "username", "password"}:
            raise ValueError("代理设置字段无效")
        value = self.stored()
        url = patch.get("url", value["url"])
        try:
            parsed = urlsplit(url)
            valid = isinstance(url, str) and len(url) <= 2048 and not any(
                c.isspace() or ord(c) < 32 for c in url
            ) and (url == "" or (
                parsed.scheme in ("http", "https") and parsed.hostname
                and parsed.port != 0 and parsed.path in ("", "/")
                and not parsed.query and not parsed.fragment
                and parsed.username is None and parsed.password is None
            ))
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise ValueError("代理地址须为不含凭据的 http:// 或 https://主机:端口")
        supplied = "username" in patch or "password" in patch
        if supplied:
            username, password = patch.get("username"), patch.get("password")
            if not all(isinstance(part, str) and len(part) <= 1024 and not any(
                ord(c) < 32 for c in part
            ) for part in (username, password)) or ":" in username or (password and not username):
                raise ValueError("请同时填写代理用户名和密码，或同时留空清除认证")
            value["credentials"] = self.store.encrypt_key(json.dumps({
                "username": username, "password": password,
            })) if username else ""
        elif url != value["url"]:
            # Never forward old credentials to a newly selected proxy host.
            value["credentials"] = ""
        value["url"] = url
        if not url:
            value["credentials"] = ""
        with self.store.connection() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('proxy', ?)", (json.dumps(value),))
        return self.public()
