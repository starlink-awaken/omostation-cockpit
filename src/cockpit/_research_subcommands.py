"""Register the research subcommand tree."""

from __future__ import annotations

import argparse


def register_research_subcommands(
    sub: argparse._SubParsersAction,
    workspace_parser: type[argparse.ArgumentParser],
) -> None:
    """Register research and its nested subcommands."""
    # ── research ──────────────────────────────────────────────
    # 子命令化: 将 20+ 布尔 flag 拆为独立子命令, 提升可发现性与帮助质量
    r = sub.add_parser(
        "research",
        help="深度研究 — 创建/查询/管理研究对象",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "子命令:\n"
            "  (默认)           创建新研究 (直接传 topic)\n"
            "  list            查看研究历史\n"
            "  open            打开研究全文\n"
            "  publish         发布研究为正式 Markdown 报告\n"
            "  dossier         查看研究的关系与产物视图\n"
            "  timeline        查看研究的演化时间线\n"
            "  tag             为研究添加/覆盖标签\n"
            "  rename          重命名研究标题\n"
            "  archive         归档研究记录\n"
            "  unarchive       恢复已归档研究记录\n"
            "  export          导出研究 (markdown/text/json)\n"
            "  ask             对指定研究发起追问\n"
            "  search          全文搜索\n"
            "  compare         对比多个研究结果\n"
            "  merge           合并多个研究结果为新研究\n"
            "  digest          提炼多个研究结果\n"
            "  audit           扫描可疑研究记录\n"
            "  quarantine      隔离可疑研究记录\n"
            "  restore         恢复已隔离研究记录\n"
            "  heatmap         显示研究活跃度热力图\n"
            "  follow-up       查看追问工作台\n"
            "  health          查看研究健康报告\n"
            "  batch           批量研究模式\n"
            "  backup          全量备份研究数据\n"
            "  backup-restore  从备份恢复研究数据\n"
            "示例:\n"
            '  cockpit research "attention mechanism"\n'
            "  cockpit research list --limit 20\n"
            "  cockpit research open 5\n"
            "  cockpit research publish 5 --style report"
        ),
    )
    r_sub = r.add_subparsers(dest="research_command", parser_class=workspace_parser)

    # create: 默认模式 (无子命令时通过 dispatch_research 回退)
    r_create = r_sub.add_parser("create", help="创建新研究")
    r_create.add_argument("topic", nargs="*", help="研究主题")
    r_create.add_argument("--agent", type=str, metavar="NAME", help="标记处理 Agent (如 minerva, sophia)")
    r_create.add_argument("--stream", action="store_true", help="流式输出 (ollama 逐 token 打印)")

    # list
    r_list = r_sub.add_parser("list", help="查看研究历史")
    r_list.add_argument("--limit", type=int, default=10, help="显示条数 (默认 10)")
    r_list.add_argument("--status", choices=["active", "archived", "all"], default="all", help="筛选状态")
    r_list.add_argument("--json", action="store_true", help="JSON 格式输出")

    # open
    r_open = r_sub.add_parser("open", help="打开研究全文")
    r_open.add_argument("id", type=int, metavar="ID", help="研究 ID")
    r_open.add_argument("--json", action="store_true", help="JSON 格式输出")

    # publish
    r_publish = r_sub.add_parser("publish", help="发布研究为正式 Markdown 报告")
    r_publish.add_argument("id", type=int, metavar="ID", help="研究 ID")
    r_publish.add_argument("--style", choices=["brief", "report", "memo"], default="report", help="输出风格")

    # dossier / timeline
    r_sub.add_parser("dossier", help="查看研究的关系与产物视图").add_argument("id", type=int, metavar="ID")
    r_sub.add_parser("timeline", help="查看研究的演化时间线").add_argument("id", type=int, metavar="ID")

    # tag / rename
    r_tag = r_sub.add_parser("tag", help="为研究添加/覆盖标签")
    r_tag.add_argument("id", type=int, metavar="ID", help="研究 ID")
    r_tag.add_argument("--labels", nargs="+", required=True, help="标签列表")
    r_rename = r_sub.add_parser("rename", help="重命名研究标题")
    r_rename.add_argument("id", type=int, metavar="ID", help="研究 ID")
    r_rename.add_argument("--new-title", nargs="+", required=True, help="新标题")

    # archive / unarchive
    r_archive = r_sub.add_parser("archive", help="归档研究记录")
    r_archive.add_argument("ids", type=int, nargs="*", metavar="ID", help="研究 ID (省略时需 --all-active)")
    r_archive.add_argument("--all-active", action="store_true", help="归档全部活跃研究")
    r_unarchive = r_sub.add_parser("unarchive", help="恢复已归档研究记录")
    r_unarchive.add_argument("ids", type=int, nargs="*", metavar="ID", help="研究 ID")
    r_unarchive.add_argument("--all-active", action="store_true", help="恢复全部活跃研究")

    # export / ask
    r_export = r_sub.add_parser("export", help="导出研究 (markdown/text/json)")
    r_export.add_argument("id", type=int, metavar="ID", help="研究 ID")
    r_export.add_argument("--format", choices=["markdown", "text", "json"], default="markdown", help="导出格式")
    r_ask = r_sub.add_parser("ask", help="对指定研究发起追问")
    r_ask.add_argument("id", type=int, metavar="ID", help="研究 ID")

    # search / compare / merge / digest
    r_sub.add_parser("search", help="全文搜索").add_argument("keyword", type=str, metavar="KEYWORD")
    r_compare = r_sub.add_parser("compare", help="对比多个研究结果")
    r_compare.add_argument("ids", type=int, nargs="+", metavar="ID", help="研究 ID 列表")
    r_merge = r_sub.add_parser("merge", help="合并多个研究结果为新研究")
    r_merge.add_argument("ids", type=int, nargs="+", metavar="ID", help="研究 ID 列表")
    r_digest = r_sub.add_parser("digest", help="提炼多个研究结果")
    r_digest.add_argument("ids", type=int, nargs="+", metavar="ID", help="研究 ID 列表")

    # audit / quarantine / restore
    r_sub.add_parser("audit", help="扫描可疑研究记录")
    r_quarantine = r_sub.add_parser("quarantine", help="隔离可疑研究记录")
    r_quarantine.add_argument("ids", type=int, nargs="+", metavar="ID", help="研究 ID 列表")
    r_restore = r_sub.add_parser("restore", help="恢复已隔离研究记录")
    r_restore.add_argument("ids", type=int, nargs="+", metavar="ID", help="研究 ID 列表")

    # heatmap / follow-up / health
    r_sub.add_parser("heatmap", help="显示研究活跃度热力图")
    r_sub.add_parser("follow-up", help="查看追问工作台（待追问/已回答统计）")
    r_sub.add_parser("health", help="查看研究健康报告（衰减状态/保鲜建议）")

    # batch
    r_batch = r_sub.add_parser("batch", help="批量研究模式: 逐个处理多个 topic，汇总结果")
    r_batch.add_argument("topics", nargs="*", help="多个研究主题")
    r_batch.add_argument("--agent", type=str, metavar="NAME", help="标记处理 Agent")

    # backup / backup-restore
    r_backup = r_sub.add_parser("backup", help="全量备份研究数据到 JSON 文件")
    r_backup.add_argument("--output", "-o", nargs="?", const="", metavar="OUTPUT", help="输出路径")
    r_bkrestore = r_sub.add_parser("backup-restore", help="从备份 JSON 文件恢复研究数据")
    r_bkrestore.add_argument("path", type=str, metavar="PATH", help="备份文件路径")
