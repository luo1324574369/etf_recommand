import subprocess
import sys
import threading
from flask import Blueprint, request, jsonify, current_app

bp = Blueprint("cmd", __name__)

# 预定义的命令列表
COMMANDS = {
    "update_data": {
        "label": "更新行情数据",
        "description": "从新浪财经拉取最新ETF价格数据",
        "command": [sys.executable, "scripts/update_data.py"],
        "success_hint": "数据更新成功，请刷新页面查看最新信号",
    },
    "run_strategy": {
        "label": "运行策略",
        "description": "执行动量轮动策略，生成最新选股信号",
        "command": [sys.executable, "scripts/run_strategy.py"],
        "success_hint": "策略运行成功，信号已保存",
    },
    "update_data_full": {
        "label": "全量更新数据",
        "description": "从2018年开始重新拉取所有历史数据（耗时较长）",
        "command": [sys.executable, "scripts/update_data.py", "--full"],
        "success_hint": "全量更新完成",
    },
    "gen_doc": {
        "label": "生成策略说明",
        "description": "根据当前配置重新生成大白话策略说明文档",
        "command": [sys.executable, "scripts/generate_strategy_doc.py"],
        "success_hint": "文档已更新到 docs/strategy_doc.md",
    },
}


@bp.route("/api/commands")
def list_commands():
    """返回可用命令列表"""
    return jsonify(COMMANDS)


@bp.route("/api/run", methods=["POST"])
def run_command():
    """执行指定命令"""
    data = request.get_json()
    cmd_key = data.get("command")

    if cmd_key not in COMMANDS:
        return jsonify({"success": False, "error": f"未知命令: {cmd_key}"}), 400

    cmd_info = COMMANDS[cmd_key]
    cmd = cmd_info["command"]

    # 获取项目根目录
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _run():
        try:
            result = subprocess.run(
                cmd,
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": "命令执行超时（超过120秒）"}
        except Exception as e:
            return {"returncode": -2, "stdout": "", "stderr": str(e)}

    result = _run()

    if result["returncode"] == 0:
        return jsonify({
            "success": True,
            "message": cmd_info["success_hint"],
            "output": result["stdout"],
        })
    else:
        return jsonify({
            "success": False,
            "error": result["stderr"] or result["stdout"],
            "output": result["stdout"],
        })


@bp.route("/api/run_async", methods=["POST"])
def run_command_async():
    """异步执行命令（不等待结果）"""
    data = request.get_json()
    cmd_key = data.get("command")

    if cmd_key not in COMMANDS:
        return jsonify({"success": False, "error": f"未知命令: {cmd_key}"}), 400

    cmd_info = COMMANDS[cmd_key]
    cmd = cmd_info["command"]

    import os
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _run():
        try:
            result = subprocess.run(
                cmd,
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout[-2000:],
                "stderr": result.stderr[-1000:],
            }
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": "命令执行超时"}
        except Exception as e:
            return {"returncode": -2, "stdout": "", "stderr": str(e)}

    threading.Thread(target=_run, daemon=True).start()

    return jsonify({
        "success": True,
        "message": f"'{cmd_info['label']}' 已启动，请在终端查看输出",
    })
