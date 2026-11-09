"""独立 HTTP/WebSocket 服务：配置、认证及逐会话上游连接。"""

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from aiohttp import WSMsgType, web

from ..application.dictionary_sources import catalog, seed_public_dictionaries, source_content
from ..application.meter import SessionMeter
from ..application.session import Session
from ..diagnostics import checkpoint, mark, session_tag, span, trace_request
from ..domain.config import validate_config
from ..domain.dictionaries import FORMATS, parse_dictionary
from ..domain.events import EventStream
from ..domain.management import contract
from ..providers.legacy import PROVIDERS, test_connection
from ..storage.auth import AuthError
from ..storage.hotwords import HotwordConflict
from ..storage.key_vault import VaultError
from ..storage.public_dictionaries import PublicDictionaryConflict
from ..storage.usage import UsageError

AUDIO = {"encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1}
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")


class PortalError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


async def request_object(request):
    body = await request.json()
    if not isinstance(body, dict):
        raise PortalError("INVALID_REQUEST", "请求体必须是 JSON 对象")
    return body


@web.middleware
async def boundary(request, handler):
    request_id = secrets.token_hex(8)
    try:
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
    except (PortalError, UsageError, AuthError) as error:
        response = web.json_response(
            {"error": {"code": error.code, "message": error.message, "requestId": request_id}},
            status=error.status,
        )
    except VaultError as error:
        response = web.json_response(
            {"error": {"code": "KEY_UNAVAILABLE", "message": str(error), "requestId": request_id}},
            status=409,
        )
    except (HotwordConflict, PublicDictionaryConflict) as error:
        response = web.json_response(
            {
                "error": {
                    "code": getattr(error, "code", "HOTWORDS_CONFLICT"),
                    "message": str(error),
                    "requestId": request_id,
                }
            },
            status=409,
        )
    except json.JSONDecodeError:
        response = web.json_response(
            {
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "请求 JSON 无效",
                    "requestId": request_id,
                }
            },
            status=400,
        )
    except ValueError as error:
        response = web.json_response(
            {"error": {"code": "INVALID_REQUEST", "message": str(error), "requestId": request_id}},
            status=400,
        )
    except (TypeError, KeyError):
        response = web.json_response(
            {
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "请求参数无效",
                    "requestId": request_id,
                }
            },
            status=400,
        )
    if not isinstance(response, web.WebSocketResponse):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Cache-Control"] = "no-store"
    return response


def loopback(host):
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host or "")
        return (getattr(address, "ipv4_mapped", None) or address).is_loopback
    except ValueError:
        return False


