# AstrBot Minecraft 适配器插件

连接 Minecraft 服务器和 AstrBot，实现消息互通和服务器管理功能。

## 功能特性

- ✅ **双向消息转发** - Minecraft 聊天消息转发到 AstrBot，AstrBot 也可以发送消息到 Minecraft
- ✅ **WebSocket 实时通信** - 使用 WebSocket 实现实时双向通信
- ✅ **REST API 支持** - 提供 HTTP 接口查询服务器状态和玩家信息
- ✅ **服务器状态查询** - 查看在线玩家、TPS、内存使用等信息
- ✅ **远程指令执行** - 通过 AstrBot 执行 Minecraft 服务器指令
- ✅ **玩家事件通知** - 玩家加入/离开自动通知
- ✅ **自动重连** - 连接断开后自动重新连接
- ✅ **权限管理** - 可设置仅管理员使用

## 前置要求

### Minecraft 服务器端

1. **服务器核心**: Paper, Spigot, Leaf 等主流插件服核心
2. **Minecraft 版本**: 1.20.x 或 1.21.x
3. **Java 版本**: 17+
4. **AstrBot Adapter 插件**: 从 [GitHub Releases](https://github.com/railgun19457/AstrBotAdapter/releases) 下载并安装到 Minecraft 服务器

### AstrBot 端

1. **Python**: 3.10+
2. **依赖库**: 
   - `websockets` - WebSocket 客户端
   - `aiohttp` - 异步 HTTP 客户端

## 安装步骤

### 1. 安装 Minecraft 服务器插件

1. 下载 [AstrBot Adapter](https://github.com/railgun19457/AstrBotAdapter/releases) 最新版本
2. 将 jar 文件放入 Minecraft 服务器的 `plugins` 目录
3. 重启 Minecraft 服务器
4. 插件会自动生成配置文件 `plugins/AstrbotAdapter/config.yml`

### 2. 配置 Minecraft 服务器插件

编辑 `plugins/AstrbotAdapter/config.yml`:

```yaml
websocket:
  enabled: true
  host: "0.0.0.0"
  port: 8765
  token: "your_secure_token_here"  # 会自动生成

rest-api:
  enabled: true
  host: "0.0.0.0"
  port: 8766
  token: "your_secure_token_here"  # 会自动生成
```

**重要**: 首次启动时插件会自动生成安全的 Token，请在控制台中查看并记录下来。

### 3. 安装 AstrBot 插件

1. 将本插件文件夹放入 AstrBot 的 `data/plugins/` 目录
2. 重启 AstrBot 或重新加载插件

### 4. 配置 AstrBot 插件

在 AstrBot 的 WebUI 中配置插件：

- **启用**: 勾选启用插件
- **WebSocket 服务器地址**: 填写 Minecraft 服务器的 IP 地址
- **WebSocket 服务器端口**: 默认 8765
- **WebSocket Token**: 从 Minecraft 服务器配置文件中获取
- **REST API 服务器地址**: 填写 Minecraft 服务器的 IP 地址
- **REST API 服务器端口**: 默认 8766
- **REST API Token**: 从 Minecraft 服务器配置文件中获取（通常与 WebSocket Token 相同）
- **消息转发目标会话**: 填写要转发 Minecraft 消息的目标会话 ID（可选，格式见下文）

#### 配置消息转发目标

如果你想将 Minecraft 的聊天消息和玩家进出消息转发到特定的 QQ 群或其他平台，需要配置"消息转发目标会话"。

格式：`platform_name:message_type:session_id`

示例：
- QQ 群：`aiocqhttp:group:123456789`
- Telegram 群组：`telegram_bot:group:-1001234567890`
- 私聊：`aiocqhttp:private:987654321`

支持配置多个目标，每行一个：
```
aiocqhttp:group:123456789
aiocqhttp:group:987654321
```

留空则不转发消息。

## 使用指南

### 基本指令

所有指令都以 `/mc` 开头（可在配置中自定义）:

#### 查看服务器状态
```
/mc status
```
显示服务器在线状态、版本、玩家数、TPS、内存使用等信息。

#### 查看在线玩家
```
/mc players
```
显示详细的玩家列表，包括血量、等级、游戏模式、世界、延迟等。

#### 发送消息到 Minecraft
```
/mc say 大家好！
```
向 Minecraft 服务器发送消息，会显示发送者名称。

#### 执行服务器指令
```
/mc cmd list
/mc cmd say Hello World
/mc cmd weather clear
```
执行 Minecraft 服务器控制台指令（需要管理员权限）。

#### 重新连接服务器
```
/mc reconnect
```
手动重新连接到 Minecraft 服务器。

#### 查看帮助
```
/mc help
```
显示完整的帮助信息。

## 配置说明

### 主要配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | false | 是否启用插件 |
| `websocket_host` | string | localhost | WebSocket 服务器地址 |
| `websocket_port` | int | 8765 | WebSocket 服务器端口 |
| `websocket_token` | string | "" | WebSocket 认证 Token |
| `rest_api_host` | string | localhost | REST API 服务器地址 |
| `rest_api_port` | int | 8766 | REST API 服务器端口 |
| `rest_api_token` | string | "" | REST API 认证 Token |
| `auto_reconnect` | bool | true | 是否自动重连 |
| `reconnect_interval` | int | 5 | 重连间隔(秒) |
| `forward_chat_to_astrbot` | bool | true | 是否转发聊天消息 |
| `forward_join_leave_to_astrbot` | bool | true | 是否转发玩家进出消息 |
| `forward_target_session` | text | "" | 消息转发目标会话，格式：platform_name:message_type:session_id |
| `status_check_interval` | int | 300 | 状态检查间隔(秒) |
| `mc_command_prefix` | string | /mc | Minecraft 指令前缀 |
| `admin_only` | bool | false | 是否仅管理员可用 |

## 常见问题

### 1. 连接失败

**问题**: 插件显示 "WebSocket 连接错误"

**解决方法**:
- 检查 Minecraft 服务器是否运行
- 检查防火墙是否开放 8765 和 8766 端口
- 确认 IP 地址和端口配置正确
- 查看 Minecraft 服务器日志确认插件是否正常运行

### 2. 认证失败

**问题**: 插件显示 "认证失败，请检查 Token"

**解决方法**:
- 确认 Token 与 Minecraft 服务器配置文件中的 Token 一致
- Token 区分大小写，请仔细核对
- 可以在 Minecraft 服务器控制台执行 `/astrbot reload` 查看 Token

### 3. 消息转发不工作

**问题**: Minecraft 聊天消息没有转发到 AstrBot

**解决方法**:
- 确认 `forward_chat_to_astrbot` 配置为 true
- 检查 WebSocket 连接是否正常（查看日志中是否有 "认证成功" 消息）
- 目前消息转发功能需要进一步开发，请参考代码中的 TODO 注释

### 4. 无法执行指令

**问题**: 执行 `/mc cmd` 指令没有效果

**解决方法**:
- 检查是否有管理员权限（如果 `admin_only` 为 true）
- 确认 WebSocket 连接状态正常
- 指令不需要包含斜杠，例如使用 `/mc cmd say Hello` 而不是 `/mc cmd /say Hello`

## 安全建议

1. **使用强 Token** - 使用至少 32 个字符的随机字符串作为认证 Token
2. **限制访问** - 在 Minecraft 服务器配置中，将 `host` 设置为 `127.0.0.1` 以限制只能本地访问
3. **使用 VPN** - 如果 AstrBot 和 Minecraft 服务器不在同一台机器上，建议使用 VPN 连接
4. **定期更换 Token** - 定期更换认证 Token 以提高安全性
5. **启用管理员限制** - 将 `admin_only` 设置为 true，限制只有管理员才能使用

## 开发信息

- **作者**: Railgun19457
- **仓库**: [https://github.com/railgun19457/AstrBotAdapter](https://github.com/railgun19457/AstrBotAdapter)
- **许可证**: MIT License

## 更新日志

### v1.0.0 (2024-11-09)
- 首次发布
- 支持 WebSocket 实时通信
- 支持 REST API 查询
- 实现基本的消息转发和指令执行功能
- 支持自动重连

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License
