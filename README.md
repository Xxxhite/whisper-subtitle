# whisper-subtitle

简体中文 | [English](README.en.md)

一个面向本地音视频文件的命令行字幕工具：使用 faster-whisper 听写中文、日语、英语和韩语，通过翻译 API 或本地 Sakura 模型生成简体中文字幕，支持 LRC、SRT 导出。每次处理一个文件。

- 日语、英语、韩语默认使用 API 翻译；中文原文在本地转换为简体。
- 默认生成 LRC，并保存到原音视频所在目录。
- 支持人声分离、导出人声、静默运行和重复拟声词合并。
- 支持术语字典、候选术语提取、质量报告和任务续跑。

程序的控制台提示和参数帮助保留英文。详细说明见[字典使用指南](docs/DICTIONARY.md)和[项目目录说明](docs/PROJECT.md)。

## 安装

建议使用 Python 3.10–3.12。在 Windows PowerShell 中进入项目目录，创建环境并安装依赖：

```powershell
cd C:\path\to\whisper-subtitle
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
.\.venv\Scripts\Activate.ps1
```

下文的 `python main.py` 均在项目目录中、激活虚拟环境后运行。也可以直接使用 `.\.venv\Scripts\python.exe main.py`，省去激活步骤。

音频由 PyAV 解码，通常无需另外安装 FFmpeg。项目使用 faster-whisper 1.2.1，并将 PyAV 限制在 19 以下，以兼容该版本的解码接口。

模型和 GPU 运行库保存在本地，不随 Git 仓库提供。缺少 Whisper 模型时会自动下载至 `models/`；GPU 听写需要配置相应的 CUDA/cuDNN 依赖，也可以使用 `--device cpu`。Sakura 和人声分离所需的额外资源见后文。

## 配置翻译 API

编辑 `config.json` 中的 `translation` 部分。配置示例已填入 DeepSeek 接口，补入自己的 API key 即可：

```json
{
  "translation": {
    "backend": "api",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "api_key": ""
  }
}
```

