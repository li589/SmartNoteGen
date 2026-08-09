# SoundFont 说明

本项目渲染 MIDI→WAV 需要 GM 兼容 SoundFont（.sf2）。推荐二选一：

| SoundFont | 体积 | 说明 |
|---|---|---|
| GeneralUser GS v1.471 | ~30MB | 通用 GM 音色库，质感均衡，默认推荐 |
| FluidR3 (GM) | ~140MB | 更饱满的钢琴/弦乐音色 |

## 下载与放置

1. 下载 .sf2 文件（如 GeneralUser GS v1.471）；
2. 放入本目录 `assets/soundfonts/`；
3. 在配置 `[paths] soundfont` 中指定实际文件名：

```toml
[paths]
soundfont = "assets/soundfonts/GeneralUser_GS_v1.471.sf2"
```

> 出于体积与版权考虑，.sf2 二进制不入库。未放置时 `render` / `pipeline` 会以退出码 2 提示。
