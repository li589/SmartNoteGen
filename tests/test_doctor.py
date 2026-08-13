"""环境诊断测试（P3-E3）。"""

from __future__ import annotations


from smartnotegen.cli import _doctor_item


def test_doctor_item_format(capsys):
    """_doctor_item 输出格式正确。"""
    _doctor_item("Python", "✅ 3.12.0")
    captured = capsys.readouterr()
    assert "Python" in captured.out
    assert "✅ 3.12.0" in captured.out


def test_doctor_item_alignment(capsys):
    """不同长度的名称对齐（宽度差异不超过 2）。"""
    _doctor_item("Python", "✅ OK")
    _doctor_item("fluidsynth", "✅ OK")
    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")
    assert len(lines) == 2
    col1 = lines[0].index("✅")
    col2 = lines[1].index("✅")
    # 中文字符占 2 宽度，允许 2 字符偏差
    assert abs(col1 - col2) <= 2, f"状态图标列偏移过大: {col1} vs {col2}"


def test_doctor_via_typer():
    """doctor 子命令可通过 CLI 调用（不崩溃）。"""
    from typer.testing import CliRunner
    from smartnotegen.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code in (0, 1, 2)
    assert "SmartNoteGen 环境诊断" in result.output
    assert "Python" in result.output