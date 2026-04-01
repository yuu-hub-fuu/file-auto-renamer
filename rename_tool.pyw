from __future__ import annotations

import argparse
import os
import sys
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from rename_core import (
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_PATH,
    batch_confirm_text,
    build_plan,
    collect_paths,
    execute_plan,
    load_config,
    save_config,
    summary_text,
)


def create_root() -> tk.Tk:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def get_cli_stream(error: bool = False):
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        return stream

    if os.name == "nt":
        try:
            import ctypes

            attached = ctypes.windll.kernel32.AttachConsole(-1)
            already_attached = ctypes.windll.kernel32.GetLastError() == 5
            if attached or already_attached:
                return open("CONOUT$", "w", encoding="utf-8", buffering=1)
        except Exception:
            pass
    return None


def cli_print(message: str, error: bool = False) -> None:
    stream = get_cli_stream(error=error)
    if stream is None:
        return
    print(message, file=stream)


def show_message(title: str, message: str, no_gui: bool, error: bool = False) -> None:
    if no_gui:
        cli_print(message, error=error)
        return

    root = create_root()
    try:
        if error:
            messagebox.showerror(title, message, parent=root)
        else:
            messagebox.showinfo(title, message, parent=root)
    finally:
        root.destroy()


def request_user_input(config: dict, args: argparse.Namespace) -> str:
    if args.input_text is not None:
        return args.input_text

    if not bool(config.get("ask_for_input", True)):
        return ""

    if args.no_gui:
        raise ValueError("当前配置要求输入名称，请通过 --input 提供文本。")

    root = create_root()
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
    if len(plans) <= 1 or args.yes:
        return

    message = batch_confirm_text(plans)
    if args.no_gui:
        raise ValueError("批量改名需要确认；请移除 --no-gui，或在已确认后加 --yes。")

    root = create_root()
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="双击打开配置，拖拽文件到本程序上即可改名。")
    parser.add_argument("paths", nargs="*", help="拖拽进来的文件或文件夹路径")
    parser.add_argument("--input", dest="input_text", help="非交互模式下提供 {input} 的内容")
    parser.add_argument("--no-gui", action="store_true", help="不弹窗，只在命令行输出")
    parser.add_argument("--dry-run", action="store_true", help="仅预览改名结果，不实际执行")
    parser.add_argument("--yes", action="store_true", help="无图形界面下跳过批量确认")
    parser.add_argument("--open-config", action="store_true", help="强制打开配置面板")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="指定配置文件路径，默认使用程序同目录下的 rename_config.json",
    )
    return parser.parse_args(argv)


