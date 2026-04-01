from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return SCRIPT_DIR


def get_config_path() -> Path:
    if getattr(sys, "frozen", False):
        appdata = Path.home() / "AppData" / "Roaming" / "AutoRenamer"
        return appdata / "rename_config.json"
    return SCRIPT_DIR / "rename_config.json"


DEFAULT_CONFIG_PATH = get_config_path()
INVALID_CHARS = '<>:"/\\|?*'
RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}
DEFAULT_CONFIG = {
    "ask_for_input": True,
    "single_item_template": "{input}",
    "multi_item_template": "{input}_{index}",
    "conflict_strategy": "auto_increment",
    "index_start": 1,
    "index_width": 2,
    "date_format": "%Y%m%d",
    "time_format": "%H%M%S",
    "conflict_separator": "_",
    "prompt_title": "拖拽改名器",
    "prompt_message": "请输入新的名称",
    "success_title": "改名完成",
    "info_title": "拖拽改名器",
    "confirm_title": "批量确认",
}


@dataclass
class RenamePlan:
    source: Path
    target: Path
    template: str
    temp_path: Path | None = None


class FormatDict(dict):
    def __missing__(self, key: str) -> str:
        raise KeyError(key)


def normalize_config(config: dict | None = None) -> dict:
    normalized = DEFAULT_CONFIG.copy()
    if isinstance(config, dict):
        normalized.update(config)

    normalized["ask_for_input"] = bool(normalized.get("ask_for_input", True))
    normalized["single_item_template"] = str(normalized.get("single_item_template", "{input}"))
    normalized["multi_item_template"] = str(
        normalized.get("multi_item_template", "{input}_{index}")
    )
    normalized["conflict_strategy"] = str(
        normalized.get("conflict_strategy", "auto_increment")
    ).lower()
    normalized["index_start"] = int(normalized.get("index_start", 1))
    normalized["index_width"] = max(1, int(normalized.get("index_width", 2)))
    normalized["date_format"] = str(normalized.get("date_format", "%Y%m%d"))
    normalized["time_format"] = str(normalized.get("time_format", "%H%M%S"))
    normalized["conflict_separator"] = str(normalized.get("conflict_separator", "_"))
    normalized["prompt_title"] = str(normalized.get("prompt_title", "拖拽改名器"))
    normalized["prompt_message"] = str(normalized.get("prompt_message", "请输入新的名称"))
    normalized["success_title"] = str(normalized.get("success_title", "改名完成"))
    normalized["info_title"] = str(normalized.get("info_title", "拖拽改名器"))
    normalized["confirm_title"] = str(normalized.get("confirm_title", "批量确认"))
    return normalized


def ensure_default_config(config_path: Path) -> None:
    if config_path.exists():
        return
    save_config(config_path, DEFAULT_CONFIG)


def load_config(config_path: Path) -> dict:
    ensure_default_config(config_path)
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件 JSON 有错误: {config_path}\n{exc}") from exc

    if not isinstance(loaded, dict):
        raise ValueError("配置文件必须是 JSON 对象。")
    return normalize_config(loaded)


def save_config(config_path: Path, config: dict) -> None:
    normalized = normalize_config(config)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def split_name_and_suffix(path: Path) -> tuple[str, str]:
    if path.is_file():
        suffix = "".join(path.suffixes)
        stem = path.name[: -len(suffix)] if suffix else path.name
        return stem, suffix
    return path.name, ""


def split_candidate_name(name: str, is_file: bool) -> tuple[str, str]:
    if not is_file:
        return name, ""
    suffixes = Path(name).suffixes
    suffix = "".join(suffixes)
    stem = name[: -len(suffix)] if suffix else name
    return stem, suffix


def sanitize_name(name: str) -> str:
    name = name.strip()
    translate_table = str.maketrans({char: "_" for char in INVALID_CHARS})
    cleaned = name.translate(translate_table).rstrip(" .")
    if not cleaned:
        cleaned = "unnamed"

    stem = cleaned.split(".")[0].upper()
    if stem in RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def sanitize_file_stem(name: str) -> str:
    # 文件扩展名由原文件决定，这里把输入里的点替换掉，避免伪造新后缀。
    cleaned = sanitize_name(name).replace(".", "_").rstrip(" _")
    if not cleaned:
        cleaned = "unnamed"
    return cleaned


def render_target_name(
    path: Path,
    template: str,
    user_input: str,
    config: dict,
    index_value: int,
) -> str:
    stem, full_suffix = split_name_and_suffix(path)
    now = datetime.now()
    values = FormatDict(
        input=user_input,
        name=path.name,
        stem=stem,
        ext=full_suffix.lstrip("."),
        date=now.strftime(config["date_format"]),
        time=now.strftime(config["time_format"]),
        index=str(index_value).zfill(int(config["index_width"])),
        parent=path.parent.name,
    )

    try:
        rendered = template.format_map(values)
    except KeyError as exc:
        raise ValueError(f"模板里有未知占位符: {exc.args[0]}") from exc

    if path.is_file():
        return f"{sanitize_file_stem(rendered)}{full_suffix}"
    return sanitize_name(rendered)