class Portal:
    def __init__(self, store, factory=None, max_sessions=8, ticket_ttl=30, listen_host="127.0.0.1"):
        self.store, self.listen_host = store, listen_host
        seed_public_dictionaries(store.public_dictionaries)
        self.factory = factory or (
            lambda profile: PROVIDERS[profile["provider"]]({
                **profile["configuration"],
                "_proxy": self.store.proxy.runtime()
                if profile["configuration"].get("useProxy") else None,
            })
        )
        self.sessions = {}
        self.max_sessions, self.ticket_ttl = max_sessions, ticket_ttl
        self.ui_tickets = {}
        self.setup_challenges = {}
        self.billing_locks = {}

    def authenticate(self, request, admin=False):
        key = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if admin:
            self.browser_origin(request)
            authorized = self.store.auth.authorized(key)
        else:
            authorized = not self.store.auth.authorized(key) and self.store.authorize_asr(key)
        if not authorized:
            raise PortalError("AUTH_FAILED", "Portal 接入凭据无效", 401)
        return hashlib.sha256(key.encode()).hexdigest()

    def browser_origin(self, request):
        # Loopback installations must not be reachable through a DNS-rebinding
        # hostname. No forwarded header is trusted for local enrollment/setup.
        if loopback(self.listen_host) and not loopback(request.url.host):
            raise PortalError("ORIGIN_REJECTED", "请通过本机 Portal 地址访问管理页面", 403)
        origin = request.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.netloc.casefold() != request.host.casefold()
            ):
                raise PortalError("ORIGIN_REJECTED", "管理请求来源无效", 403)

    def native_local(self, request):
        if (
            not loopback(request.remote)
            or not loopback(request.url.host)
            or request.headers.get("Origin") is not None
            or request.headers.get("Sec-Fetch-Site") is not None
        ):
            raise PortalError("LOCAL_CLIENT_REQUIRED", "此接口仅允许本机输入法发起配对", 403)

    async def auth_status(self, request):
        self.browser_origin(request)
        initialized = self.store.auth.initialized()
        result = {"initialized": initialized, "passwordMinLength": 12}
        if not initialized:
            now = time.monotonic()
            self.setup_challenges = {
                key: value for key, value in self.setup_challenges.items() if value[0] > now
            }
            if len(self.setup_challenges) >= 128:
                raise PortalError("AUTH_RATE_LIMITED", "初始化请求过多，请稍后重试", 429)
            nonce = secrets.token_urlsafe(32)
            self.setup_challenges[nonce] = (now + 600, request.remote, request.host)
            result["setupChallenge"] = nonce
        return web.json_response(result)

    async def auth_setup(self, request):
        self.browser_origin(request)
        if self.store.auth.initialized():
            raise AuthError("ALREADY_INITIALIZED", "管理密码已经设置，请登录", 409)
        if request.content_type != "application/json":
            raise PortalError("INVALID_REQUEST", "请使用 JSON 请求", 415)
        body = await request_object(request)
        challenge = body.get("setupChallenge")
        entry = self.setup_challenges.pop(challenge, None) if isinstance(challenge, str) else None
        if (
            entry is None
            or entry[0] <= time.monotonic()
            or entry[1:] != (request.remote, request.host)
        ):
            raise PortalError("SETUP_CHALLENGE_EXPIRED", "首次设置页面已失效，请刷新后重试", 403)
        self.store.auth.limit("setup", request.remote or "unknown")
        password, confirmation = body.get("password"), body.get("confirmPassword")
        if not isinstance(password, str) or password != confirmation:
            raise PortalError("INVALID_PASSWORD", "两次输入的密码不一致")
        code = body.get("pairingCode")
        if code is not None and (not isinstance(code, str) or len(code) != 10):
            raise PortalError("INVALID_REQUEST", "输入法配对码无效")
        result = await asyncio.to_thread(self.store.auth.setup, password, code)
        return web.json_response(result, status=201)

    async def auth_login(self, request):
        self.browser_origin(request)
        if request.content_type != "application/json":
            raise PortalError("INVALID_REQUEST", "请使用 JSON 请求", 415)
        body = await request_object(request)
        result = await asyncio.to_thread(
            self.store.auth.login, body.get("password"), request.remote or "unknown"
        )
        return web.json_response(result)

    async def auth_logout(self, request):
        self.authenticate(request, admin=True)
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        self.store.auth.logout(token)
        return web.json_response({"ok": True})

    async def input_pairing_start(self, request):
        self.native_local(request)
        if request.content_type != "application/json":
            raise PortalError("INVALID_REQUEST", "请使用 JSON 请求", 415)
        body = await request_object(request)
        result = self.store.auth.start_pairing(body.get("clientId"), request.remote or "unknown")
        return web.json_response(result, status=201)

    async def input_pairing_claim(self, request):
        self.native_local(request)
        body = await request_object(request)
        identity, token = request.match_info["id"], body.get("claimToken")
        if request.path.endswith("/ack"):
            self.store.auth.acknowledge_pairing(identity, token)
            return web.json_response({"ok": True})
        return web.json_response(self.store.auth.claim_pairing(identity, token))

    async def input_pairing_admin(self, request):
        self.authenticate(request, admin=True)
        if request.method == "GET":
            return web.json_response(self.store.auth.pending_pairing(request.query.get("code", "")))
        body = await request_object(request)
        code = body.get("code")
        if not isinstance(code, str) or len(code) != 10:
            raise PortalError("INVALID_REQUEST", "输入法配对码无效")
        return web.json_response(self.store.auth.approve_pairing(code))

    async def admin_asr_keys(self, request):
        self.authenticate(request, admin=True)
        if request.method == "GET":
            return web.json_response({"keys": self.store.asr_keys()})
        body = await request.json()
        if not isinstance(body, dict):
            raise PortalError("INVALID_REQUEST", "ASR Key 创建体必须是对象")
        return web.json_response(self.store.create_asr_key(body.get("title")), status=201)

    async def revoke_asr_key(self, request):
        self.authenticate(request, admin=True)
        digest = self.store.revoke_asr_key(request.match_info["id"])
        if digest is None:
            raise PortalError("KEY_NOT_FOUND", "ASR Key 不存在", 404)
        # Revoke both pending tickets and currently active recognition sessions.
        for session in list(self.sessions.values()):
            if session.owner == digest:
                session.cancelled = True
                await session.emit("session.cancelled")
                if session.ws is not None and session.ws.prepared:
                    await session.ws.close()
                elif session.ws is None:
                    self.sessions.pop(session.id, None)
                    self.store.usage.finish(session.id, "cancelled", "KEY_REVOKED")
        return web.json_response({"ok": True})

    async def key_quota(self, request):
        self.authenticate(request, admin=True)
        identity = request.match_info["id"]
        if self.store.asr_key(identity) is None:
            raise PortalError("KEY_NOT_FOUND", "ASR Key 不存在", 404)
        return web.json_response(
            self.store.usage.update_quota("key", identity, await request_object(request))
        )

    async def profile_quota(self, request):
        self.authenticate(request, admin=True)
        identity = request.match_info["id"]
        if self.store.get(identity) is None:
            raise PortalError("PROFILE_NOT_FOUND", "识别配置不存在", 404)
        return web.json_response(
            self.store.usage.update_quota("profile", identity, await request_object(request))
        )

    async def usage(self, request):
        self.authenticate(request, admin=True)

        def timestamp(value, default):
            if value is None:
                return default
            try:
                return float(value)
            except ValueError:
                try:
                    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if moment.tzinfo is None:
                        moment = moment.replace(tzinfo=timezone.utc)
                    return moment.timestamp()
                except ValueError:
                    raise ValueError("统计时间请使用 Unix 秒数或 ISO 8601 格式") from None

        end = timestamp(request.query.get("to"), time.time())
        start = timestamp(request.query.get("from"), end - 7 * 86400)
        return web.json_response(
            self.store.usage.statistics(
                start,
                end,
                request.query.get("bucket", "day"),
                request.query.get("keyId"),
                request.query.get("profileId"),
                request.query.get("timezone", "UTC"),
            )
        )

    async def reveal_asr_key(self, request):
        self.authenticate(request, admin=True)
        identity = request.match_info["id"]
        if self.store.asr_key(identity) is None:
            raise PortalError("KEY_NOT_FOUND", "ASR Key 不存在", 404)
        return web.json_response({"id": identity, "key": self.store.reveal_asr_key(identity)})

    async def recover_asr_key(self, request):
        self.authenticate(request, admin=True)
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("key"), str):
            raise PortalError("INVALID_REQUEST", "请提供原始 ASR Key")
        identity = request.match_info["id"]
        record = self.store.asr_key(identity)
        if record is None:
            raise PortalError("KEY_NOT_FOUND", "ASR Key 不存在", 404)
        if record["revoked"]:
            raise PortalError("KEY_REVOKED", "不能恢复已撤销的 Key", 409)
        # Compare before storing: a supplied value can never replace another key.
        if (
            self.store.authorize_asr(body["key"])
            != hashlib.sha256(body["key"].encode()).hexdigest()
        ):
            raise PortalError("KEY_MISMATCH", "原值与此 Key 不匹配", 400)
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT id FROM asr_keys WHERE digest=?",
                (hashlib.sha256(body["key"].encode()).hexdigest(),),
            ).fetchone()
        if row is None or row["id"] != identity:
            raise PortalError("KEY_MISMATCH", "原值与此 Key 不匹配", 400)
        self.store.remember_asr_key(body["key"])
        return web.json_response({"ok": True, "id": identity})

    async def health(self, request):
        return web.json_response(
            {
                "status": "ok",
                "service": "OpenASRPortal",
                "initialized": self.store.auth.initialized(),
                "protocolVersion": 1,
                "managementPage": "/admin",
            }
        )

    async def capabilities(self, request):
        self.authenticate(request)
        return web.json_response(
            {
                "protocolVersion": 1,
                "audio": AUDIO,
                "maxSessions": self.max_sessions,
                "maxRecordingMs": 300000,
                "resumable": False,
                "hotwords": {
                    "version": 1,
                    "path": "/v1/hotwords",
                    "scope": "access-key",
                    "dictionaries": True,
                    "catalogPath": "/v1/hotwords/catalog",
                    "personalTableOnly": True,
                    "recommendationWords": True,
                    "publicDictionaries": True,
                    "publicDownloadPath": "/v1/hotwords/catalog/{sourceId}",
                },
                "events": [
                    "session.ready",
                    "transcript.partial",
                    "transcript.final",
                    "session.finished",
                    "session.cancelled",
                    "session.error",
                ],
            }
        )

    async def profiles(self, request):
        self.authenticate(request)
        return web.json_response({"profiles": self.store.list(), **self.store.settings()})

    def hotword_owner(self, request):
        if request.path.startswith("/v1/admin/"):
            self.authenticate(request, admin=True)
            record = self.store.asr_key_owner(request.match_info["id"])
            if record is None:
                raise PortalError("KEY_NOT_FOUND", "ASR Key 不存在", 404)
            if record["revoked"]:
                raise PortalError("KEY_REVOKED", "此 Key 已撤销", 409)
            return record["digest"]
        return self.authenticate(request)

    def hotword_listing(self, request, owner):
        profile_id = request.query.get("profileId") or self.store.settings()["defaultProfileId"]
        profile = self.store.get(profile_id) if profile_id else None
        if profile_id and profile is None:
            raise PortalError("PROFILE_NOT_FOUND", "识别配置不存在", 404)
        listing = self.store.hotwords.listing(owner, profile["provider"] if profile else None)
        return {**listing, "profileId": profile_id or None}

    async def personal_hotwords(self, request):
        owner = self.hotword_owner(request)
        if request.method == "PATCH":
            self.hotword_listing(request, owner)  # Validate the selected profile before a write.
            body = await request_object(request)
            if body.keys() - {"revision", "settings"}:
                raise ValueError("未知的热词更新字段")
            self.store.hotwords.update(owner, body.get("settings"), body.get("revision"))
        return web.json_response(self.hotword_listing(request, owner))

    async def clear_hotword_statistics(self, request):
        self.store.hotwords.clear_statistics(self.hotword_owner(request))
        return web.json_response({"ok": True})

    async def dictionary_catalog(self, request):
        self.authenticate(request, admin=request.path.startswith("/v1/admin/"))
        return web.json_response(catalog(self.store.public_dictionaries))

    async def resolve_dictionary_source(self, identity):
        if not isinstance(identity, str) or not ID.fullmatch(identity):
            raise ValueError("公开词库来源 ID 无效")
        record = self.store.public_dictionaries.get(identity)
        if record and record["enabled"]:
            parsed = {key: record[key] for key in ("format", "words", "report")}
            source = {
                key: record[key]
                for key in (
                    "id",
                    "title",
                    "description",
                    "license",
                    "homepage",
                    "revision",
                    "sha256",
                )
            }
            return parsed, source
        try:
            content, format_name, source = await source_content(identity)
        except httpx.HTTPError:
            raise PortalError(
                "DICTIONARY_DOWNLOAD_FAILED", "公开词库下载失败，可下载原文件后上传", 502
            ) from None
        return await asyncio.to_thread(parse_dictionary, content, format_name), source

    async def public_recommendation(self, request):
        self.authenticate(request, admin=request.path.startswith("/v1/admin/"))
        identity = request.match_info["source_id"]
        if identity not in {
            row["id"] for row in catalog(self.store.public_dictionaries)["sources"]
        }:
            raise PortalError("PUBLIC_DICTIONARY_NOT_FOUND", "公共热词表不存在或未发布", 404)
        parsed, source = await self.resolve_dictionary_source(identity)
        return web.json_response({**parsed, "source": source, "recommendationOnly": True})

    async def public_dictionary_payload(self, body):
        if "sourceId" in body:
            if "content" in body:
                raise ValueError("请选择词表内容或联网来源之一")
            return await self.resolve_dictionary_source(body["sourceId"])
        content = body.get("content", "")
        if content == "":
            format_name = body.get("format", "auto")
            if format_name not in FORMATS:
                raise ValueError("未知的词表格式")
            parsed = {
                "format": "text",
                "words": [],
                "report": {
                    "rows": 0,
                    "wordCount": 0,
                    "skipped": 0,
                    "duplicates": 0,
                    "warnings": [],
                    "sample": [],
                },
            }
        else:
            parsed = await asyncio.to_thread(parse_dictionary, content, body.get("format", "auto"))
        return parsed, {
            "id": "admin-upload",
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }

    async def admin_public_dictionaries(self, request):
        self.authenticate(request, admin=True)
        identity = request.match_info.get("dictionary_id")
        store = self.store.public_dictionaries
        if request.method == "GET":
            if not identity:
                return web.json_response({"dictionaries": store.listing(), "maxTables": 100})
            result = store.get(identity)
            if result is None:
                raise PortalError("PUBLIC_DICTIONARY_NOT_FOUND", "公共热词表不存在", 404)
            return web.json_response(result)
        body = await request_object(request)
        metadata_fields = {"title", "description", "license", "homepage", "enabled"}
        allowed = (
            {"revision"}
            if request.method == "DELETE"
            else (
                metadata_fields
                | {"content", "format", "sourceId", "preview"}
                | ({"revision"} if identity else set())
            )
        )
        if body.keys() - allowed:
            raise ValueError("未知的公共热词表字段")
        if identity and store.get(identity) is None:
            raise PortalError("PUBLIC_DICTIONARY_NOT_FOUND", "公共热词表不存在", 404)
        if request.method == "DELETE":
            result = store.update(identity, body.get("revision"), {}, delete=True)
        else:
            if type(body.get("preview", False)) is not bool:
                raise ValueError("preview 必须为布尔值")
            parsed, source = None, None
            if not identity or "content" in body or "sourceId" in body:
                parsed, source = await self.public_dictionary_payload(body)
            elif "format" in body or body.get("preview"):
                raise ValueError("预览或格式变更须提供 content 或 sourceId")
            if body.get("preview"):
                return web.json_response({**parsed, "source": source, "recommendationOnly": True})
            metadata = {key: body[key] for key in metadata_fields if key in body}
            if identity:
                result = store.update(identity, body.get("revision"), metadata, parsed, source)
            else:
                defaults = {key: source[key] for key in metadata_fields if key in source}
                result = store.create({**defaults, **metadata}, parsed, source)
        if result is None:
            raise PortalError("PUBLIC_DICTIONARY_NOT_FOUND", "公共热词表不存在", 404)
        return web.json_response(result, status=201 if request.method == "POST" else 200)

    async def hotword_dictionaries(self, request):
        owner = self.hotword_owner(request)
        self.hotword_listing(request, owner)
        identity = request.match_info.get("dictionary_id")
        if request.method == "GET":
            result = self.store.hotwords.dictionary_words(owner, identity)
            if result is None:
                raise PortalError("DICTIONARY_NOT_FOUND", "词库不存在或不属于此 Key", 404)
            return web.json_response(result)
        body = await request_object(request)
        if identity:
            if body.keys() - {"revision", "patch"}:
                raise ValueError("未知的词库修改字段")
            changed = self.store.hotwords.change_dictionary(
                owner,
                identity,
                body.get("patch"),
                body.get("revision"),
                delete=request.method == "DELETE",
            )
            if not changed:
                raise PortalError("DICTIONARY_NOT_FOUND", "词库不存在或不属于此 Key", 404)
            return web.json_response(self.hotword_listing(request, owner))
        if body.keys() - {"revision", "title", "format", "content", "sourceId", "preview"}:
            raise ValueError("未知的词库导入字段")
        if type(body.get("preview", False)) is not bool:
            raise ValueError("preview 必须为布尔值")
        source = {"id": "upload", "sha256": ""}
        content, format_name = body.get("content"), body.get("format", "auto")
        if "sourceId" in body:
            if content is not None:
                raise ValueError("请选择上传内容或公开来源之一")
            parsed, source = await self.resolve_dictionary_source(body["sourceId"])
        else:
            parsed = await asyncio.to_thread(parse_dictionary, content, format_name)
            source["sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if body.get("preview"):
            return web.json_response(
                {
                    "format": parsed["format"],
                    "report": parsed["report"],
                    "words": parsed["words"],
                    "source": source,
                    "recommendationOnly": True,
                }
            )
        identity = await asyncio.to_thread(
            self.store.hotwords.import_dictionary,
            owner,
            body.get("title", source.get("title")),
            parsed,
            source,
            body.get("revision"),
        )
        return web.json_response(
            {
                **self.hotword_listing(request, owner),
                "importedDictionaryId": identity,
                "importReport": parsed["report"],
            },
            status=201,
        )

    async def management_contract(self, request):
        self.authenticate(request, admin=True)
        return web.json_response(contract())

    async def admin_profiles(self, request):
        self.authenticate(request, admin=True)
        if request.method == "GET":
            return web.json_response(
                {
                    "profiles": self.store.list(admin=True),
                    **self.store.settings(admin=True),
                    "managementVersion": 1,
                }
            )
        body = await request.json()
        profile_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(profile_id, str) or not ID.fullmatch(profile_id):
            raise PortalError("INVALID_PROFILE", "请填写合法且唯一的配置 id")
        if self.store.get(profile_id):
            raise PortalError("PROFILE_EXISTS", "配置 id 已存在", 409)
        title = body.get("title", profile_id)
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise PortalError("INVALID_PROFILE", "配置名称无效")
        result = self.store.save(
            profile_id, title, body.get("provider"), body.get("configuration", {})
        )
        return web.json_response(result, status=201)

    async def admin_settings(self, request):
        self.authenticate(request, admin=True)
        if request.method == "GET":
            return web.json_response(self.store.settings(admin=True))
        body = await request_object(request)
        if set(body) == {"proxy"}:
            self.store.proxy.save(body["proxy"])
            return web.json_response(self.store.settings(admin=True))
        if not body or body.keys() - {"defaultProfileId", "profileOrder"}:
            raise PortalError("INVALID_REQUEST", "未知的默认配置或排序字段")
        self.store.usage.configure_defaults(body)
        return web.json_response(self.store.settings(admin=True))

    async def ui_ticket(self, request):
        self.authenticate(request, admin=True)
        ticket = secrets.token_urlsafe(32)
        parent = request.headers.get("Authorization", "").removeprefix("Bearer ")
        self.ui_tickets[ticket] = (time.monotonic() + 60, parent)
        return web.json_response({"ticket": ticket, "expiresInMs": 60000})

    async def ui_session(self, request):
        self.browser_origin(request)
        ticket = (await request_object(request)).get("ticket", "")
        entry = self.ui_tickets.pop(ticket, None) if isinstance(ticket, str) else None
        if (
            entry is None
            or entry[0] <= time.monotonic()
            or not self.store.auth.authorized(entry[1])
        ):
            raise PortalError("AUTH_FAILED", "管理页面凭据已失效，请重新登录", 401)
        return web.json_response(self.store.auth.issue_session())

    async def management_page(self, request):
        self.browser_origin(request)
        name = request.match_info.get("file", "index.html")
        suffix = "?" + urlencode({"pair": request.query["pair"]}) if "pair" in request.query else ""
        if name == "index.html" and not self.store.auth.initialized():
            raise web.HTTPFound("/admin/setup" + suffix)
        if name == "setup":
            if self.store.auth.initialized():
                raise web.HTTPFound("/admin" + suffix)
            name = "setup.html"
        if name not in (
            "index.html",
            "app.js",
            "style.css",
            "icon.svg",
            "personal-hotwords.mjs",
            "setup.html",
            "setup.js",
            "i18n.mjs",
            "messages.mjs",
            "dynamic-messages.mjs",
            "error-messages.mjs",
        ):
            raise web.HTTPNotFound()
        response = web.FileResponse(Path(__file__).parents[1] / "presentation/web" / name)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    async def admin_profile(self, request):
        self.authenticate(request, admin=True)
        profile_id = request.match_info["id"]
        if not ID.fullmatch(profile_id):
            raise PortalError("INVALID_PROFILE", "识别配置 id 无效")
        if request.method == "DELETE":
            self.store.delete(profile_id)
            return web.json_response({"ok": True})
        if request.method == "GET":
            profile = self.store.get(profile_id)
            if profile is None:
                raise PortalError("PROFILE_NOT_FOUND", "识别配置不存在", 404)
            return web.json_response(self.store.public(profile, admin=True))
        body = await request.json()
        if not isinstance(body, dict):
            raise PortalError("INVALID_REQUEST", "配置必须为对象")
        previous = self.store.get(profile_id) or {}
        if request.method == "PATCH" and not previous:
            raise PortalError("PROFILE_NOT_FOUND", "配置不存在", 404)
        provider = body.get("provider", previous.get("provider"))
        title = body.get("title", previous.get("title", profile_id))
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise PortalError("INVALID_PROFILE", "配置标题无效")
        return web.json_response(
            self.store.save(profile_id, title, provider, body.get("configuration", {}))
        )

    async def test_profile(self, request):
        self.authenticate(request, admin=True)
        profile = self.store.get(request.match_info["id"])
        if request.can_read_body:
            body = await request.json()
            if not isinstance(body, dict):
                raise PortalError("INVALID_REQUEST", "测试配置必须为对象")
            provider = body.get("provider", profile["provider"] if profile else None)
            profile = {
                "id": request.match_info["id"],
                "provider": provider,
                "configuration": validate_config(
                    provider,
                    body.get("configuration", {}),
                    profile["configuration"]
                    if profile and profile["provider"] == provider
                    else None,
                ),
            }
        if profile is None:
            raise PortalError("PROFILE_NOT_FOUND", "识别配置不存在", 404)
        provider = self.factory(profile)
        saved = self.store.get(profile["id"]) is not None
        billing_profile = profile["id"] if saved else f"draft:{profile['provider']}:{profile['id']}"
        if not saved:
            self.store.usage.ensure_account("profile", billing_profile)
        identity = secrets.token_urlsafe(18)
        self.store.usage.new_session(identity, None, billing_profile, "probe")
        self.store.usage.activate(identity)
        meter = None
        original_open, original_send = provider.open, provider.send_audio
        if getattr(provider, "token_metered", False):
            meter = SessionMeter(self.store.usage, identity, self.billing_locks)
            provider.usage_callback = meter.response

        async def metered_open():
            if meter:
                await asyncio.wait_for(meter.start(), 20)
            await original_open()
            if not meter:
                self.store.usage.begin_call(identity)

        async def metered_send(pcm, last=False):
            accepted, scope = self.store.usage.accept_audio(identity, len(pcm))
            await original_send(pcm[:accepted], last=last or scope is not None)

        provider.open, provider.send_audio = metered_open, metered_send
        result = {}
        try:
            with self.store.connection() as db:
                self.store.usage.check_account(db, "profile", billing_profile)
            result = await test_connection(provider)
            return web.json_response(result)
        finally:
            try:
                self.store.usage.finish(identity, "finished" if result.get("ok") else "failed")
            finally:
                if meter:
                    meter.close()

    def reap(self):
        for value, entry in list(self.ui_tickets.items()):
            if entry[0] <= time.monotonic():
                self.ui_tickets.pop(value, None)
        for session_id, session in list(self.sessions.items()):
            if session.ws is None and session.expires < time.monotonic():
                self.sessions.pop(session_id, None)
                self.store.usage.finish(session_id, "expired", "TICKET_EXPIRED")

    @trace_request("create")
    async def create_session(self, request):
        with span("authenticate"):
            owner = self.authenticate(request)
        self.reap()
        body = await request.json()
        if not isinstance(body, dict):
            raise PortalError("INVALID_REQUEST", "会话请求必须为对象")
        request_id = body.get("clientRequestId", "")
        if not isinstance(request_id, str) or len(request_id) > 200:
            raise PortalError("INVALID_REQUEST", "clientRequestId 无效")
        for session in self.sessions.values():
            if request_id and session.owner == owner and session.request_id == request_id:
                if session.ws is not None:
                    raise PortalError("SESSION_STARTED", "该请求已建立识别连接", 409)
                return self.session_response(session)
        if len(self.sessions) >= self.max_sessions:
            raise PortalError("UPSTREAM_BUSY", "Portal 会话容量已满", 429)
        if body.get("audio", AUDIO) != AUDIO:
            raise PortalError("UNSUPPORTED_AUDIO", "当前支持 PCM16 / 16kHz / 单声道")
        profile_id = body.get("profileId")
        if profile_id is not None and (
            not isinstance(profile_id, str) or (profile_id and not ID.fullmatch(profile_id))
        ):
            raise PortalError("INVALID_PROFILE", "识别配置 ID 无效")
        if not profile_id:
            profile_id = self.store.settings()["defaultProfileId"]
            if not profile_id:
                with self.store.connection() as db:
                    exhausted = (
                        db.execute(
                            "SELECT value FROM settings WHERE name='defaultAutoUnavailable'"
                        ).fetchone()[0]
                        == "1"
                    )
                if exhausted:
                    raise UsageError(
                        "NO_UPSTREAM_AVAILABLE",
                        "所有上游 ASR 已停用或额度耗尽，请管理员补充额度",
                        503,
                    )
                raise PortalError("PROFILE_NOT_FOUND", "Portal 尚未设置默认识别配置", 404)
        with span("profileRead"):
            profile = self.store.get(profile_id)
        if profile is None:
            raise PortalError("PROFILE_NOT_FOUND", "识别配置不存在", 404)
        with span("quotaCheck"):
            self.store.usage.check(owner, profile)
        with span("hotwordsSelection"):
            selection = self.store.hotwords.listing(owner, profile["provider"])["selection"]
        profile["configuration"]["hotwords"] = [
            {"text": term["text"], "weight": term["weight"]} for term in selection["terms"]
        ]
        session = Session(
            secrets.token_urlsafe(18),
            owner,
            profile,
            secrets.token_urlsafe(32),
            time.monotonic() + self.ticket_ttl,
            request_id,
        )
        session.stream = EventStream(session.id)
        session_tag(session.id)
        session.hotword_selection = {
            "supported": selection["capability"]["supported"],
            "appliedCount": selection["appliedCount"],
            "omittedCount": len(selection["omitted"]),
        }
        with span("sessionPersist"):
            self.store.usage.new_session(session.id, owner, profile["id"])
        self.sessions[session.id] = session
        return self.session_response(session)

    def session_response(self, session):
        return web.json_response(
            {
                "sessionId": session.id,
                "ticket": session.ticket,
                "streamPath": f"/v1/sessions/{session.id}/stream",
                "ticketExpiresInMs": max(0, int((session.expires - time.monotonic()) * 1000)),
            },
            status=201,
        )

    async def cancel_session(self, request):
        owner = self.authenticate(request)
        session = self.sessions.get(request.match_info["id"])
        if session is not None:
            if session.owner != owner:
                raise PortalError("AUTH_FAILED", "会话不属于当前调用方", 403)
            session.cancelled = True
            await session.emit("session.cancelled")
            if session.ws is not None and session.ws.prepared:
                await session.ws.close()
            elif session.ws is None:
                self.sessions.pop(session.id, None)
                self.store.usage.finish(session.id, "cancelled")
        return web.json_response({"ok": True})

    @trace_request("stream")
    async def stream(self, request):
        session = self.sessions.get(request.match_info["id"])
        ticket = request.query.get("ticket", "")
        if (
            session is None
            or not session.ticket
            or not self.store.active_digest(session.owner)
            or not secrets.compare_digest(ticket, session.ticket)
        ):
            raise PortalError("AUTH_FAILED", "一次性连接凭据无效", 401)
        if time.monotonic() > session.expires:
            self.sessions.pop(session.id, None)
            self.store.usage.finish(session.id, "expired", "TICKET_EXPIRED")
            raise PortalError("TICKET_EXPIRED", "连接凭据已过期", 401)
        session_tag(session.id)
        ws = web.WebSocketResponse(max_msg_size=1024 * 1024, heartbeat=30)
        if not ws.can_prepare(request).ok:
            raise PortalError("INVALID_REQUEST", "需要 WebSocket 连接")
        self.store.usage.check(session.owner, session.profile)
        session.ticket = ""
        session.ws = ws
        provider = None
        meter = None
        tasks = []
        outcome, error_code = "failed", ""
        try:
            with span("localWebsocketPrepare"):
                await ws.prepare(request)
            if session.cancelled or ws.closed:
                return ws
            with span("usageActivate"):
                self.store.usage.activate(session.id)
            with span("providerConstruct"):
                provider = self.factory(session.profile)
            if getattr(provider, "token_metered", False):
                meter = SessionMeter(
                    self.store.usage, session.id, self.billing_locks
                )
                provider.usage_callback = meter.response
                await asyncio.wait_for(meter.start(), 20)
            with span("providerOpen"):
                await asyncio.wait_for(provider.open(), 20)
            if session.cancelled or ws.closed:
                return ws
            if not meter:
                with span("usageBeginCall"):
                    self.store.usage.begin_call(session.id)
            await session.emit(
                "session.ready",
                audio=AUDIO,
                textProcessing=provider.text_processing,
                finalizeTimeoutMs=int((provider.finish_timeout + 1) * 1000),
                hotwords=session.hotword_selection,
            )
            mark("readySent")
            checkpoint("ready")
            ended = asyncio.Event()

            async def upload():
                pending = bytearray()
                audio_bytes = 0

                async def send(pcm, last=False):
                    try:
                        accepted, scope = self.store.usage.accept_audio(
                            session.id, len(pcm)
                        )
                    except UsageError as error:
                        if error.code not in ("QUOTA_EXHAUSTED", "PROFILE_DISABLED"):
                            raise
                        accepted, scope = 0, "account"
                    last = last or scope is not None
                    if scope:
                        session.quota_scope = scope
                    await provider.send_audio(pcm[:accepted], last=last)
                    if accepted:
                        mark("firstUpstreamAudioSent")
                    if last:
                        ended.set()
                    return not last

                async for message in ws:
                    if message.type == WSMsgType.BINARY:
                        mark("firstClientAudioReceived")
                        if len(message.data) % 2:
                            raise PortalError("UNSUPPORTED_AUDIO", "PCM16 字节数必须为偶数")
                        audio_bytes += len(message.data)
                        if audio_bytes > 16000 * 2 * 300:
                            raise PortalError("AUDIO_LIMIT", "录音超过五分钟上限")
                        pending.extend(message.data)
                        while len(pending) >= 6400:
                            if not await send(bytes(pending[:6400])):
                                return
                            del pending[:6400]
                    elif message.type == WSMsgType.TEXT:
                        control = json.loads(message.data)
                        if not isinstance(control, dict):
                            raise PortalError("INVALID_REQUEST", "控制消息必须为对象")
                        if control.get("type") == "session.cancel":
                            session.cancelled = True
                            await session.emit("session.cancelled")
                            return
                        if control.get("type") == "audio.end":
                            mark("audioEndReceived")
                            await send(bytes(pending), last=True)
                            return
                        raise PortalError("INVALID_REQUEST", "未知的控制消息")
                raise PortalError("CLIENT_DISCONNECTED", "客户端连接已关闭")

            async def download():
                while True:
                    events, last = await provider.receive()
                    for raw in events:
                        async with session.lock:
                            if not session.cancelled:
                                event = session.stream.transcript(raw)
                                if event:
                                    if event.get("text"):
                                        mark("firstTranscript")
                                        if event["type"] == "transcript.final":
                                            mark("firstFinal")
                                    await ws.send_json(event)
                                    if event["type"] == "transcript.final":
                                        try:
                                            await asyncio.to_thread(
                                                self.store.hotwords.observe, session.owner, event
                                            )
                                        except Exception:
                                            # Statistics must never interrupt successful dictation.
                                            logging.getLogger(__name__).error(
                                                "热词统计失败，识别会话继续"
                                            )
                    if last:
                        return

            sender = asyncio.create_task(upload())
            receiver = asyncio.create_task(download())
            tasks = [sender, receiver]
            done, _ = await asyncio.wait(tasks, timeout=300, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise PortalError("SESSION_TIMEOUT", "会话超过五分钟上限")
            for task in done:
                task.result()
            if session.cancelled:
                return ws
            if sender in done and ended.is_set():
                try:
                    await asyncio.wait_for(receiver, provider.finish_timeout)
                except asyncio.TimeoutError:
                    raise PortalError("FINALIZATION_TIMEOUT", "等待最终定稿超时") from None
            elif receiver in done and not ended.is_set():
                raise PortalError("UPSTREAM_CLOSED", "上游提前结束，尚未完成音频提交")
            if not session.cancelled:
                outcome = "quota_finished" if session.quota_scope else "finished"
                await session.emit(
                    "session.finished",
                    finalCount=session.stream.final_count,
                    **(
                        {"reason": "quota_exhausted", "quotaScope": session.quota_scope}
                        if session.quota_scope
                        else {}
                    ),
                )
                mark("finishedSent")
        except Exception as error:
            error_code = getattr(error, "code", "UPSTREAM_ERROR")
            if not ws.prepared:
                raise
            if not session.cancelled:
                await session.emit(
                    "session.error",
                    code=getattr(error, "code", "UPSTREAM_ERROR"),
                    message=getattr(error, "message", "上游识别失败，请检查 Portal 配置与网络"),
                    retryable=not isinstance(error, UsageError),
                    requestId=secrets.token_hex(8),
                )
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                if provider is not None:
                    await provider.close()
            finally:
                try:
                    self.store.usage.finish(
                        session.id, "cancelled" if session.cancelled else outcome, error_code
                    )
                finally:
                    if meter:
                        meter.close()
                    self.sessions.pop(session.id, None)
                    if ws.prepared:
                        await ws.close()
        return ws

    async def lifecycle(self, app):
        self.store.usage.recover()

        async def maintenance():
            while True:
                self.reap()
                await asyncio.sleep(5)

        task = asyncio.create_task(maintenance())
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for session in list(self.sessions.values()):
            session.cancelled = True
            if session.ws is not None and session.ws.prepared:
                await session.ws.close()
            else:
                self.store.usage.finish(session.id, "interrupted", "SERVICE_SHUTDOWN")

    def app(self):
        app = web.Application(middlewares=[boundary], client_max_size=8 * 1024 * 1024)
        app.router.add_get("/health", self.health)
        app.router.add_get("/", self.management_page)
        app.router.add_get("/admin", self.management_page)
        app.router.add_get("/admin/{file}", self.management_page)
        app.router.add_get("/v1/admin/auth/status", self.auth_status)
        app.router.add_post("/v1/admin/auth/setup", self.auth_setup)
        app.router.add_post("/v1/admin/auth/login", self.auth_login)
        app.router.add_post("/v1/admin/auth/logout", self.auth_logout)
        app.router.add_post("/v1/local-input/pairings", self.input_pairing_start)
        app.router.add_post("/v1/local-input/pairings/{id}/claim", self.input_pairing_claim)
        app.router.add_post("/v1/local-input/pairings/{id}/ack", self.input_pairing_claim)
        app.router.add_get("/v1/admin/local-input-pairings", self.input_pairing_admin)
        app.router.add_post("/v1/admin/local-input-pairings", self.input_pairing_admin)
        app.router.add_get("/v1/admin/contract", self.management_contract)
        app.router.add_get("/v1/admin/profiles", self.admin_profiles)
        app.router.add_post("/v1/admin/profiles", self.admin_profiles)
        app.router.add_get("/v1/admin/settings", self.admin_settings)
        app.router.add_patch("/v1/admin/settings", self.admin_settings)
        app.router.add_get("/v1/admin/asr-keys", self.admin_asr_keys)
        app.router.add_get("/v1/admin/usage", self.usage)
        app.router.add_post("/v1/admin/asr-keys", self.admin_asr_keys)
        app.router.add_delete("/v1/admin/asr-keys/{id}", self.revoke_asr_key)
        app.router.add_patch("/v1/admin/asr-keys/{id}/quota", self.key_quota)
        app.router.add_patch("/v1/admin/profiles/{id}/quota", self.profile_quota)
        app.router.add_get("/v1/admin/asr-keys/{id}/secret", self.reveal_asr_key)
        app.router.add_post("/v1/admin/asr-keys/{id}/recover", self.recover_asr_key)
        app.router.add_post("/v1/admin/ui-tickets", self.ui_ticket)
        app.router.add_post("/v1/admin/ui-session", self.ui_session)
        app.router.add_get("/v1/capabilities", self.capabilities)
        app.router.add_get("/v1/profiles", self.profiles)
        app.router.add_get("/v1/hotwords", self.personal_hotwords)
        app.router.add_patch("/v1/hotwords", self.personal_hotwords)
        app.router.add_delete("/v1/hotwords/statistics", self.clear_hotword_statistics)
        app.router.add_get("/v1/hotwords/catalog", self.dictionary_catalog)
        app.router.add_get("/v1/admin/hotwords/catalog", self.dictionary_catalog)
        app.router.add_get("/v1/hotwords/catalog/{source_id}", self.public_recommendation)
        app.router.add_get("/v1/admin/hotwords/catalog/{source_id}", self.public_recommendation)
        for method in ("GET", "POST"):
            app.router.add_route(
                method, "/v1/admin/hotwords/public-dictionaries", self.admin_public_dictionaries
            )
        for method in ("GET", "PATCH", "DELETE"):
            app.router.add_route(
                method,
                "/v1/admin/hotwords/public-dictionaries/{dictionary_id}",
                self.admin_public_dictionaries,
            )
        app.router.add_get("/v1/admin/asr-keys/{id}/hotwords", self.personal_hotwords)
        app.router.add_patch("/v1/admin/asr-keys/{id}/hotwords", self.personal_hotwords)
        app.router.add_delete(
            "/v1/admin/asr-keys/{id}/hotwords/statistics", self.clear_hotword_statistics
        )
        for prefix in ("/v1/hotwords", "/v1/admin/asr-keys/{id}/hotwords"):
            app.router.add_post(prefix + "/dictionaries", self.hotword_dictionaries)
            app.router.add_get(prefix + "/dictionaries/{dictionary_id}", self.hotword_dictionaries)
            app.router.add_patch(
                prefix + "/dictionaries/{dictionary_id}", self.hotword_dictionaries
            )
            app.router.add_delete(
                prefix + "/dictionaries/{dictionary_id}", self.hotword_dictionaries
            )
        app.router.add_post("/v1/sessions", self.create_session)
        app.router.add_delete("/v1/sessions/{id}", self.cancel_session)
        app.router.add_get("/v1/sessions/{id}/stream", self.stream)
        for method in ("GET", "PUT", "PATCH", "DELETE"):
            app.router.add_route(method, "/v1/admin/profiles/{id}", self.admin_profile)
        app.router.add_post("/v1/admin/profiles/{id}/test", self.test_profile)

        async def options(request):
            return web.Response(status=204)

        app.router.add_route("OPTIONS", "/{path:.*}", options)
        app.cleanup_ctx.append(self.lifecycle)
        return app
