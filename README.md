# whisper-subtitle

简体中文 | [English](README.en.md)

一个每次处理单个音视频文件的命令行字幕工具。使用 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 听写中文、日语、英语和韩语，通过翻译 API 或本地 Sakura 生成简体中文字幕，支持 LRC 和 SRT。

- 日语、英语、韩语默认通过 API 翻译；中文直接在本地转换为简体。
- 默认生成 LRC，保存到原音视频所在目录。
- 支持人声分离、人声导出、术语字典、质量报告和任务续跑。
- 提供高精度与普通两种听写预设；日语高精度模式支持分句和可疑片段复核。

## 快速开始

建议使用 Python 3.10–3.12。以下命令在 Windows PowerShell 中运行。

### 1. 安装

进入项目目录后执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
.\.venv\Scripts\Activate.ps1
```

下文命令均在项目目录中运行。若不激活虚拟环境，可将 `python` 换成 `.\.venv\Scripts\python.exe`。

首次使用会将缺少的 Whisper 模型下载到 `models/`。GPU 听写需要相应的 CUDA/cuDNN 运行库；使用 CPU 可加 `--device cpu --model small`。音频由 PyAV 解码，通常无需单独安装 FFmpeg。

### 2. 配置翻译 API

编辑 `config.json` 的 `translation.api_key`，填入自己的密钥。模板已提供 DeepSeek 配置；使用其他兼容接口时，同时修改 `base_url` 和 `model`：

```json
{
  "translation": {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "api_key": "your-api-key"
  }
}
```

以上是配置节选，其余设置沿用模板。模型 ID 按服务商实际提供的值填写，也可通过 `SUBTITLE_API_KEY` 环境变量提供密钥。

API 接收字幕文本和所需上下文，音视频在本地处理。个人配置 `config.json` 已排除出 Git。仅听写或处理中文音频时，无需翻译 API。

### 3. 生成字幕

```powershell
python main.py "D:\video\sample.mp4"
```

默认自动识别语言，并在原文件旁生成 `sample.zh.lrc`。控制台提示和参数帮助使用英文。

## 常用命令

```powershell
# 指定日语，输出 SRT
python main.py "sample.mp4" --language ja --format srt

# 同时生成 LRC、SRT 和原文字幕
python main.py "sample.mp4" --format all --original

# 仅听写并导出原文
python main.py "sample.mp3" --transcribe-only

# 使用本地 Sakura 日译中（需先准备模型和运行库）
python main.py "sample.mp4" --translator sakura

# 分离并导出人声，隐藏逐句日志（需先准备分离资源）
python main.py "sample.mp4" -v -Q

# 使用较快的听写预设
python main.py "sample.mp4" -q normal
```

Sakura 仅用于日译中；选择它时，未显式设置的自动语言会按 `ja` 听写。资源准备见[详细配置](docs/CONFIGURATION.md#local-sakura)。

## 常用参数

| 参数 | 作用 |
| --- | --- |
| `--language` | `auto`、`zh`、`ja`、`en` 或 `ko` |
| `--format` | `lrc`（默认）、`srt` 或 `all` |
| `--quality` / `-q` | `high`（默认）或较快的 `normal` |
| `--translator` | `api`（默认）、`auto`（同 API）或 `sakura` |
| `--original` / `--transcribe-only` | 额外导出原文 / 仅导出原文 |
| `--separate` / `-s`、`--vocals` / `-v` | 分离人声 / 分离并导出人声 |
| `--quiet` / `-Q` | 隐藏逐句内容，保留进度和错误提示 |
| `--output-dir` | 指定输出目录 |
| `--dict` | 指定术语字典文件 |
| `--report` | 额外生成 `.quality.csv` 复核报告 |

完整参数列表：

```powershell
python main.py --help
```

`high` 默认使用 large-v2，优先保留轻声和词时间细节；`normal` 默认使用 turbo，处理较快。高精度局部复核会增加耗时，模型与复核条件见[听写配置](docs/CONFIGURATION.md#recognition)。小写 `-q` 控制预设，大写 `-Q` 控制日志。

## 输出与续跑

默认输出位置：

```text
D:\audio\sample.mp3
D:\audio\sample.zh.lrc
```

| 选项 | 生成文件 |
| --- | --- |
| 默认 | `.zh.lrc` |
| `--format srt` | `.zh.srt` |
| `--format all --original` | 中文字幕与原文 LRC、SRT，共四个文件 |
| `--transcribe-only` | 所选格式的 `.original.*`，默认 LRC |
| `-v` | 额外生成 `.vocals.wav` |
| `--report` | 额外生成 `.quality.csv` |

原文字幕保留输入语言。输出文件沿用原文件名，同名同格式文件会更新；可用 `--output-dir "D:\subtitles"` 更改位置。

任务进度保存在项目的 `.cache/` 中，重新运行同一命令即可复用听写、继续翻译。按 `Ctrl+C` 停止；首次听写完成后才保存整段听写，提前中断会在下次重新听写。

- `--retranslate`：复用听写，重新翻译。
- `--force-transcribe`：重新听写，并重置该任务的翻译。
- 修改输出格式或目录：继续复用听写和翻译。
- 修改字典：重新运行普通命令，仅刷新受影响的条目。

导出字幕的手动编辑只影响文件本身；续跑和重新翻译使用任务缓存。

## 更多文档

- [详细配置](docs/CONFIGURATION.md)：API、模型与 GPU、Sakura、人声分离、缓存行为。
- [字典与质量报告](docs/DICTIONARY.md)：术语维护、候选提取与导入、报告说明。
- [项目目录](docs/PROJECT.md)：源码结构、本地资源与版本控制。
- [运行库来源](runtime/README.md) · [翻译规范来源](prompts/README.md) · [GalTransl 字典来源](third_party/galtransl/README.md)。

## 许可证

代码与原创文档采用 [GPL-3.0-only](LICENSE)。第三方字典、运行库和模型遵循各自的许可，模型及运行库由使用者另行准备；来源与许可记录见上方文档。
