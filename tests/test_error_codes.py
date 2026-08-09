"""P2-3 错误码单测：errors 子命令 + 新增异常类（7/8/9）。"""

from __future__ import annotations

from typer.testing import CliRunner

from smartnotegen.cli import app
from smartnotegen.exceptions import (
    BatchFailedError,
    BatchPartialError,
    ERROR_CODES,
    ModuleError,
)

runner = CliRunner()


def test_errors_command_lists_codes(tmp_project):
    """smartnotegen errors 列出全部错误码 0-9。"""
    result = runner.invoke(app, ["errors"])
    assert result.exit_code == 0, result.output
    for code, name, _desc in ERROR_CODES:
        assert str(code) in result.output
    assert "渲染环境不完整" in result.output
    assert "批量部分失败" in result.output
    assert "批量全部失败" in result.output


def test_module_error_code_7():
    err = ModuleError("环境不完整", code=7)
    assert err.code == 7


def test_batch_partial_error_code_8():
    err = BatchPartialError("部分失败", code=8)
    assert err.code == 8


def test_batch_failed_error_code_9():
    err = BatchFailedError("全部失败", code=9)
    assert err.code == 9


def test_error_codes_table_complete():
    """错误码表含 0-9 连续定义。"""
    codes = [c for c, _n, _d in ERROR_CODES]
    assert codes == list(range(10))
