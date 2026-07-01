import os
import sys
import subprocess

from .render import bold, green, red, yellow, gray, blue

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MENU = [
    ("运行策略", "执行动量轮动选股，生成最新信号",
     [sys.executable, "scripts/run_strategy.py"]),
    ("更新行情数据", "从akshare拉取最新ETF价格数据",
     [sys.executable, "scripts/update_data.py"]),
    ("全量更新数据", "从2018年开始重拉所有历史数据（较慢）",
     [sys.executable, "scripts/update_data.py", "--full"]),
    ("生成策略说明", "根据当前配置重新生成大白话文档",
     [sys.executable, "scripts/generate_strategy_doc.py"]),
    ("查看持仓", "显示当前账户持仓和交易记录",
     [sys.executable, "scripts/show_portfolio.py"]),
    ("录入交易", "买入/卖出操作",
     [sys.executable, "scripts/add_trade.py"]),
    ("初始化账户", "新建或重置模拟账户",
     [sys.executable, "scripts/init_account.py"]),
]


def print_header():
    print()
    print(bold(green("╔══════════════════════════════════════════════╗")))
    print(bold(green("║           ETF Quant 终端模式 v1.0            ║")))
    print(bold(green("╚══════════════════════════════════════════════╝")))
    print()


def print_menu():
    print(bold("  请选择操作："))
    print()
    for i, (name, desc, _) in enumerate(MENU, 1):
        print(f"  {yellow(f'[{i}]')} {bold(name)}")
        print(f"      {gray(desc)}")
    print()
    print(f"  {yellow('[q]')} {bold('退出')}")
    print()


def run_command(cmd_list):
    print()
    print(blue("─── 执行中 ───"))
    print()

    result = subprocess.run(
        cmd_list,
        cwd=_PROJECT_ROOT,
    )

    print()
    if result.returncode == 0:
        print(green("✓ 执行完成"))
    else:
        print(red(f"✗ 执行失败（退出码 {result.returncode}）"))
    print()


def main():
    print_header()

    while True:
        print_menu()
        try:
            choice = input(f"{bold(green('ETF@Quant'))}:~$ ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print(gray("再见！"))
            break

        if not choice:
            continue

        if choice.lower() in ("q", "quit", "exit"):
            print(gray("再见！"))
            break

        if not choice.isdigit():
            print(red(f"  ✗ 无效选项: {choice}，请输入 1-{len(MENU)} 或 q"))
            continue

        idx = int(choice)
        if idx < 1 or idx > len(MENU):
            print(red(f"  ✗ 无效选项: {choice}，请输入 1-{len(MENU)} 或 q"))
            continue

        name, desc, cmd = MENU[idx - 1]
        print()
        print(f"即将执行：{bold(name)} - {desc}")
        run_command(cmd)

        input("按 Enter 返回菜单...")


if __name__ == "__main__":
    main()