以上为配置节选，其余选项可保留 `config.example.json` 的默认值。接口及可用模型以[服务商文档](https://api-docs.deepseek.com/)为准。

| 配置项 | 说明 |
| --- | --- |
| `backend` | 默认 `api`；日、英、韩使用 API，中文本地转换。`auto` 与此行为一致；`sakura` 选择本地日译中 |
| `base_url` | API 地址，程序自动追加 `/chat/completions`；也支持完整端点。服务商要求 `/v1` 时需自行包含 |
| `model` | 服务商提供的模型 ID |
| `api_key` | API 密钥；留空时可在交互式终端临时输入 |
| `api_key_env` | 密钥环境变量名，默认 `SUBTITLE_API_KEY`；读取顺序为环境变量、配置文件、交互输入 |
| `instructions` | 补充翻译要求，如称呼、术语或风格偏好 |
| `batch_size` | 每批字幕条数，默认 20 |
| `context_lines` | 每批附带的前后文条数，默认各 3 条 |
| `timeout_seconds` | 单次请求超时，默认 120 秒 |
| `max_retries` | 请求失败后的额外重试次数，默认 3 |

API 接收字幕文本和翻译所需的上下文，音视频文件在本地听写。`config.json` 已排除出 Git，`config.example.json` 中的密钥应保持为空。

接口需兼容 Chat Completions：接收 `model`、`messages`、`stream: false`，并在 `choices[0].message.content` 返回文本。程序检查字幕 ID、重试缺失或格式错误的结果，并保存已完成的翻译。

### 日译中翻译规范

日语通过 API 翻译时，会自动加载 `prompts/ja_zh_guidelines.txt`，应用自然中文、角色语气、人称关系、省略成分、敬称、文化背景、术语一致性和译后检查等要求。

规范参考了 VoiceTransl 的 Basic、增强版 v1/v2 及 GalTransl 翻译要求，并针对带时间轴字幕调整：每个字幕 ID 单独返回，语句重组限制在当前字幕内部。

可以编辑规范文件调整风格，或在 `translation.instructions` 中补充要求。规范内容参与翻译缓存校验；修改后会更新日语 API 翻译，并复用原听写。来源记录见 [prompts/README.md](prompts/README.md)。

## 基本用法

```powershell
# 自动识别语言，生成中文字幕 LRC
python main.py "D:\video\sample.mp4"

# 指定日语
python main.py "sample.mp4" --language ja

# 生成 SRT，或同时生成 LRC 和 SRT
python main.py "sample.mp4" --format srt
python main.py "sample.mp4" --format all

# 同时导出原文字幕
python main.py "sample.mp4" --original

# 仅听写并导出原文，不翻译
python main.py "sample.mp3" --transcribe-only

# 中文听写后直接转换为简体
python main.py "sample.wav" --language zh

# 使用 CPU 和较小模型
python main.py "sample.mp3" --device cpu --model small

# 查看全部参数
python main.py --help
```

省略输入文件时，程序会提示输入路径。支持的语言代码为 `zh`、`ja`、`en`、`ko`，默认 `auto` 自动识别，适合以一种主要语言为主的音视频。

### 常用参数

| 参数 | 用途 |
| --- | --- |
| `--language` | 指定原文语言 |
| `--quality` / `-q` | `high` 为默认完整度优先预设，`normal` 为较快预设 |
| `--model` | 指定 Whisper 模型名或本地模型目录 |
| `--device` | `auto`、`cpu` 或 `cuda` |
| `--compute-type` | 覆盖推理精度，如 `float16`、`int8_float16` |
| `--vad` / `--no-vad` | 开启或关闭听写前的语音活动过滤 |
| `--vad-threshold` | VAD 语音概率阈值，默认 0.5 |
| `--translator` | `api`、`auto` 或 `sakura` |
| `--separate` / `-s` | 先分离人声，再听写 |
| `--vocals` / `-v` | 分离并导出人声，自动启用 `-s` |
| `--quiet` / `-Q` | 隐藏逐句输出，保留阶段提示、进度、错误和文件路径 |
| `--sounds` | `merge` 合并连续重复的拟声词；`keep` 保留各条 |
| `--dict` | 指定自定义字典文件 |
| `--terms` | 从已有日语听写缓存中，通过 API 提取候选术语 |
| `--add-terms` | 将已确认的候选术语合并到字典，无需音视频参数 |
| `--report` | 额外导出字幕质量报告 |
| `--format` | `lrc`、`srt` 或 `all`，默认 `lrc` |
| `--original` | 同时导出原文字幕 |
| `--transcribe-only` | 仅导出原文字幕 |
| `--output-dir` | 指定输出目录，默认原文件所在目录 |
| `--retranslate` | 复用听写，重新翻译全部字幕 |
| `--force-transcribe` | 重新听写，并重置该任务的翻译缓存 |
| `--config` | 指定配置文件 |

小写 `-q` 控制听写预设，大写 `-Q` 控制逐句日志。

## 听写模型与预设

| 设置 | `high`（默认） | `normal` |
| --- | --- | --- |
| 自动选择的模型 | large-v2 | turbo |
| 自动选择的 GPU 精度 | FP16 | INT8/FP16 |
| 自动选择的 CPU 精度 | FP32 | INT8 |
| 听写前 VAD 过滤 | 关闭，处理完整音频 | 开启，默认阈值 0.5 |
| 单词级时间戳 | 开启 | 关闭 |
| 使用前文约束后续听写 | 关闭，减少错误传播 | 开启 |
| Beam size | 5 | 5 |
| 解码器无语音阈值 | 0.6 | 0.6 |

`high` 优先保留轻声对白和时间细节，需要更多时间与资源。解码器仍会进行自身的无语音判断；检查结果时可留意安静段落中的误识别。

```powershell
# 默认预设
python main.py "sample.wav" --language ja

# 切换较快预设
python main.py "sample.wav" -q normal

# 保留较快预设，但关闭听写前 VAD
python main.py "sample.wav" -q normal --no-vad

# 自定义过滤阈值、模型和精度
python main.py "sample.wav" --vad --vad-threshold 0.25
python main.py "sample.wav" --model large-v2 --compute-type float16
```

配置中的 `whisper_model: "auto"`、`compute_type: "auto"`、`vad_filter: null` 跟随预设；指定具体值后覆盖预设。`vad_threshold` 在开启 VAD 时生效。

程序会显示使用的模型、精度和 VAD 保留时长。若 VAD 保留比例偏低，会提示尝试关闭过滤。改变模型、预设、精度、设备或解码设置会重新听写；输出格式和目录变化会继续复用听写。

模型可从 Hugging Face 下载至 `models/`，也可以使用本地 CTranslate2 模型目录。例如已有 `models/faster-whisper-large-v2/` 时，`--model large-v2` 会优先使用它。`device: auto` 优先选择可用 NVIDIA GPU，否则使用 CPU。英文专用 `.en` 模型适用于英语音频。

## 可选的 Sakura 本地翻译

日语可以手动选择 Sakura：

```powershell
python main.py "sample.mp4" --translator sakura
```

选择 Sakura 时，如果没有填写 `--language` 且配置中的语言为 `auto`，会默认按 `ja` 听写。显式的 `--language` 和配置中指定的具体语言优先；使用 `--language auto` 可保留自动识别。其他听写设置相同时，已有的日语听写缓存可继续复用。

使用前需要准备以下本地资源，或在 `config.json` 的 `sakura` 部分指定路径：

- 模型：`models/Sakura-Galtransl-7B-v3.7.gguf`。
- llama.cpp 服务程序：`runtime/llama/llama-server.exe` 及配套运行库。

这些资源不随仓库提供。模型及使用说明见 [Sakura-GalTransl 模型页](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7)，运行库说明见 [runtime/README.md](runtime/README.md)。

| `sakura` 配置项 | 默认值或说明 |
| --- | --- |
| `server_path` | `runtime/llama/llama-server.exe`，相对于项目目录 |
| `model_path` | `models/Sakura-Galtransl-7B-v3.7.gguf`，相对于项目目录 |
| `gpu_layers` | 24；设为 0 时使用 CPU |
| `device` | `Vulkan0`，按本机设备调整 |
| `context_size` | 4096 tokens |
| `batch_size` | 每批 8 条字幕 |
| `startup_timeout_seconds` | 启动超时 180 秒 |
| `timeout_seconds` | 单次翻译超时 180 秒 |
| `glossary` | 旧版全局术语设置，每行 `原文->译文 # 备注`；日常维护建议使用 `dictionary.json` |

程序会在本地临时端口启动后台服务，并在结束或中断时关闭它。Sakura 使用适配其模型的短中文提示词；逐句翻译会省去历史上下文并使用较低温度，减少续写和提示词混入。批量返回条数异常时，会改为逐句重试该批次，再恢复正常批量处理。

切换 API 与 Sakura 会保留听写、更新翻译。`auto` 和 `api` 共享 API 翻译缓存；中文始终直接转换为简体。服务日志保存在 `.cache/sakura-server-<进程号>.log`。旧版提示词缓存中的异常条目会在下次运行时检查并修复，迁移备份为 `task.before-sakura-prompt-v3.json`。

模型页标注的许可为 CC BY-NC-SA 4.0，具体使用条件见上述模型页面。

## 可选的人声分离

`-s` 在听写前分离人声；`-v` 同时导出分离后的人声，自动包含 `-s`。

```powershell
python main.py "sample.mp4" -s
python main.py "sample.mp4" -v -Q
python main.py "sample.mp4" -v --output-dir "D:\subtitles" --format srt
```

使用前需要准备 `runtime/separate/separate.exe` 及其配套运行库，以及模型 `models/UVR_MDXNET_KARA_2.onnx`。这些资源保留在本地，路径可在 `separation` 配置中修改，来源说明见 [runtime/README.md](runtime/README.md)。

| `separation` 配置项 | 默认值或说明 |
| --- | --- |
| `enabled` | `false`；是否默认分离人声 |
| `export_vocals` | `false`；开启后导出人声，并自动启用分离 |
| `executable_path` | `runtime/separate/separate.exe` |
| `model_path` | `models/UVR_MDXNET_KARA_2.onnx` |
| `denoise` | `false`；额外降噪，会增加处理时间 |
| `chunks` | 每块 15 秒 |
| `margin` | 重叠区 44100 个采样点 |

分离有助于处理被音乐遮盖的人声。轻声、耳语和多人重叠片段建议结合导出的人声检查。人声导出为立体声 44.1 kHz PCM16 WAV，命名为 `<原文件名>.vocals.wav`，默认与原文件放在一起；字幕仍沿用原文件名和时间轴。人声会在听写、翻译前导出。

分离进程完成后才启动 Whisper，使用独立运行库，并在取消任务时退出。首次运行可能需要编译音频处理函数，耗时较长。

分离结果、验证记录和日志保存在 `.cache/<文件哈希>/separation/<设置哈希>/`，后续会验证并复用人声文件。开关分离或更改分离模型、运行程序、分离设置会重新听写；仅更改 `-v`、`-Q`、输出格式或目录会继续复用缓存。

## 字典与候选术语

项目默认读取 `dictionary.json`，包含 52 条日中术语提示：32 条通用词、17 条相关成人题材词和 3 个书写变体。词条用于原文匹配后提供给 API/Sakura；译前和译后强制替换规则默认留空。来源快照和许可证保存在 [third_party/galtransl](third_party/galtransl/README.md)。

字典支持三个阶段：`pre` 译前修正、`glossary` 术语提示、`post` 带原文条件的译后修正。术语优先匹配长词；短词在句中另有独立出现时，仍会匹配。译前、译后规则按文件顺序执行。

```powershell
# 使用另一份字典
python main.py "sample.mp4" --dict "D:\rules\custom.json"

# 额外导出质量报告
python main.py "sample.mp4" --report
```

质量报告为 `<原文件名>.quality.csv`，可用于检查日文残留、术语未使用、异常重复、额外英文、标点不成对、译文膨胀和时间重叠等问题。报告只列出待检查项。完整格式见[字典使用指南](docs/DICTIONARY.md)。

### 生成候选术语

对已经保存听写缓存的日语文件运行：

```powershell
python main.py "sample.mp4" --terms
```

此命令通过配置中的 API 提取人名、专用词等候选术语，即使普通字幕翻译选择了 Sakura，也仍使用 API。无需新增本地模型。输出文件默认与原文件放在一起，或保存到 `--output-dir` 指定的目录：

- `sample.terms.csv`：建议译名、备注、出现次数、不同译名建议及带时间的原句示例。
- `sample.terms.json`：候选字典，所有词条默认 `enabled: false`。

检查 CSV，按需修改 JSON 中的译名，把确认的词条设为 `"enabled": true`，然后导入：

```powershell
python main.py --add-terms "D:\video\sample.terms.json"
python main.py "sample.mp4"
```

导入会备份当前字典，跳过重复项，并在译名冲突时停止。下次正常运行只重新翻译受新术语影响的句子。没有听写缓存时，先正常处理文件或运行 `--transcribe-only`。

提取进度保存在 `.cache/<文件哈希>/terms-state.json`，失败或中断后可用同一命令继续。已有候选文件会保留，需生成另一份时可更换 `--output-dir`。`--terms`、`--add-terms` 与听写、字幕导出选项分开使用，更多说明见[候选术语指南](docs/DICTIONARY.md#generate-candidate-terms)。

## 控制台输出与字幕清理

默认逐句输出听写和译文，格式如下：

```text
[ASR 001 00:01] 识别出的原句
[ZH  001 00:01] 翻译后的简体中文
```

`ASR` 表示原文，`ZH` 表示译文。时间显示为 `mm:ss`，超过一小时后为 `hh:mm:ss`。字幕文件保留完整的时间精度。续跑时也会显示已缓存的句子。

翻译过程显示开始提示、逐句译文和最终汇总，不会在每句之间插入进度日志。使用 `-Q` 后隐藏逐句内容，翻译进度每五秒刷新一次；配置 `quiet: true` 可默认启用。重试、错误和输出路径仍会显示。

最终中文字幕会过滤纯 emoji 识别结果，默认最短显示时长为 0.8 秒，并避免字幕时间重叠。`minimum_subtitle_seconds` 可调整时长，设为 0 时关闭该项调整。

`review_audio: true` 默认启用，会对混合 emoji/文字、未翻译的日文、开场前可疑的结束语等片段进行本地音频复查。可恢复的片段重新听写，并更新对应翻译；确认为无语音的伪字幕会从最终输出中省略。原始记录及复查信息留在任务缓存，首次复查前会保存 `task.before-audio-review.json`。翻译仍无法完成时会保存进度并暂停。

连续重复的已知笑声、拟声词默认合并：相邻条目需为同类声音，间隔不超过 1 秒，合并跨度不超过 10 秒。有意义的对白、应答和感叹声保持独立。原始听写、原文导出和翻译缓存保留各条记录。

```powershell
# 保留重复拟声词的每条字幕
python main.py "sample.mp4" --sounds keep
```

`merge_repeated_sounds: false` 可在配置中关闭合并。切换此选项会复用已有听写和翻译。代码修改在新启动的任务中生效；已运行的任务可停止后用同一命令续跑。

## 输出位置与任务续跑

默认只输出简体中文 LRC：

```text
D:\audio\sample.mp3
D:\audio\sample.zh.lrc
```

| 选项 | 输出文件 |
| --- | --- |
| 默认 / `--format lrc` | 中文字幕 `.zh.lrc` |
| `--format srt` | 中文字幕 `.zh.srt` |
| `--format all` | 中文字幕 LRC 和 SRT |
| `--original` | 额外输出所选格式的原文 `.original.*` |
| `--transcribe-only` | 只输出原文，默认 `.original.lrc` |
| `--vocals` / `-v` | 额外输出 `.vocals.wav`，自动启用人声分离 |

例如 `--format all --original` 会生成四个字幕文件。SRT 包含每条字幕的起止时间；LRC 使用句级时间，并在空档和结尾写入空白时间标记，实际显示效果取决于播放器。

`output_dir: "source"` 表示原文件目录，可在配置中修改，或通过 `--output-dir "D:\subtitles"` 临时指定。同名、同格式文件会更新，其他格式的已有文件会保留。

任务缓存独立保存在项目的 `.cache/<文件内容哈希>/task.json`，包含听写和翻译进度。再次运行同一命令会复用完整听写并继续未完成的翻译。按 `Ctrl+C` 可停止任务；听写在完成后统一保存，若在听写完成前中断，下次会重新听写。

- `--retranslate`：保留听写，重新翻译全部字幕。
- `--force-transcribe`：重新听写，并重置该任务翻译。
- 修改字典：仅刷新有效翻译输入或命中术语发生变化的条目；译后规则可复用模型原始译文。
- 修改翻译模型、接口或全局提示词：复用听写，更新翻译。
- 修改输出格式、目录或重复拟声词合并方式：复用听写和翻译。

命令行的输入、`--config`、`--dict` 和 `--output-dir` 相对路径基于当前终端目录；配置文件中的相对模型、字典及输出路径基于项目目录，`output_dir: "source"` 除外。

导出的字幕可以自行编辑。重新翻译读取的是 `task.json` 中的听写，导出文件的手动修改不会回写到任务缓存。

## 许可证

本项目的代码和原创文档采用 [GNU General Public License v3.0](LICENSE)（`GPL-3.0-only`）。使用、修改和分发时，请遵守许可证中的相应条件。

第三方资源保留各自的版权和许可：

- GalTransl 字典的来源、修改记录和 GPL-3.0 许可保存在 [third_party/galtransl](third_party/galtransl/README.md)。
- 日译中翻译规范的参考来源记录在 [prompts/README.md](prompts/README.md)。
- Python 依赖、可选运行库和模型遵循各自的许可证。模型和运行库不随本仓库提供；Sakura 模型的具体条件见[模型页面](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7)，本地运行库来源见 [runtime/README.md](runtime/README.md)。

## 参考项目

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Whisper](https://github.com/openai/whisper)
- [OpenCC Python](https://pypi.org/project/opencc-python-reimplemented/)
- [Sakura-GalTransl](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7)
- [llama.cpp](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)
- [VoiceTransl](https://github.com/shinnpuru/VoiceTransl)
- [GalTransl](https://github.com/GalTransl/GalTransl)
