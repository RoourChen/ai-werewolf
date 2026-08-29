# Third-Party Notices

本项目（AI狼人杀 / ai-werewolf）是独立实现，**未直接复制**任何第三方源代码。
本项目受 [deepwolf](https://github.com/JuneQQQ/deepwolf) 启发，仅用于理解产品能力
与玩法。

## deepwolf（灵感来源 / inspiration only）

- 项目：https://github.com/JuneQQQ/deepwolf
- 许可证：MIT License — Copyright (c) 2026 the deepwolf contributors
- 用途：仅用于理解狼人杀的产品能力与玩法，未复用其源码、测试、Prompt 或目录结构。

如未来对本项目引入任何源自 deepwolf 的代码片段，该片段仍受其 MIT License 约束，
须保留以下版权声明：

```
MIT License

Copyright (c) 2026 the deepwolf contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 运行时依赖（Runtime dependencies）

本项目通过 pip 声明以下运行时依赖（不打包进仓库）：

- `httpx` — BSD-3-Clause
- `rich` — MIT License

可选依赖（`server` extra）：`fastapi`、`uvicorn`，各自遵循其上游许可证。