class ControlPanel:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config = load_config(self.config_path)

        self.root = tk.Tk()
        self.root.title("改名器控制面板")
        self.root.geometry("840x760")
        self.root.minsize(760, 680)
        self.root.resizable(True, True)

        state = self.infer_ui_state(self.config)

        self.mode_var = tk.StringVar(value=state["mode"])
        self.ask_for_input_var = tk.BooleanVar(value=state["ask_for_input"])
        self.simple_value_var = tk.StringVar(value=state["simple_value"])
        self.single_template_var = tk.StringVar(value=self.config["single_item_template"])
        self.multi_template_var = tk.StringVar(value=self.config["multi_item_template"])
        self.index_start_var = tk.StringVar(value=str(self.config["index_start"]))
        self.index_width_var = tk.StringVar(value=str(self.config["index_width"]))
        self.separator_var = tk.StringVar(value=self.config["conflict_separator"])
        self.prompt_message_var = tk.StringVar(value=self.config["prompt_message"])
        self.mode_hint_var = tk.StringVar()
        self.simple_label_var = tk.StringVar()
        self.preview_single_var = tk.StringVar()
        self.preview_multi_var = tk.StringVar()

        self.build_ui()
        self.bind_updates()
        self.refresh_ui()

    def infer_ui_state(self, config: dict) -> dict:
        ask_for_input = bool(config.get("ask_for_input", True))
        single = str(config.get("single_item_template", "{input}"))
        multi = str(config.get("multi_item_template", "{input}_{index}"))

        if ask_for_input and single == "{input}" and multi == "{input}_{index}":
            return {"mode": "fixed", "ask_for_input": True, "simple_value": ""}
        if not ask_for_input and multi == f"{single}_{{index}}":
            return {"mode": "fixed", "ask_for_input": False, "simple_value": single}

        if ask_for_input and single == "{input}{stem}" and multi == "{input}{stem}_{index}":
            return {"mode": "prefix", "ask_for_input": True, "simple_value": ""}
        if (
            not ask_for_input
            and "{stem}" in single
            and single.endswith("{stem}")
            and multi == f"{single}_{{index}}"
        ):
            return {
                "mode": "prefix",
                "ask_for_input": False,
                "simple_value": single[: -len("{stem}")],
            }

        if ask_for_input and single == "{stem}{input}" and multi == "{stem}{input}_{index}":
            return {"mode": "suffix", "ask_for_input": True, "simple_value": ""}
        if (
            not ask_for_input
            and single.startswith("{stem}")
            and multi == f"{single}_{{index}}"
        ):
            return {
                "mode": "suffix",
                "ask_for_input": False,
                "simple_value": single[len("{stem}") :],
            }

        return {"mode": "custom", "ask_for_input": ask_for_input, "simple_value": ""}

    def build_ui(self) -> None:
        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.main = ttk.Frame(canvas, padding=18)
        canvas_window = canvas.create_window((0, 0), window=self.main, anchor="nw")

        def on_frame_configure(_event) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event) -> None:
            canvas.itemconfigure(canvas_window, width=event.width)

        self.main.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        ttk.Label(
            self.main,
            text="双击程序改规则，拖到程序上就改名。",
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            self.main,
            text="文件后缀会自动保留；一次拖多个项目时会先弹出确认框。",
            foreground="#0b5f2a",
            wraplength=760,
        ).pack(anchor="w", pady=(6, 14))

        mode_box = ttk.LabelFrame(self.main, text="1. 你想怎么改名", padding=14)
        mode_box.pack(fill="x")
        ttk.Radiobutton(
            mode_box,
            text="固定叫这个名字",
            value="fixed",
            variable=self.mode_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            mode_box,
            text="在原名字前面加字",
            value="prefix",
            variable=self.mode_var,
        ).grid(row=0, column=1, sticky="w", padx=(24, 0))
        ttk.Radiobutton(
            mode_box,
            text="在原名字后面加字",
            value="suffix",
            variable=self.mode_var,
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Radiobutton(
            mode_box,
            text="高级自定义",
            value="custom",
            variable=self.mode_var,
        ).grid(row=1, column=1, sticky="w", padx=(24, 0), pady=(8, 0))
        ttk.Label(
            mode_box,
            textvariable=self.mode_hint_var,
            foreground="#555555",
            wraplength=720,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

        basic_box = ttk.LabelFrame(self.main, text="2. 主要设置", padding=14)
        basic_box.pack(fill="x", pady=(14, 0))

        ttk.Checkbutton(
            basic_box,
            text="每次拖拽时先弹窗输入",
            variable=self.ask_for_input_var,
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        self.simple_label = ttk.Label(basic_box, textvariable=self.simple_label_var)
        self.simple_label.grid(row=1, column=0, sticky="w", pady=(12, 4))
        self.simple_entry = ttk.Entry(basic_box, textvariable=self.simple_value_var, width=56)
        self.simple_entry.grid(row=1, column=1, sticky="ew", pady=(12, 4))

        self.prompt_label = ttk.Label(basic_box, text="弹窗里显示的提示语")
        self.prompt_label.grid(row=2, column=0, sticky="w", pady=4)
        self.prompt_entry = ttk.Entry(basic_box, textvariable=self.prompt_message_var, width=56)
        self.prompt_entry.grid(row=2, column=1, sticky="ew", pady=4)

        basic_box.columnconfigure(1, weight=1)

        preview_box = ttk.LabelFrame(self.main, text="3. 效果预览", padding=14)
        preview_box.pack(fill="x", pady=(14, 0))
        ttk.Label(preview_box, text="拖 1 个文件时").grid(row=0, column=0, sticky="w")
        ttk.Label(
            preview_box,
            textvariable=self.preview_single_var,
            foreground="#0b5f2a",
            wraplength=700,
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(preview_box, text="拖多个文件时").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            preview_box,
            textvariable=self.preview_multi_var,
            foreground="#0b5f2a",
            wraplength=700,
        ).grid(row=1, column=1, sticky="w", pady=(8, 0))

        self.custom_box = ttk.LabelFrame(self.main, text="4. 高级设置", padding=14)
        self.custom_box.pack(fill="x", pady=(14, 0))

        ttk.Label(self.custom_box, text="单个项目模板").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.custom_single_entry = ttk.Entry(
            self.custom_box,
            textvariable=self.single_template_var,
            width=56,
        )
        self.custom_single_entry.grid(row=0, column=1, sticky="ew", pady=(0, 4))

        ttk.Label(self.custom_box, text="多个项目模板").grid(row=1, column=0, sticky="w", pady=4)
        self.custom_multi_entry = ttk.Entry(
            self.custom_box,
            textvariable=self.multi_template_var,
            width=56,
        )
        self.custom_multi_entry.grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(self.custom_box, text="起始序号").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(self.custom_box, textvariable=self.index_start_var, width=10).grid(
            row=2, column=1, sticky="w", pady=4
        )

        ttk.Label(self.custom_box, text="序号位数").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(self.custom_box, textvariable=self.index_width_var, width=10).grid(
            row=3, column=1, sticky="w", pady=4
        )

        ttk.Label(self.custom_box, text="重名时中间加什么").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(self.custom_box, textvariable=self.separator_var, width=10).grid(
            row=4, column=1, sticky="w", pady=4
        )

        ttk.Label(
            self.custom_box,
            text=(
                "高级变量：{input} 你输入的文字  {stem} 原文件名  {name} 原完整名  "
                "{index} 序号  {date} 日期  {time} 时间  {parent} 文件夹名"
            ),
            foreground="#555555",
            wraplength=720,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.custom_box.columnconfigure(1, weight=1)

        footer = ttk.Frame(self.main)
        footer.pack(fill="x", pady=(16, 8))
        ttk.Label(
            footer,
            text=f"配置保存位置：{self.config_path}",
            foreground="#666666",
            wraplength=560,
        ).pack(side="left")
        ttk.Button(footer, text="恢复默认", command=self.reset_defaults).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="保存配置", command=self.save).pack(side="right")

    def bind_updates(self) -> None:
        for variable in (
            self.mode_var,
            self.ask_for_input_var,
            self.simple_value_var,
            self.single_template_var,
            self.multi_template_var,
            self.index_start_var,
            self.index_width_var,
            self.prompt_message_var,
        ):
            variable.trace_add("write", self.on_value_changed)

    def on_value_changed(self, *_args) -> None:
        self.refresh_ui()

    def refresh_ui(self) -> None:
        mode = self.mode_var.get()
        ask = self.ask_for_input_var.get()

        mode_hints = {
            "fixed": "适合把文件统一改成固定名字。拖多个文件时会自动补序号。",
            "prefix": "适合保留原文件名，只是在最前面加上统一文字。",
            "suffix": "适合保留原文件名，只是在最后面加上统一文字。",
            "custom": "只有你想写高级规则时才用这一项；平时前面三种就够了。",
        }
        self.mode_hint_var.set(mode_hints.get(mode, ""))

        if mode == "fixed":
            self.simple_label_var.set("固定名字")
        elif mode == "prefix":
            self.simple_label_var.set("前面要加的字")
        elif mode == "suffix":
            self.simple_label_var.set("后面要加的字")
        else:
            self.simple_label_var.set("这项在高级自定义模式下不使用")

        simple_enabled = mode != "custom" and not ask
        prompt_enabled = ask and mode != "custom"
        self.simple_entry.state(["!disabled"] if simple_enabled else ["disabled"])
        self.prompt_entry.state(["!disabled"] if prompt_enabled else ["disabled"])

        if mode == "custom":
            self.custom_box.configure(text="4. 高级设置（当前正在使用）")
            self.custom_single_entry.state(["!disabled"])
            self.custom_multi_entry.state(["!disabled"])
        else:
            self.custom_box.configure(text="4. 高级设置（通常不用改）")
            self.custom_single_entry.state(["disabled"])
            self.custom_multi_entry.state(["disabled"])

        self.update_preview()

    def build_templates(self) -> tuple[str, str]:
        mode = self.mode_var.get()
        ask = self.ask_for_input_var.get()
        value = self.simple_value_var.get().strip()

        if mode == "fixed":
            if ask:
                return "{input}", "{input}_{index}"
            return value or "新名字", f"{value or '新名字'}_{{index}}"

        if mode == "prefix":
            if ask:
                return "{input}{stem}", "{input}{stem}_{index}"
            prefix = value or "已处理_"
            return f"{prefix}{{stem}}", f"{prefix}{{stem}}_{{index}}"

        if mode == "suffix":
            if ask:
                return "{stem}{input}", "{stem}{input}_{index}"
            suffix = value or "_已处理"
            return f"{{stem}}{suffix}", f"{{stem}}{suffix}_{{index}}"

        return self.single_template_var.get().strip(), self.multi_template_var.get().strip()

    def update_preview(self) -> None:
        mode = self.mode_var.get()
        ask = self.ask_for_input_var.get()
        value = self.simple_value_var.get().strip()
        user_value = "[你输入的内容]"
        source_stem = "示例文件"
        source_ext = ".txt"

        if mode == "fixed":
            shown = user_value if ask else (value or "新名字")
            single = f"{shown}{source_ext}"
            multi = f"{shown}_01{source_ext}"
        elif mode == "prefix":
            shown = user_value if ask else (value or "已处理_")
            single = f"{shown}{source_stem}{source_ext}"
            multi = f"{shown}{source_stem}_01{source_ext}"
        elif mode == "suffix":
            shown = user_value if ask else (value or "_已处理")
            single = f"{source_stem}{shown}{source_ext}"
            multi = f"{source_stem}{shown}_01{source_ext}"
        else:
            single_template = self.single_template_var.get().strip() or "(请填写单个项目模板)"
            multi_template = self.multi_template_var.get().strip() or "(请填写多个项目模板)"
            single = f"单个项目会按：{single_template}"
            multi = f"多个项目会按：{multi_template}"

        self.preview_single_var.set(f"示例文件.txt  ->  {single}")
        self.preview_multi_var.set(f"示例文件.txt  ->  {multi}")

    def reset_defaults(self) -> None:
        state = self.infer_ui_state(DEFAULT_CONFIG)
        self.mode_var.set(state["mode"])
        self.ask_for_input_var.set(DEFAULT_CONFIG["ask_for_input"])
        self.simple_value_var.set(state["simple_value"])
        self.single_template_var.set(DEFAULT_CONFIG["single_item_template"])
        self.multi_template_var.set(DEFAULT_CONFIG["multi_item_template"])
        self.index_start_var.set(str(DEFAULT_CONFIG["index_start"]))
        self.index_width_var.set(str(DEFAULT_CONFIG["index_width"]))
        self.separator_var.set(DEFAULT_CONFIG["conflict_separator"])
        self.prompt_message_var.set(DEFAULT_CONFIG["prompt_message"])
        self.refresh_ui()

    def save(self) -> None:
        try:
            index_start = int(self.index_start_var.get().strip())
            index_width = int(self.index_width_var.get().strip())
            if index_width < 1:
                raise ValueError("序号宽度至少为 1。")

            config = load_config(self.config_path)
            single_template, multi_template = self.build_templates()
            config.update(
                {
                    "ask_for_input": self.ask_for_input_var.get(),
                    "single_item_template": single_template or "{input}",
                    "multi_item_template": multi_template or "{input}_{index}",
                    "index_start": index_start,
                    "index_width": index_width,
                    "conflict_separator": self.separator_var.get(),
                    "prompt_message": self.prompt_message_var.get().strip() or "请输入新的名称",
                }
            )
            save_config(self.config_path, config)
        except ValueError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return

        messagebox.showinfo("保存成功", f"配置已保存到:\n{self.config_path}", parent=self.root)

    def run(self) -> None:
        self.root.mainloop()


def run_rename(args: argparse.Namespace, config_path: Path) -> int:
    config = load_config(config_path)
    paths = collect_paths(args.paths)
    user_input = request_user_input(config, args)
    plans = build_plan(paths, config, user_input)

    if args.dry_run:
        cli_print(summary_text(plans, []))
        if len(plans) > 1:
            cli_print("")
            cli_print(batch_confirm_text(plans))
        return 0

    confirm_batch(plans, config, args)
    completed, skipped = execute_plan(plans)
    show_message(
        str(config.get("success_title", DEFAULT_CONFIG["success_title"])),
        summary_text(completed, skipped),
        no_gui=args.no_gui,
    )
    return 0


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    config_path = Path(args.config).resolve()

    if args.open_config or not args.paths:
        ControlPanel(config_path).run()
        return 0

    return run_rename(args, config_path)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt as exc:
        message = str(exc) or "操作已取消。"
        if "--no-gui" in sys.argv:
            cli_print(message, error=True)
        else:
            try:
                show_message("已取消", message, no_gui=False, error=True)
            except Exception:
                cli_print(message, error=True)
        raise SystemExit(1)
    except Exception as exc:
        details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        if "--no-gui" in sys.argv:
            cli_print(details, error=True)
        else:
            try:
                show_message("发生错误", details, no_gui=False, error=True)
            except Exception:
                cli_print(details, error=True)
        raise SystemExit(1)
