# 期末重点智能体 MVP

这是一个本地运行的课程复习 agent 原型。目标体验是：用户在浏览器里正常登录“学在吉大”，打开课程视频并播放几秒，系统自动收集可访问的视频、字幕/文字稿和后续上传的往年题，然后生成期末重点、考题暗示和知识点优先级报告。

## 当前能力

- Chrome 扩展后台自动捕获授权页面里的 `mp4` / `m3u8` / 媒体请求。
- 扩展会优先用浏览器登录态直接上传可访问视频；失败时把候选 URL 和页面文字稿交给本地后端兜底。
- 页面已有转文字、字幕、文字稿时会自动提取并导入。
- 支持手动上传往年题、课件、笔记、音视频和文本作为补充材料。
- 支持 `ffmpeg` 提取音频，支持可选 `faster-whisper` 本地转写。
- 支持前端配置 OpenAI-compatible LLM 的 `baseURL`、`APIKEY`、模型和温度。APIKEY 只放在当前浏览器会话里，不写入数据库、报告或日志。
- 根据老师提示词、课堂证据和往年题命中生成 Markdown 报告。

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000
```

## 推荐使用流程

1. 启动本地服务并打开 `http://127.0.0.1:8000`。
2. 在 Chrome 打开 `chrome://extensions/`，开启开发者模式，加载扩展目录：

```text
D:\QIMO_AGENT_TEST\browser-extension\qimo-catcher
```

3. 在 Chrome 里正常登录学在吉大。
4. 打开目标课程视频并播放几秒。
5. 回到本地页面查看“自动收集到的资料”和“期末重点报告”。
6. 有往年题时，在“高级：往年题、LLM 和手动兜底导入”里上传或粘贴，报告会综合判断。

扩展弹窗只是状态面板。正常情况下不需要点“导入”；只有自动捕获不理想时才用“Import now”兜底。

## LLM 语义分析

前端可以直接配置 OpenAI-compatible 接口：

- `baseURL`：例如 `https://api.openai.com/v1`，也可以是 DeepSeek、硅基流动、vLLM、Ollama 等兼容地址。
- `APIKEY`：仅保存在浏览器 sessionStorage，随“生成报告”请求发给本地后端，不持久化。
- `模型`：按服务商实际模型名填写。
- `温度`：默认 `0.2`。

不开启 LLM 时，系统仍会使用本地规则分析。开启后，后端调用 `${baseURL}/chat/completions`，把课堂文字摘录、规则分析出的候选知识点和往年题证据交给模型，再合并进报告。

## 自动转写

默认不强制安装 Whisper，避免首次安装过重。需要本地自动转写时：

```powershell
.\.venv\Scripts\python -m pip install faster-whisper
$env:ENABLE_WHISPER="1"
$env:WHISPER_MODEL="small"
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

如有 NVIDIA GPU，可按本机 CUDA 环境调整 `WHISPER_DEVICE` 和 `WHISPER_COMPUTE_TYPE`。

## 合规边界

本项目只处理你有权访问的课程资料、老师授权资料或你手动上传的学习材料。本地服务不读取账号、密码或浏览器 Cookie；扩展也不会绕过登录、验证码、DRM、反下载策略或平台访问控制。若视频必须依赖加密播放器或 DRM，本项目不会也不应绕过这些限制。

## 后续方向

- 自动识别课程目录和章节标题，减少“未命名课程”。
- 对学在吉大已有转文字结果做更稳定的结构化抓取。
- 增加 OCR，处理扫描版 PDF 和图片题。
- 将报告拆成知识图谱、题型统计和复习计划。
