# VideoPipe

VideoPipe 是一个以网页端为主的视频链接下载器。用户粘贴视频链接或分享文本后，可以解析视频信息、选择最佳画质、720P 或 480P，并将视频下载到本地。

当前仓库是 V1 测试版本，暂不包含广告、会员、支付、AI 翻译、配音、登录内容与 Cookie 导入。

## V1 功能

- 视频链接与分享文本解析
- 最佳画质、720P、480P 三档选择
- 最多三个任务并行下载，其余任务自动排队
- 实时下载进度
- 正在下载的任务可以立即停止
- 服务重启后恢复未完成队列
- HLS/m3u8、DASH/MSS 与直接媒体链接处理
- yt-dlp 解析失败时使用 Playwright + Edge 发现网页媒体流

## 下载引擎

- `yt-dlp`：网站解析、普通视频和 HLS 分片下载
- `Aria2`：普通直链多连接下载
- `N_m3u8DL-RE`：DASH/MSS 清单下载
- `FFmpeg`：必要的媒体封装与处理
- `Playwright + Microsoft Edge`：网页媒体流发现

不同网站会随时调整页面和接口，因此不能保证所有链接永久可用。当前版本只处理点播视频，不处理直播或直播回放，也不处理 DRM 加密内容。

## 系统要求

当前版本面向 Windows：

- Python 3.11+
- Microsoft Edge
- Aria2 Windows 可执行文件
- N_m3u8DL-RE Windows 可执行文件

第三方二进制文件不会提交到仓库，请放置在以下路径：

```text
vendor/
├── N_m3u8DL-RE/
│   └── N_m3u8DL-RE.exe
└── aria2/
    └── aria2-1.37.0-win-64bit-build1/
        └── aria2c.exe
```

FFmpeg 由 `imageio-ffmpeg` Python 依赖提供。

## 本地启动

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8765
```

浏览器打开：

```text
http://127.0.0.1:8765/
```

开发时需要自动重载，可以在启动命令末尾添加 `--reload`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

## 数据目录

任务数据库与临时下载文件保存在 `data/`。下载文件交付给浏览器后，服务会清理对应的临时任务目录。

以下内容不会提交到 Git：

- Python 虚拟环境与缓存
- 任务数据库和下载文件
- 未完成的下载分片
- 第三方下载器二进制文件

## 当前验证范围

- 已测试常见社交视频平台、微信视频号公开分享链接、直接 MP4 与公开 HLS/m3u8
- 已验证三档画质、并行队列、实时进度和下载中断
- 部分平台的公开页面可能因为登录要求、地区限制、风控或接口调整而解析失败
- 微信视频号公开分享链接目前依赖第三方解析服务，服务可用性不由 VideoPipe 控制

## 后续计划

- Windows 桌面客户端
- 用户任务隔离、限流与公网部署保护
- 会员、广告与最高画质权限
- 视频 AI 多语言字幕、翻译和配音
- Cookie 导入与用户已获授权内容下载

请仅下载自己拥有、已经购买或获得授权使用的内容，并遵守内容来源网站的使用条款及所在地法律。
