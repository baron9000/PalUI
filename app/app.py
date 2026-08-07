import configparser
import json
import os
import tarfile
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

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
CONFIG_SNAPSHOT_DIR = os.environ.get("PALWORLD_CONFIG_SNAPSHOT_DIR", "/palworld/backups/config-snapshots")
CONFIG_SNAPSHOT_POINTER = os.environ.get(
    "PALWORLD_CONFIG_SNAPSHOT_POINTER",
    os.path.join(CONFIG_SNAPSHOT_DIR, "latest.json"),
)

PALWORLD_API_BASE_URL = os.environ.get("PALWORLD_API_BASE_URL", "http://host.docker.internal:8212")
PALWORLD_API_USERNAME = os.environ.get("PALWORLD_API_USERNAME", "admin")
PALWORLD_API_PASSWORD = os.environ.get("PALWORLD_API_PASSWORD", "")
PALWORLD_API_TOKEN = os.environ.get("PALWORLD_API_TOKEN", "")
PALWORLD_API_TOKEN_HEADER = os.environ.get("PALWORLD_API_TOKEN_HEADER", "Authorization")
PALWORLD_API_TOKEN_PREFIX = os.environ.get("PALWORLD_API_TOKEN_PREFIX", "Bearer")
PALWORLD_API_TIMEOUT = float(os.environ.get("PALWORLD_API_TIMEOUT", "8"))
PALWORLD_STATS_ENDPOINT = os.environ.get("PALWORLD_STATS_ENDPOINT", "").strip()
PALWORLD_STATS_COMMAND = os.environ.get("PALWORLD_STATS_COMMAND", "info").strip()
PALWORLD_RESTART_STRATEGY = os.environ.get(
    "PALWORLD_RESTART_STRATEGY", "save-stop-then-shutdown"
).strip().lower()

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
    parser = configparser.ConfigParser(interpolation=None, strict=False)
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


def copy_file_if_exists(src: str, dst: str) -> bool:
    if not os.path.exists(src):
        return False

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as source_handle, open(dst, "wb") as dest_handle:
        dest_handle.write(source_handle.read())
    return True


