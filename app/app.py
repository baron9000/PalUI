import configparser
import os
import tarfile
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests
from flask import Flask, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("PALUI_SECRET_KEY", "palui-dev-key")

CONFIG_DIR = os.environ.get(
    "PALWORLD_CONFIG_DIR", "/palworld/Pal/Saved/Config/LinuxServer"
)
PALWORLD_SETTINGS_PATH = os.path.join(CONFIG_DIR, "PalWorldSettings.ini")
ENGINE_SETTINGS_PATH = os.path.join(CONFIG_DIR, "Engine.ini")
PALWORLD_ROOT_DIR = os.environ.get("PALWORLD_ROOT_DIR", "/palworld")
PALWORLD_SAVE_ROOT = os.environ.get("PALWORLD_SAVE_ROOT", "/palworld/Pal/Saved")
BACKUP_DIR = os.environ.get("PALWORLD_BACKUP_DIR", "/palworld/backups")

PALWORLD_API_BASE_URL = os.environ.get("PALWORLD_API_BASE_URL", "http://host.docker.internal:8212")
PALWORLD_API_TOKEN = os.environ.get("PALWORLD_API_TOKEN", "")
PALWORLD_API_TOKEN_HEADER = os.environ.get("PALWORLD_API_TOKEN_HEADER", "Authorization")
PALWORLD_API_TOKEN_PREFIX = os.environ.get("PALWORLD_API_TOKEN_PREFIX", "Bearer")
PALWORLD_API_TIMEOUT = float(os.environ.get("PALWORLD_API_TIMEOUT", "8"))

FIELD_SEP = "||"
OPTION_SECTION_KEY = "__OPTION_SETTINGS__"

# Heuristics for better inputs in Palworld settings.
SLIDER_RULES = {
    "DayTimeSpeedRate": (0.1, 5.0, 0.1),
    "NightTimeSpeedRate": (0.1, 5.0, 0.1),
    "ExpRate": (0.1, 20.0, 0.1),
    "PalCaptureRate": (0.1, 5.0, 0.1),
    "PalSpawnNumRate": (0.1, 5.0, 0.1),
    "PalDamageRateAttack": (0.1, 5.0, 0.1),
    "PalDamageRateDefense": (0.1, 5.0, 0.1),
    "PlayerDamageRateAttack": (0.1, 5.0, 0.1),
    "PlayerDamageRateDefense": (0.1, 5.0, 0.1),
    "PlayerStomachDecreaceRate": (0.1, 5.0, 0.1),
    "PlayerStaminaDecreaceRate": (0.1, 5.0, 0.1),
    "PlayerAutoHPRegeneRate": (0.1, 5.0, 0.1),
    "PlayerAutoHpRegeneRateInSleep": (0.1, 5.0, 0.1),
    "PalStomachDecreaceRate": (0.1, 5.0, 0.1),
    "PalStaminaDecreaceRate": (0.1, 5.0, 0.1),
    "PalAutoHPRegeneRate": (0.1, 5.0, 0.1),
    "PalAutoHpRegeneRateInSleep": (0.1, 5.0, 0.1),
    "BuildObjectDamageRate": (0.1, 5.0, 0.1),
    "BuildObjectDeteriorationDamageRate": (0.0, 5.0, 0.1),
    "CollectionDropRate": (0.1, 5.0, 0.1),
    "CollectionObjectHpRate": (0.1, 5.0, 0.1),
    "CollectionObjectRespawnSpeedRate": (0.1, 5.0, 0.1),
    "EnemyDropItemRate": (0.1, 5.0, 0.1),
}

ENUM_RULES = {
    "Difficulty": ["None", "Easy", "Normal", "Hard"],
    "DeathPenalty": ["None", "Item", "ItemAndEquipment", "All"],
}


@dataclass
class FieldMeta:
    input_type: str
    value: str
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    enum_values: list[str] | None = None


def config_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    return parser


def load_ini(path: str) -> configparser.ConfigParser:
    parser = config_parser()
    if os.path.exists(path):
        parser.read(path)
    return parser


def save_ini(path: str, parser: configparser.ConfigParser) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        parser.write(handle)


