# Local GPU runtime libraries

The following files in `cuda/` were copied from the existing local VoiceTransl installation:

```text
D:\application\VoiceTransl\_internal\whisper-faster\_xxl_data\torch\lib
```

- `cublas64_12.dll`
- `cublasLt64_12.dll`
- `cudart64_12.dll`

Before transcription, the application adds this directory to the current process's DLL search path. System PATH is unchanged. These binaries are ignored by Git.

VoiceTransl's cuDNN 8 files were not copied. The project uses CTranslate2 4.9 and retains its bundled cuDNN 9 interface component.

## Sakura runtime

`llama/` contains `llama-server.exe` and the DLLs copied from:

```text
D:\application\VoiceTransl\_internal\llama
```

The matching model is stored at `models/Sakura-Galtransl-7B-v3.7.gguf`. These model and runtime files occupy about 5.91 GiB and are ignored by Git. The application manages its own hidden server on `127.0.0.1`, with a dynamically selected port, and closes it when translation finishes or stops.

The model is licensed under CC BY-NC-SA 4.0. See the [Sakura model card](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7) for its license and usage details.

## Vocal separation runtime

`separate/separate.exe` and its complete `_internal/` runtime were copied from `D:\application\VoiceTransl\_internal\separate`. The ONNX model is stored separately at `models/UVR_MDXNET_KARA_2.onnx`. Model and runtime binaries are local resources ignored by Git.

The application uses this standalone runtime without installing its Python dependencies into `.venv`. It supplies a private input WAV and explicit model parameters, captures output in the task's `separator.log`, and sets `NUMBA_CACHE_DIR` to `runtime/separate/numba-cache/`. Its process exits before recognition begins. No external application settings or credentials are used.

The frozen runtime includes librosa 0.11.0 bytecode without matching source paths. Numba ignores an explicit cache directory when those source paths are absent, then falls back to the Windows user cache. To make project-local caching work, matching `.py` source files from the official `librosa==0.11.0` wheel were restored under `separate/librosa/`. The separator runs with a stable working directory so this cache is reusable across media files. Librosa uses the ISC license.
