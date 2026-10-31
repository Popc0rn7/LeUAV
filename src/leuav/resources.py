"""Resolve external resources without copying or moving them."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import yaml


class ResourceError(ValueError):
    pass


def read_resources(config: Path) -> dict[str, dict]:
    if not config.exists():
        return {}
    try:
        document = yaml.safe_load(config.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ResourceError(f"无法读取 {config}: {exc}") from exc
    if document is None:
        return {}
    if not isinstance(document, dict) or set(document) - {"resources"}:
        raise ResourceError(f"{config}: 顶层只支持 resources 映射")
    entries = document.get("resources", {})
    if not isinstance(entries, dict):
        raise ResourceError(f"{config}: resources 必须是映射")
    result = {}
    for name, entry in entries.items():
        if not isinstance(name, str) or not name or not isinstance(entry, dict):
            raise ResourceError(f"{config}: 资源名称必须是非空字符串，配置必须是映射")
        if set(entry) - {"path"} or not isinstance(entry.get("path"), str) or not entry["path"].strip():
            raise ResourceError(f"{config}: {name} 必须包含非空 path，且只支持 path 字段")
        path = Path(entry["path"]).expanduser()
        if not path.is_absolute():
            path = config.parent / path
        result[name] = {"path": path.resolve(), "source": config}
    return result


def load_resources(workspace: Path, user_config: Path | None = None) -> dict[str, dict]:
    if user_config is None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        user_config = config_home / "leuav" / "resources.yaml"
    resources = read_resources(user_config.expanduser().absolute())
    resources.update(read_resources(workspace.expanduser().absolute() / "resources.local.yaml"))
    return resources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="定位和检查仓库外资源；不会搬移或修改资源")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="工作区目录，默认当前目录")
    parser.add_argument("--user-config", type=Path, help="显式指定用户配置文件")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="列出路径、存在状态和配置来源")
    resolve = sub.add_parser("resolve", help="输出一个已存在资源的绝对路径")
    resolve.add_argument("name")
    check = sub.add_parser("check", help="检查指定资源；省略名称时检查所有已配置资源")
    check.add_argument("names", nargs="*")
    args = parser.parse_args(argv)
    try:
        if args.user_config is not None and not args.user_config.expanduser().is_file():
            raise ResourceError(f"指定的用户配置文件不存在: {args.user_config}")
        resources = load_resources(args.workspace, args.user_config)
        if args.command == "list":
            for name, entry in sorted(resources.items()):
                state = "存在" if entry["path"].exists() else "缺失"
                print(f"{name}\t{state}\t{entry['path']}\t{entry['source']}")
            if not resources:
                print("尚未配置资源；请配置 ~/.config/leuav/resources.yaml 或工作区 resources.local.yaml")
            return 0
        names = [args.name] if args.command == "resolve" else (args.names or sorted(resources))
        if not names:
            raise ResourceError("没有可检查的资源；请先配置 resources.yaml 或 resources.local.yaml")
        failed = False
        for name in names:
            entry = resources.get(name)
            if entry is None:
                print(f"{name}: 未配置，请在用户配置或工作区 resources.local.yaml 中添加 resources.{name}.path", file=sys.stderr)
                failed = True
            elif not entry["path"].exists():
                print(f"{name}: 路径不存在: {entry['path']}（配置来源 {entry['source']}）", file=sys.stderr)
                failed = True
            else:
                print(entry["path"] if args.command == "resolve" else f"{name}: 可用 {entry['path']}")
        return 1 if failed else 0
    except (ResourceError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