def split_top_level_csv(raw: str) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    depth = 0
    in_quote = False

    for ch in raw:
        if ch == '"':
            in_quote = not in_quote
            current.append(ch)
            continue

        if not in_quote:
            if ch in "([{" :
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            elif ch == "," and depth == 0:
                token = "".join(current).strip()
                if token:
                    out.append(token)
                current = []
                continue

        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        out.append(tail)
    return out


def parse_option_settings(raw: str) -> OrderedDict[str, str]:
    content = raw.strip()
    if content.startswith("(") and content.endswith(")"):
        content = content[1:-1]

    parsed: OrderedDict[str, str] = OrderedDict()
    for token in split_top_level_csv(content):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def serialize_option_settings(items: OrderedDict[str, str]) -> str:
    body = ",".join(f"{k}={v}" for k, v in items.items())
    return f"({body})"


def infer_field_meta(key: str, value: str) -> FieldMeta:
    val = value.strip()
    lower = val.lower()

    if lower in {"true", "false"}:
        return FieldMeta(input_type="bool", value=lower)

    if key in ENUM_RULES:
        return FieldMeta(input_type="enum", value=val, enum_values=ENUM_RULES[key])

    try:
        float_val = float(val)
        if key in SLIDER_RULES:
            min_value, max_value, step = SLIDER_RULES[key]
            return FieldMeta(
                input_type="slider",
                value=str(float_val),
                min_value=min_value,
                max_value=max_value,
                step=step,
            )
        return FieldMeta(input_type="number", value=str(float_val), step=0.1)
    except ValueError:
        pass

    if key.endswith("Rate"):
        return FieldMeta(input_type="slider", value=val, min_value=0.1, max_value=5.0, step=0.1)

    return FieldMeta(input_type="text", value=val)


def make_field_name(file_name: str, section: str, key: str) -> str:
    return FIELD_SEP.join([file_name, section, key])


def parse_field_name(name: str) -> tuple[str, str, str] | None:
    parts = name.split(FIELD_SEP)
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def parser_to_ui_model(file_name: str, parser: configparser.ConfigParser) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []

    for section_name in parser.sections():
        fields: list[dict[str, Any]] = []
        for key, value in parser.items(section_name):
            if file_name == "PalWorldSettings.ini" and key == "OptionSettings":
                option_items = parse_option_settings(value)
                option_fields: list[dict[str, Any]] = []
                for opt_key, opt_val in option_items.items():
                    meta = infer_field_meta(opt_key, opt_val)
                    option_fields.append(
                        {
                            "key": opt_key,
                            "value": meta.value,
                            "input_type": meta.input_type,
                            "min_value": meta.min_value,
                            "max_value": meta.max_value,
                            "step": meta.step,
                            "enum_values": meta.enum_values,
                            "field_name": make_field_name(file_name, OPTION_SECTION_KEY, opt_key),
                        }
                    )
                sections.append(
                    {
                        "name": f"{section_name} - OptionSettings",
                        "raw_name": section_name,
                        "is_option_settings": True,
                        "fields": option_fields,
                    }
                )
                continue

            meta = infer_field_meta(key, value)
            fields.append(
                {
                    "key": key,
                    "value": meta.value,
                    "input_type": meta.input_type,
                    "min_value": meta.min_value,
                    "max_value": meta.max_value,
                    "step": meta.step,
                    "enum_values": meta.enum_values,
                    "field_name": make_field_name(file_name, section_name, key),
                }
            )

        if fields:
            sections.append(
                {
                    "name": section_name,
                    "raw_name": section_name,
                    "is_option_settings": False,
                    "fields": fields,
                }
            )

    return sections


def get_auth_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if PALWORLD_API_TOKEN:
        token = PALWORLD_API_TOKEN
        if PALWORLD_API_TOKEN_PREFIX:
            token = f"{PALWORLD_API_TOKEN_PREFIX} {PALWORLD_API_TOKEN}".strip()
        headers[PALWORLD_API_TOKEN_HEADER] = token
    return headers