def ensure_unique_target(
    source: Path,
    desired_name: str,
    config: dict,
    existing_names: set[str],
    planned_names: set[str],
) -> Path:
    if desired_name not in existing_names and desired_name not in planned_names:
        planned_names.add(desired_name)
        return source.with_name(desired_name)

    strategy = str(config.get("conflict_strategy", "auto_increment")).lower()
    if strategy == "error":
        raise FileExistsError(f"目标名称已存在: {desired_name}")

    if strategy != "auto_increment":
        raise ValueError(f"不支持的 conflict_strategy: {strategy}")

    separator = str(config.get("conflict_separator", "_"))
    base, suffix = split_candidate_name(desired_name, source.is_file())
    counter = 2
    while True:
        candidate = f"{base}{separator}{counter:02d}{suffix}"
        if candidate not in existing_names and candidate not in planned_names:
            planned_names.add(candidate)
            return source.with_name(candidate)
        counter += 1


def collect_paths(raw_paths: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_paths:
        path = Path(raw).resolve()
        if not path.exists():
            raise FileNotFoundError(f"找不到目标: {raw}")
        if path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def ensure_no_nested_paths(paths: list[Path]) -> None:
    for index, path in enumerate(paths):
        for other in paths[index + 1 :]:
            if path in other.parents or other in path.parents:
                raise ValueError(
                    "不支持同时拖入父目录和它内部的子项目，请分开操作。\n"
                    f"冲突项: {path} <-> {other}"
                )


def build_plan(paths: list[Path], config: dict, user_input: str) -> list[RenamePlan]:
    ensure_no_nested_paths(paths)
    total = len(paths)
    plans: list[RenamePlan] = []

    group_current_names: dict[Path, set[str]] = {}
    for path in paths:
        group_current_names.setdefault(path.parent, set()).add(path.name)

    group_existing_names: dict[Path, set[str]] = {}
    for parent, own_names in group_current_names.items():
        existing = {item.name for item in parent.iterdir()}
        group_existing_names[parent] = existing - own_names

    group_planned_names: dict[Path, set[str]] = {parent: set() for parent in group_current_names}

    for offset, path in enumerate(paths):
        template_key = "single_item_template" if total == 1 else "multi_item_template"
        template = str(config.get(template_key, DEFAULT_CONFIG[template_key]))
        index_value = int(config["index_start"]) + offset
        desired_name = render_target_name(path, template, user_input, config, index_value)
        target = ensure_unique_target(
            source=path,
            desired_name=desired_name,
            config=config,
            existing_names=group_existing_names[path.parent],
            planned_names=group_planned_names[path.parent],
        )
        plans.append(RenamePlan(source=path, target=target, template=template))

    return plans


def build_temp_path(source: Path) -> Path:
    while True:
        temp_name = f".__rename_tmp__{uuid.uuid4().hex}__{source.name}"
        temp_path = source.with_name(temp_name)
        if not temp_path.exists():
            return temp_path


def execute_plan(plans: list[RenamePlan]) -> tuple[list[RenamePlan], list[str]]:
    completed: list[RenamePlan] = []
    skipped: list[str] = []
    temp_renamed: list[RenamePlan] = []

    for plan in plans:
        if plan.source == plan.target:
            skipped.append(f"{plan.source.name} -> {plan.target.name} (名称未变化)")
            completed.append(plan)
            continue

        temp_path = build_temp_path(plan.source)
        plan.source.rename(temp_path)
        plan.temp_path = temp_path
        temp_renamed.append(plan)

    try:
        for plan in temp_renamed:
            assert plan.temp_path is not None
            plan.temp_path.rename(plan.target)
            completed.append(plan)
    except Exception:
        for plan in temp_renamed:
            try:
                if plan.temp_path and plan.temp_path.exists():
                    plan.temp_path.rename(plan.source)
            except OSError:
                pass
        raise

    return completed, skipped


def summary_text(plans: list[RenamePlan], skipped: list[str]) -> str:
    renamed_lines = []
    for plan in plans:
        if plan.source != plan.target:
            renamed_lines.append(f"{plan.source.name} -> {plan.target.name}")

    parts = [f"处理项目: {len(plans)}"]
    if renamed_lines:
        parts.append("已改名:")
        parts.extend(renamed_lines)
    if skipped:
        parts.append("跳过:")
        parts.extend(skipped)
    if not renamed_lines and not skipped:
        parts.append("没有需要改名的项目。")
    return "\n".join(parts)


def batch_confirm_text(plans: list[RenamePlan], preview_limit: int = 12) -> str:
    changed = [plan for plan in plans if plan.source != plan.target]
    header = [f"本次将处理 {len(plans)} 个项目。", "", "请确认以下改名预览:"]
    preview = [f"{plan.source.name} -> {plan.target.name}" for plan in changed[:preview_limit]]
    if len(changed) > preview_limit:
        preview.append(f"... 还有 {len(changed) - preview_limit} 个项目未展开")
    if not changed:
        preview.append("所有项目名称都没有变化。")
    return "\n".join(header + preview)
