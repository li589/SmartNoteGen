# 插件 / 扩展架构（R12）

第三方包可通过 **`importlib.metadata` entry points** 注册扩展，**无需改动核心代码**。
核心侧统一由 `sunoauxtool/plugins.py::discover()` 合并「内置 hardcode」与「entry point 插件」。

## 扩展点一览

| point（短名） | 完整 group | 注册内容 | 是否实例化 |
|---|---|---|---|
| `ai_backends` | `sunoauxtool.ai_backends` | `AIGenerator` 子类 | 否（保留类） |
| `render_engines` | `sunoauxtool.render_engines` | `Renderer` 子类 | 否（保留类） |
| `download_sources` | `sunoauxtool.download_sources` | `SourceAdapter` **子类** | 是（核心实例化） |
| `transcribe_backends` | `sunoauxtool.transcribe_backends` | 提供 `transcribe(src, out=None) -> str` 的类 | 否（CLI 实例化） |
| `video_visuals` | `sunoauxtool.video_visuals` | `Visualizer` 子类 | 否（工厂按 config 实例化） |

> `instantiate=False` 的点保留**类本身**，因为构造需要当次 `config` / `**extra`
> （如 score 视觉层的 `score / beat_times / bpm / notation`）。

## 注册方式

在插件包的 `pyproject.toml` 声明：

```toml
[project]
name = "my-sunoaux-plugin"
version = "0.1.0"

[project.entry-points."sunoauxtool.transcribe_backends"]
my-backend = "my_pkg.backends:MyBackend"

[project.entry-points."sunoauxtool.download_sources"]
my-source = "my_pkg.sources:MySource"
```

安装即生效（`pip install -e .`），卸载即消失。完整可运行示例见
**`examples/plugin_demo/`**（注册了 `demo` 转谱后端与 `demo-source` 下载源）。

## 不变约束

1. **builtins 仍硬编码**：entry points 只追加；同名时插件覆盖内置。
2. **坏插件不拖垮 CLI**：单个 entry point 的导入 / 实例化异常只
   `warnings.warn` 并跳过，内置能力照常可用（见 `tests/test_plugins.py`）。
3. **类型不符即跳过**：传了 `base` 的点会校验实例 / 子类，不符同样 warn 跳过。
4. 核心层不反向依赖 CLI 层；AI 后端保持延迟导入（P0 路径零 torch）。

## 接入新扩展点

1. 在核心侧写一个 `discover_<point>()`，内部
   `discover("<point>", builtins, base=..., instantiate=...)`；
2. 把原手写 dict / if-elif 派发改用它（参考 `download/sources/base.py`、
   `video/visuals/__init__.py`、`cli.py` 的 `transcribe --backend`）；
3. 补一条「插件不崩」冒烟测试。

## 排错

- 插件没被发现：确认包已安装且 group 名拼写为 `sunoauxtool.<point>`；
  用 `python -c "from importlib.metadata import entry_points; print(entry_points(group='sunoauxtool.transcribe_backends'))"` 核对。
- 插件被跳过：运行时会打印 `UserWarning`（加载失败 / 类型不符），按提示修。