def request_json(method: str, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{PALWORLD_API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    response = requests.request(
        method=method,
        url=url,
        headers=get_auth_headers(),
        json=payload,
        timeout=PALWORLD_API_TIMEOUT,
    )
    response.raise_for_status()
    if not response.content:
        return {"ok": True, "status": response.status_code}
    try:
        return response.json()
    except ValueError:
        return {"ok": True, "status": response.status_code, "text": response.text}


def call_first_success(
    method: str,
    endpoints: list[str],
    payloads: list[dict[str, Any] | None],
) -> tuple[bool, dict[str, Any]]:
    errors: list[str] = []
    for endpoint in endpoints:
        for payload in payloads:
            try:
                return True, request_json(method, endpoint, payload)
            except requests.RequestException as err:
                errors.append(f"{endpoint} ({payload}): {err}")
    return False, {"errors": errors}


def fetch_statistics() -> tuple[bool, dict[str, Any]]:
    return call_first_success(
        "GET",
        [
            "/v1/api/server/statistics",
            "/v1/api/statistics",
            "/v1/api/metrics",
            "/v1/api/info",
        ],
        [None],
    )


def run_announcement(message: str) -> tuple[bool, dict[str, Any]]:
    return call_first_success(
        "POST",
        ["/v1/api/announce", "/v1/api/server/announce"],
        [{"message": message}, {"text": message}],
    )


def run_restart(message: str) -> tuple[bool, dict[str, Any]]:
    return call_first_success(
        "POST",
        ["/v1/api/restart", "/v1/api/server/restart"],
        [{"message": message}, {"text": message}, None],
    )


def run_shutdown(message: str) -> tuple[bool, dict[str, Any]]:
    return call_first_success(
        "POST",
        ["/v1/api/shutdown", "/v1/api/server/shutdown"],
        [{"message": message}, {"text": message}, None],
    )


def run_kick(player_id: str, reason: str) -> tuple[bool, dict[str, Any]]:
    return call_first_success(
        "POST",
        ["/v1/api/kick", "/v1/api/player/kick"],
        [
            {"playerId": player_id, "reason": reason},
            {"steamId": player_id, "reason": reason},
            {"player": player_id, "reason": reason},
        ],
    )


def run_ban(player_id: str, reason: str) -> tuple[bool, dict[str, Any]]:
    return call_first_success(
        "POST",
        ["/v1/api/ban", "/v1/api/player/ban"],
        [
            {"playerId": player_id, "reason": reason},
            {"steamId": player_id, "reason": reason},
            {"player": player_id, "reason": reason},
        ],
    )


def ensure_backup_dir() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)


def list_backups() -> list[dict[str, Any]]:
    ensure_backup_dir()
    backups: list[dict[str, Any]] = []

    for name in os.listdir(BACKUP_DIR):
        full_path = os.path.join(BACKUP_DIR, name)
        if not os.path.isfile(full_path):
            continue
        if not (name.endswith(".tar.gz") or name.endswith(".tgz")):
            continue

        stat = os.stat(full_path)
        backups.append(
            {
                "name": name,
                "size_bytes": stat.st_size,
                "modified_ts": stat.st_mtime,
            }
        )

    backups.sort(key=lambda b: b["modified_ts"], reverse=True)
    return backups


def build_backup_name() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"palworld-backup-{ts}.tar.gz"


def create_backup() -> tuple[bool, str, dict[str, Any]]:
    ensure_backup_dir()

    if not os.path.isdir(PALWORLD_ROOT_DIR):
        return False, f"Palworld root path not found: {PALWORLD_ROOT_DIR}", {}

    backup_name = build_backup_name()
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    include_paths: list[str] = []
    if os.path.isdir(PALWORLD_SAVE_ROOT):
        include_paths.append(PALWORLD_SAVE_ROOT)
    if os.path.isdir(CONFIG_DIR):
        include_paths.append(CONFIG_DIR)

    if not include_paths:
        return False, "No backup sources found for save or config directories.", {}

    with tarfile.open(backup_path, "w:gz") as archive:
        for src_path in include_paths:
            relative_arcname = os.path.relpath(src_path, PALWORLD_ROOT_DIR)
            archive.add(src_path, arcname=relative_arcname)

    size_bytes = os.path.getsize(backup_path)
    return (
        True,
        f"Backup created: {backup_name}",
        {"name": backup_name, "path": backup_path, "size_bytes": size_bytes},
    )


def is_safe_backup_name(name: str) -> bool:
    if not name:
        return False
    if "/" in name or "\\" in name:
        return False
    return name.endswith(".tar.gz") or name.endswith(".tgz")


def is_safe_extract_target(target_path: str, base_dir: str) -> bool:
    base_real = os.path.realpath(base_dir)
    target_real = os.path.realpath(target_path)
    return target_real == base_real or target_real.startswith(base_real + os.sep)


def restore_backup(backup_name: str) -> tuple[bool, str, dict[str, Any]]:
    ensure_backup_dir()

    if not is_safe_backup_name(backup_name):
        return False, "Invalid backup file name.", {}

    backup_path = os.path.join(BACKUP_DIR, backup_name)
    if not os.path.isfile(backup_path):
        return False, f"Backup not found: {backup_name}", {}

    if not os.path.isdir(PALWORLD_ROOT_DIR):
        return False, f"Palworld root path not found: {PALWORLD_ROOT_DIR}", {}

    with tarfile.open(backup_path, "r:gz") as archive:
        members = archive.getmembers()
        if not members:
            return False, "Backup archive is empty.", {}

        for member in members:
            extract_path = os.path.join(PALWORLD_ROOT_DIR, member.name)
            if not is_safe_extract_target(extract_path, PALWORLD_ROOT_DIR):
                return False, "Backup contains invalid paths.", {}

        archive.extractall(PALWORLD_ROOT_DIR)

    announce_message = f"Backup restore '{backup_name}' complete, server restarting."
    run_announcement(announce_message)
    restart_ok, restart_res = run_restart(announce_message)

    if restart_ok:
        return True, f"Backup restored: {backup_name}", {"name": backup_name}

    return (
        False,
        f"Backup restored but restart failed for: {backup_name}",
        {"name": backup_name, "restart": restart_res},
    )


def save_config_from_form(form_data: dict[str, str], checkbox_keys: set[str]) -> tuple[bool, str]:
    pal_parser = load_ini(PALWORLD_SETTINGS_PATH)
    engine_parser = load_ini(ENGINE_SETTINGS_PATH)

    option_section_name = None
    option_values: OrderedDict[str, str] = OrderedDict()

    for section_name in pal_parser.sections():
        if pal_parser.has_option(section_name, "OptionSettings"):
            option_section_name = section_name
            option_values = parse_option_settings(pal_parser.get(section_name, "OptionSettings"))
            break

    any_change = False

    for field_name, field_value in form_data.items():
        parsed = parse_field_name(field_name)
        if not parsed:
            continue

        file_name, section_name, key = parsed
        normalized_value = field_value

        if field_name in checkbox_keys:
            normalized_value = "true"

        if section_name == OPTION_SECTION_KEY:
            current = option_values.get(key)
            if current != normalized_value:
                option_values[key] = normalized_value
                any_change = True
            continue

        parser = pal_parser if file_name == "PalWorldSettings.ini" else engine_parser
        if not parser.has_section(section_name):
            parser.add_section(section_name)

        current = parser.get(section_name, key, fallback="")
        if current != normalized_value:
            parser.set(section_name, key, normalized_value)
            any_change = True

    # Checkboxes not present in request form are false.
    for field_name in checkbox_keys:
        if field_name in form_data:
            continue

        parsed = parse_field_name(field_name)
        if not parsed:
            continue

        file_name, section_name, key = parsed
        normalized_value = "false"

        if section_name == OPTION_SECTION_KEY:
            current = option_values.get(key)
            if current != normalized_value:
                option_values[key] = normalized_value
                any_change = True
            continue

        parser = pal_parser if file_name == "PalWorldSettings.ini" else engine_parser
        if not parser.has_section(section_name):
            parser.add_section(section_name)

        current = parser.get(section_name, key, fallback="")
        if current != normalized_value:
            parser.set(section_name, key, normalized_value)
            any_change = True

    if not any_change:
        return True, "No configuration changes detected."

    if option_section_name:
        pal_parser.set(
            option_section_name,
            "OptionSettings",
            serialize_option_settings(option_values),
        )

    save_ini(PALWORLD_SETTINGS_PATH, pal_parser)
    save_ini(ENGINE_SETTINGS_PATH, engine_parser)

    announce_ok, announce_res = run_announcement("Config change made, server restarting.")
    restart_ok, restart_res = run_restart("Config change made, server restarting.")

    if announce_ok and restart_ok:
        return True, "Configuration updated and restart initiated with announcement."

    return (
        False,
        (
            "Configuration saved, but Palworld API restart flow failed. "
            f"announce={announce_res} restart={restart_res}"
        ),
    )


@app.get("/")
def index():
    pal_parser = load_ini(PALWORLD_SETTINGS_PATH)
    engine_parser = load_ini(ENGINE_SETTINGS_PATH)

    configs = {
        "PalWorldSettings.ini": parser_to_ui_model("PalWorldSettings.ini", pal_parser),
        "Engine.ini": parser_to_ui_model("Engine.ini", engine_parser),
    }

    stats_ok, stats_data = fetch_statistics()
    backups = list_backups()

    return render_template(
        "index.html",
        configs=configs,
        stats_ok=stats_ok,
        stats_data=stats_data,
        backups=backups,
        api_base=PALWORLD_API_BASE_URL,
        config_dir=CONFIG_DIR,
        backup_dir=BACKUP_DIR,
    )


@app.post("/config/save")
def config_save():
    form_data = {k: v for k, v in request.form.items() if FIELD_SEP in k}
    checkbox_keys = set(request.form.getlist("__bool_fields"))

    ok, message = save_config_from_form(form_data, checkbox_keys)
    return redirect(url_for("index", status="ok" if ok else "error", message=message))


@app.get("/api/server/statistics")
def api_statistics():
    ok, data = fetch_statistics()
    return jsonify({"ok": ok, "data": data})


@app.post("/api/mod/announcement")
def api_announcement():
    message = request.form.get("message", "").strip()
    if not message:
        return jsonify({"ok": False, "error": "Message is required."}), 400

    ok, data = run_announcement(message)
    code = 200 if ok else 502
    return jsonify({"ok": ok, "data": data}), code


@app.post("/api/mod/kick")
def api_kick():
    player_id = request.form.get("player_id", "").strip()
    reason = request.form.get("reason", "").strip()
    if not player_id:
        return jsonify({"ok": False, "error": "Player ID is required."}), 400

    ok, data = run_kick(player_id, reason)
    code = 200 if ok else 502
    return jsonify({"ok": ok, "data": data}), code


@app.post("/api/mod/ban")
def api_ban():
    player_id = request.form.get("player_id", "").strip()
    reason = request.form.get("reason", "").strip()
    if not player_id:
        return jsonify({"ok": False, "error": "Player ID is required."}), 400

    ok, data = run_ban(player_id, reason)
    code = 200 if ok else 502
    return jsonify({"ok": ok, "data": data}), code


@app.post("/api/mod/restart")
def api_restart():
    message = request.form.get("message", "Server restarting.").strip()
    run_announcement(message)
    ok, data = run_restart(message)
    code = 200 if ok else 502
    return jsonify({"ok": ok, "data": data}), code


@app.post("/api/mod/shutdown")
def api_shutdown():
    message = request.form.get("message", "Server shutting down.").strip()
    run_announcement(message)
    ok, data = run_shutdown(message)
    code = 200 if ok else 502
    return jsonify({"ok": ok, "data": data}), code


@app.get("/api/backups")
def api_backups():
    return jsonify({"ok": True, "data": list_backups()})


@app.post("/api/backups/create")
def api_backups_create():
    ok, message, data = create_backup()
    code = 200 if ok else 400
    return jsonify({"ok": ok, "message": message, "data": data}), code


@app.post("/api/backups/restore")
def api_backups_restore():
    backup_name = request.form.get("backup_name", "").strip()
    ok, message, data = restore_backup(backup_name)
    code = 200 if ok else 400
    return jsonify({"ok": ok, "message": message, "data": data}), code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8005, debug=False)
