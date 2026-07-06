# 期末重点智能体 MVP

这是一个本地运行的课程复习 agent 原型。目标体验是：用户点击“启动学在吉大浏览器”，在专用浏览器里完成认证，之后系统自动收集可访问的视频、字幕/文字稿和往年题，生成期末重点、考题暗示和知识点优先级报告。

## 当前能力

- 受控浏览器模式：后端启动一个独立 Chromium profile，用户只在里面登录学在吉大。
- 后台监听专用浏览器里的媒体请求，自动收集 `mp4`、`m3u8`、字幕和页面已有文字稿。
- 下载时使用专用浏览器当前会话的临时请求头，提升登录态/签名 URL 场景的成功率。
- 支持手动上传往年题、课件、笔记、音视频和文本作为补充材料。
- 支持 `ffmpeg` 提取音频，支持可选 `faster-whisper` 本地转写。
- 支持前端配置 OpenAI-compatible LLM 的 `baseURL`、`APIKEY`、模型和温度。APIKEY 只放在当前浏览器会话里，不写入数据库、报告或日志。
- 根据老师提示词、课堂证据和往年题命中生成 Markdown 报告。
- Chrome 扩展仍保留为备用方案，但不再是主流程。

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000
```

## 推荐使用流程

1. 启动本地服务并打开 `http://127.0.0.1:8000`。
2. 点击“启动学在吉大浏览器”。
3. 在弹出的专用浏览器里正常登录学在吉大。
4. 打开目标课程视频并播放几秒。
5. 回到本地页面查看“自动收集到的资料”和“期末重点报告”。
6. 有往年题时，在“高级：往年题、LLM 和手动兜底导入”里上传或粘贴，报告会综合判断。

专用浏览器的登录态保存在 `data/browser-profile`，不会读取你的日常 Chrome 资料。

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

本项目只处理你有权访问的课程资料、老师授权资料或你手动上传的学习材料。本地服务不保存账号密码，不绕过登录、验证码、DRM、反下载策略或平台访问控制。若视频必须依赖加密播放器或 DRM，本项目不会也不应绕过这些限制。

## 后续方向

- 自动识别课程目录和章节标题，减少“未命名课程”。
- 对学在吉大已有转文字结果做更稳定的结构化抓取。
- 增加 OCR，处理扫描版 PDF 和图片题。
- 将报告拆成知识图谱、题型统计和复习计划。
