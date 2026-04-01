from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from rename_core import (
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_PATH,
    batch_confirm_text,
    build_plan,
    collect_paths,
    execute_plan,
    load_config,
    summary_text,
)


def get_ui():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def request_user_input(config: dict, args: argparse.Namespace) -> str:
    if args.input_text is not None:
        return args.input_text

    if not bool(config.get("ask_for_input", True)):
        return ""

    if args.no_gui:
        raise ValueError("当前配置要求输入名称，请通过 --input 提供文本，或直接双击拖拽使用。")

    from tkinter import simpledialog

    root = get_ui()
    try:
        text = simpledialog.askstring(
            title=str(config.get("prompt_title", DEFAULT_CONFIG["prompt_title"])),
            prompt=str(config.get("prompt_message", DEFAULT_CONFIG["prompt_message"])),
            parent=root,
        )
    finally:
        root.destroy()

    if text is None:
        raise KeyboardInterrupt("用户取消了输入。")
    return text.strip()


def confirm_batch(plans: list, config: dict, args: argparse.Namespace) -> None:
    if len(plans) <= 1:
        return

    message = batch_confirm_text(plans)
    if args.yes:
        return

    if args.no_gui:
        raise ValueError("当前为批量改名预览，请移除 --no-gui，或在明确确认后加 --yes。")

    from tkinter import messagebox

    root = get_ui()
    try:
        approved = messagebox.askokcancel(
            title=str(config.get("confirm_title", DEFAULT_CONFIG["confirm_title"])),
            message=message,
            parent=root,
        )
    finally:
        root.destroy()

    if not approved:
        raise KeyboardInterrupt("用户取消了批量改名。")


def show_message(title: str, message: str, no_gui: bool, error: bool = False) -> None:
    if no_gui:
        output = sys.stderr if error else sys.stdout
        print(message, file=output)
        return

    from tkinter import messagebox

    root = get_ui()
    try:
        if error:
            messagebox.showerror(title, message, parent=root)
        else:
            messagebox.showinfo(title, message, parent=root)
    finally:
        root.destroy()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把文件或文件夹拖到脚本上即可按模板改名。")
    parser.add_argument("paths", nargs="*", help="拖拽进来的文件或文件夹路径")
    parser.add_argument("--input", dest="input_text", help="非交互模式下提供 {input} 的内容")
    parser.add_argument("--no-gui", action="store_true", help="不弹窗，只在命令行输出")
    parser.add_argument("--dry-run", action="store_true", help="仅预览改名结果，不实际执行")
    parser.add_argument("--yes", action="store_true", help="无图形界面下跳过批量确认")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="指定配置文件路径，默认使用脚本同目录下的 rename_config.json",
    )
    return parser.parse_args(argv)


def usage_text(config_path: Path) -> str:
    return (
        "把文件或文件夹直接拖到本脚本，或拖到 drag_to_rename.bat 上即可改名。\n\n"
        f"配置文件: {config_path}\n"
        "控制面板: rename_control.pyw\n"
        "常用占位符: {input} {name} {stem} {ext} {index} {date} {time} {parent}\n"
        "安全机制:\n"
        "1. 文件后缀名始终保持原样，不会被模板或输入改掉\n"
        "2. 一次处理超过 1 个项目时，会先弹出确认框\n"
    )


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    config_path = Path(args.config).resolve()
    config = load_config(config_path)

    if not args.paths:
        show_message(
            str(config.get("info_title", DEFAULT_CONFIG["info_title"])),
            usage_text(config_path),
            no_gui=args.no_gui,
        )
        return 0

    paths = collect_paths(args.paths)
    user_input = request_user_input(config, args)
    plans = build_plan(paths, config, user_input)

    if args.dry_run:
        print(summary_text(plans, []))
        if len(plans) > 1:
            print()
            print(batch_confirm_text(plans))
        return 0

    confirm_batch(plans, config, args)
    completed, skipped = execute_plan(plans)
    show_message(
        str(config.get("success_title", DEFAULT_CONFIG["success_title"])),
        summary_text(completed, skipped),
        no_gui=args.no_gui,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt as exc:
        message = str(exc) or "操作已取消。"
        if "--no-gui" in sys.argv:
            print(message, file=sys.stderr)
        else:
            try:
                show_message("已取消", message, no_gui=False, error=True)
            except Exception:
                print(message, file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        if "--no-gui" in sys.argv:
            print(details, file=sys.stderr)
        else:
            try:
                show_message("发生错误", details, no_gui=False, error=True)
            except Exception:
                print(details, file=sys.stderr)
        raise SystemExit(1)
