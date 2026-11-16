# MGU Assistant 中文说明

[English](README.md) · [Italiano](README.it.md) · [原项目](https://github.com/IvanBiondi/mgu-assistant)

MGU Assistant 是面向 BMW MGU iDrive 7 的 Windows 引导工具，提供 ENET 检查、SSH 设置和本地 MGU Store 安装。项目处于 Beta 阶段：上游报告过一位车主完成安装，自动化测试使用模拟响应。这不代表所有车型或固件均兼容。

**简体中文汉化：小白151／小白科技杂物社（[JackieZ123430](https://github.com/JackieZ123430)）。** 原软件版权与许可见 [LICENSE](LICENSE)，第三方来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 中文界面

简体中文系统自动显示中文，其他系统默认英文。启动前可通过 `MGU_UI_LANGUAGE` 指定 `zh-CN` 或 `en`，更改后重新启动。PowerShell 示例：

```powershell
$env:MGU_UI_LANGUAGE = 'zh-CN'
python main.py --demo
```

发行版同样支持此环境变量，在相同终端启动 `MGU-Assistant.exe` 即可。演示模式使用示例数据并阻止车辆操作。原后端与上游命令的诊断输出保留原文，便于排障。

## 五步流程

1. **连接**：停车并打开点火开关，连接 ENET，选择网卡，执行电脑检查和只读主机识别。
2. **备份与解锁**：解锁前使用 BimmerCode 读取 HU_MGU 并导出原始备份，核对 VIN、主机类型、软件版本、供电和实体钥匙。已有 root 访问时跳过刷写。
3. **密钥与编码**：选择无扩展名的 `id_rsa`；读取并确认主机服务器指纹，验证 root 登录。按需恢复原始编码并检查原车功能。服务器指纹与私钥指纹不同。
4. **安装商店**：校验本地组件后安装。首次安装使用离线组件；后续更新和新增应用可能需要车机联网。
5. **重启与验证**：停车状态下单独确认重启，等待 iDrive 恢复，再检查商店、音频、菜单、摄像头及其他原车功能。

刷写可能清除编码／CAFD 和数字钥匙配对，甚至损坏主机。编码备份不保留数字钥匙配对。本程序不能验证 BimmerCode 备份内容。操作中请保持供电和 ENET 连接。发生异常时保留日志，不要重复刷写或自动修复。勾选项是用户确认，并非自动测试证据。SHA-256 校验只验证文件完整性，不证明固件兼容性。

## 本地开发

上游要求 Windows、带 Tkinter 的 Python 3.12。按原项目固定的版本和校验值准备资源：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/prepare_resources.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --demo
```

使用 `scripts/build.py` 构建，`scripts/package.py` 打包。不要提交下载的组件、私钥、真实车辆标识、日志、备份或状态目录。校验失败时应调查原因，不要修改预期哈希来绕过校验。

[兼容性](docs/compatibility.md) · [故障排查](docs/troubleshooting.md) · [验证记录](docs/validation.md) · [贡献指南](CONTRIBUTING.md)

汉化测试在电脑上进行，不包含真实车辆刷写、安装或重启测试。

<!-- Localization provenance: XIAOBAI-ZHCN-20261116; translation by 小白151 / JackieZ123430. -->