def snapshot_config_files(file_paths: list[str]) -> dict[str, Any]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = os.path.join(CONFIG_SNAPSHOT_DIR, timestamp)
    os.makedirs(snapshot_dir, exist_ok=True)

    copied_files: list[str] = []
    for file_path in file_paths:
        if not os.path.exists(file_path):
            continue
        relative_name = os.path.basename(file_path)
        if copy_file_if_exists(file_path, os.path.join(snapshot_dir, relative_name)):
            copied_files.append(relative_name)

    manifest = {
        "timestamp": timestamp,
        "snapshot_dir": snapshot_dir,
        "files": copied_files,
        "created_at": datetime.now(UTC).isoformat(),
    }
    with open(os.path.join(snapshot_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    with open(CONFIG_SNAPSHOT_POINTER, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    return manifest


def load_latest_config_snapshot() -> dict[str, Any] | None:
    if not os.path.exists(CONFIG_SNAPSHOT_POINTER):
        return None

    try:
        with open(CONFIG_SNAPSHOT_POINTER, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None

    snapshot_dir = data.get("snapshot_dir")
    if not snapshot_dir or not os.path.isdir(snapshot_dir):
        return None

    return data


def restore_config_snapshot(snapshot: dict[str, Any]) -> tuple[bool, str]:
    snapshot_dir = snapshot.get("snapshot_dir")
    if not snapshot_dir or not os.path.isdir(snapshot_dir):
        return False, "Config snapshot is missing or unavailable."

    restored: list[str] = []
    for file_name in snapshot.get("files", []):
        src_path = os.path.join(snapshot_dir, file_name)
        if file_name == "PalWorldSettings.ini":
            dst_path = PALWORLD_SETTINGS_PATH
        elif file_name == "Engine.ini":
            dst_path = ENGINE_SETTINGS_PATH
        else:
            continue

        if copy_file_if_exists(src_path, dst_path):
            restored.append(file_name)

    if not restored:
        return False, "No config files were restored from the snapshot."

    announce_message = "Config revert made, server restarting."
    run_announcement(announce_message)
    restart_ok, restart_res = run_restart(announce_message)

    if restart_ok:
        return True, f"Restored config files: {', '.join(restored)}"

    return False, f"Config restored, but restart failed: {restart_res}"


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


REST_GET_COMMANDS = {"info", "players", "settings", "metrics", "game-data"}
REST_POST_COMMANDS = {"announce", "ban", "kick", "save", "shutdown", "start", "stop", "unban"}
SAFE_STATS_COMMANDS = {"info", "players", "settings", "metrics", "game-data"}


def get_request_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"headers": {"Content-Type": "application/json"}}

    if PALWORLD_API_PASSWORD:
        kwargs["auth"] = (PALWORLD_API_USERNAME or "admin", PALWORLD_API_PASSWORD)
    elif PALWORLD_API_TOKEN:
        token = PALWORLD_API_TOKEN
        if PALWORLD_API_TOKEN_PREFIX:
            token = f"{PALWORLD_API_TOKEN_PREFIX} {PALWORLD_API_TOKEN}".strip()
        kwargs["headers"][PALWORLD_API_TOKEN_HEADER] = token

    return kwargs


def request_json(method: str, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{PALWORLD_API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    request_kwargs = get_request_kwargs()
    response = requests.request(
        method=method,
        url=url,
        json=payload,
        timeout=PALWORLD_API_TIMEOUT,
        **request_kwargs,
    )
    response.raise_for_status()
    if not response.content:
        return {"ok": True, "status": response.status_code}
    try:
        return response.json()
    except ValueError:
        return {"ok": True, "status": response.status_code, "text": response.text}


def fetch_statistics() -> tuple[bool, dict[str, Any]]:
    if PALWORLD_STATS_ENDPOINT:
        try:
            return True, request_json("GET", PALWORLD_STATS_ENDPOINT)
        except requests.RequestException as err:
            return False, {"errors": [f"{PALWORLD_STATS_ENDPOINT} (None): {err}"]}

    if PALWORLD_STATS_COMMAND:
        # Only allow read-only commands during dashboard page load.
        command = PALWORLD_STATS_COMMAND.lower()
        if command in SAFE_STATS_COMMANDS:
            return run_rest_command(command)

    return run_rest_command("info")


def run_rest_command(command: str, payload: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    if command not in REST_GET_COMMANDS and command not in REST_POST_COMMANDS:
        return False, {"errors": [f"Unsupported REST command: {command}"]}

    method = "GET" if command in REST_GET_COMMANDS else "POST"
    try:
        return True, request_json(method, f"/v1/api/{command}", payload)
    except requests.RequestException as err:
        return False, {"errors": [f"/v1/api/{command} ({payload}): {err}"]}

def run_info() -> tuple[bool, dict[str, Any]]:
    return run_rest_command("info")


def run_players() -> tuple[bool, dict[str, Any]]:
    return run_rest_command("players")


def run_settings() -> tuple[bool, dict[str, Any]]:
    return run_rest_command("settings")


def run_metrics() -> tuple[bool, dict[str, Any]]:
    return run_rest_command("metrics")


def run_game_data() -> tuple[bool, dict[str, Any]]:
    return run_rest_command("game-data")


def run_announcement(message: str) -> tuple[bool, dict[str, Any]]:
    return run_rest_command("announce", {"message": message})


def run_kick(player_id: str, reason: str) -> tuple[bool, dict[str, Any]]:
    return run_rest_command("kick", {"userid": player_id, "message": reason or "You are kicked."})


def run_ban(player_id: str, reason: str) -> tuple[bool, dict[str, Any]]:
    return run_rest_command("ban", {"userid": player_id, "message": reason or "You are banned."})


def run_unban(player_id: str) -> tuple[bool, dict[str, Any]]:
    return run_rest_command("unban", {"userid": player_id})


def run_save() -> tuple[bool, dict[str, Any]]:
    return run_rest_command("save")


def run_stop() -> tuple[bool, dict[str, Any]]:
    return run_rest_command("stop")


def run_start() -> tuple[bool, dict[str, Any]]:
    return run_rest_command("start")


def run_shutdown(waittime: int, message: str) -> tuple[bool, dict[str, Any]]:
    return run_rest_command("shutdown", {"waittime": waittime, "message": message})


def run_restart(message: str) -> tuple[bool, dict[str, Any]]:
    # Some server wrappers rewrite config during graceful shutdown. A save+stop
    # sequence often preserves just-written config files better than shutdown.
    strategy = PALWORLD_RESTART_STRATEGY

    if strategy == "shutdown":
        return run_shutdown(1, message)

    save_ok, save_res = run_save()
    stop_ok, stop_res = run_stop()

    if strategy == "save-stop":
        if save_ok and stop_ok:
            return True, {
                "strategy": strategy,
                "save": save_res,
                "stop": stop_res,
            }
        return False, {
            "strategy": strategy,
            "errors": [
                "save failed" if not save_ok else None,
                "stop failed" if not stop_ok else None,
            ],
            "save": save_res,
            "stop": stop_res,
        }

    # Default strategy: try save+stop first, then fall back to shutdown.
    if save_ok and stop_ok:
        return True, {
            "strategy": "save-stop-then-shutdown",
            "path": "save-stop",
            "save": save_res,
            "stop": stop_res,
        }

    shutdown_ok, shutdown_res = run_shutdown(1, message)
    if shutdown_ok:
        return True, {
            "strategy": "save-stop-then-shutdown",
            "path": "shutdown-fallback",
            "save": save_res,
            "stop": stop_res,
            "shutdown": shutdown_res,
        }

    return False, {
        "strategy": "save-stop-then-shutdown",
        "errors": ["save+stop failed", "shutdown fallback failed"],
        "save": save_res,
        "stop": stop_res,
        "shutdown": shutdown_res,
    }


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

    save_ok, save_data = run_save()
    if not save_ok:
        return False, f"Unable to save world before backup: {save_data}", {}

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
    pal_changed = False
    engine_changed = False

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
                pal_changed = True
            continue

        parser = pal_parser if file_name == "PalWorldSettings.ini" else engine_parser
        if not parser.has_section(section_name):
            parser.add_section(section_name)

        current = parser.get(section_name, key, fallback="")
        if current != normalized_value:
            parser.set(section_name, key, normalized_value)
            any_change = True
            if file_name == "PalWorldSettings.ini":
                pal_changed = True
            else:
                engine_changed = True

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
                pal_changed = True
            continue

        parser = pal_parser if file_name == "PalWorldSettings.ini" else engine_parser
        if not parser.has_section(section_name):
            parser.add_section(section_name)

        current = parser.get(section_name, key, fallback="")
        if current != normalized_value:
            parser.set(section_name, key, normalized_value)
            any_change = True
            if file_name == "PalWorldSettings.ini":
                pal_changed = True
            else:
                engine_changed = True

    if not any_change:
        return True, "No configuration changes detected."

    announce_ok, announce_res = run_announcement("Config change made, server restarting.")
    stop_ok, stop_res = run_stop()
    if not stop_ok:
        return False, (
            "Stop failed; config was not changed. "
            f"announce={announce_res} stop={stop_res}"
        )

    snapshot_manifest = snapshot_config_files(
        [
            path
            for path, changed in [
                (PALWORLD_SETTINGS_PATH, pal_changed),
                (ENGINE_SETTINGS_PATH, engine_changed),
            ]
            if changed
        ]
    )

    if option_section_name:
        pal_parser.set(
            option_section_name,
            "OptionSettings",
            serialize_option_settings(option_values),
        )

    save_ini(PALWORLD_SETTINGS_PATH, pal_parser)
    save_ini(ENGINE_SETTINGS_PATH, engine_parser)

    start_ok, start_res = run_start()

    if announce_ok and start_ok:
        return True, (
            "Configuration updated and start initiated after stop. "
            f"Snapshot saved: {snapshot_manifest.get('timestamp')}"
        )

    if announce_ok and not start_ok:
        return True, (
            "Configuration updated after stop. Start API failed; if your server wrapper "
            "auto-starts after stop this is expected. "
            f"start={start_res} Snapshot saved: {snapshot_manifest.get('timestamp')}"
        )

    return (
        False,
        (
            "Configuration updated after stop, but API start/announcement had issues. "
            f"announce={announce_res} start={start_res}"
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
    latest_config_snapshot = load_latest_config_snapshot()

    return render_template(
        "index.html",
        configs=configs,
        stats_ok=stats_ok,
        stats_data=stats_data,
        backups=backups,
        latest_config_snapshot=latest_config_snapshot,
        api_base=PALWORLD_API_BASE_URL,
        config_dir=CONFIG_DIR,
        backup_dir=BACKUP_DIR,
        config_snapshot_dir=CONFIG_SNAPSHOT_DIR,
    )


@app.post("/config/save")
def config_save():
    form_data = {k: v for k, v in request.form.items() if FIELD_SEP in k}
    checkbox_keys = set(request.form.getlist("__bool_fields"))

    ok, message = save_config_from_form(form_data, checkbox_keys)
    flash(message, "ok" if ok else "error")
    return redirect(url_for("index"))


@app.post("/config/revert-latest")
def config_revert_latest():
    snapshot = load_latest_config_snapshot()
    if not snapshot:
        flash("No config snapshot is available to revert.", "error")
        return redirect(url_for("index"))

    ok, message = restore_config_snapshot(snapshot)
    flash(message, "ok" if ok else "error")
    return redirect(url_for("index"))


@app.post("/api/rest/<command>")
def api_rest_command(command: str):
    command = command.lower().strip()

    if command in {"info", "players", "settings", "metrics", "game-data", "save", "stop"}:
        ok, data = run_rest_command(command)
        code = 200 if ok else 502
        return jsonify({"ok": ok, "data": data}), code

    if command == "announce":
        message = request.form.get("message", "").strip()
        if not message:
            return jsonify({"ok": False, "error": "Message is required."}), 400

        ok, data = run_announcement(message)
        code = 200 if ok else 502
        return jsonify({"ok": ok, "data": data}), code

    if command in {"kick", "ban"}:
        player_id = request.form.get("player_id", "").strip()
        if not player_id:
            return jsonify({"ok": False, "error": "Player ID is required."}), 400

        reason = request.form.get("reason", "").strip()
        if command == "kick":
            ok, data = run_kick(player_id, reason)
        else:
            ok, data = run_ban(player_id, reason)

        code = 200 if ok else 502
        return jsonify({"ok": ok, "data": data}), code

    if command == "unban":
        player_id = request.form.get("player_id", "").strip()
        if not player_id:
            return jsonify({"ok": False, "error": "Player ID is required."}), 400

        ok, data = run_unban(player_id)
        code = 200 if ok else 502
        return jsonify({"ok": ok, "data": data}), code

    if command == "shutdown":
        waittime_raw = request.form.get("waittime", "1").strip() or "1"
        try:
            waittime = max(0, int(waittime_raw))
        except ValueError:
            return jsonify({"ok": False, "error": "Wait time must be an integer."}), 400

        message = request.form.get("message", "Server shutting down.").strip()
        ok, data = run_shutdown(waittime, message)
        code = 200 if ok else 502
        return jsonify({"ok": ok, "data": data}), code

    return jsonify({"ok": False, "error": f"Unsupported REST command: {command}"}), 404


@app.get("/api/server/statistics")
def api_statistics():
    ok, data = run_info()
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
    ok, data = run_shutdown(1, message)
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
