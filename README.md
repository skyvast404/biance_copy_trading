# Binance Copy Trading Bot

自动复制主账户交易到多个跟随账户的币安交易机器人。

## ⚠️ 重要警告

- **本项目仅供学习和研究使用**
- **请先在测试网环境充分测试后再考虑实盘使用**
- **加密货币交易存在风险，请谨慎使用**
- **作者不对使用本软件造成的任何损失负责**

## ✨ 特性

- 🔄 **实时跟单** - 通过 WebSocket 实时监控主账户交易
- 📊 **灵活配置** - 支持多个跟随账户，每个账户可设置不同的跟单比例
- 🛡️ **风险控制** - 支持最小/最大订单数量限制、交易对过滤
- 🔌 **自动重连** - WebSocket 断线自动重连
- 📝 **详细日志** - 完整的交易日志记录和统计
- ⚙️ **易于配置** - YAML 配置文件，简单直观

## 📋 系统要求

- Python 3.7+
- 币安账户（主账户 + 跟随账户）
- API Key 和 Secret（需要交易权限，不要授予提现权限）

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

复制配置文件模板：

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，填入你的 API 凭证：

```yaml
# 测试网地址（推荐先用测试网）
base_url: "https://testnet.binance.vision"

# 主账户配置
master:
  api_key: "你的主账户API_KEY"
  api_secret: "你的主账户API_SECRET"

# 跟随账户配置
followers:
  - name: "follower_1"
    api_key: "跟随账户1的API_KEY"
    api_secret: "跟随账户1的API_SECRET"
    scale: 1.0  # 跟单比例：1.0 = 相同数量，0.5 = 一半数量
    enabled: true
```

### 3. 运行

```bash
python main.py
```

或指定配置文件：

```bash
python main.py --config my_config.yaml
```

### 4. 停止

按 `Ctrl+C` 优雅停止程序。

## 📁 项目结构

```
copy_trade/
├── main.py                      # 主程序入口
├── config.yaml                  # 配置文件（需要创建）
├── config.example.yaml          # 配置文件模板
├── requirements.txt             # Python 依赖
├── README.md                    # 项目文档
├── .gitignore                   # Git 忽略文件
├── logs/                        # 日志目录（自动创建）
│   └── copy_trade.log
└── src/                         # 源代码
    ├── __init__.py
    ├── config_loader.py         # 配置加载器
    ├── binance_client.py        # Binance API 客户端
    ├── copy_trade_engine.py     # 跟单引擎核心
    └── logger.py                # 日志配置
```

## ⚙️ 配置说明

### 基础配置

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `base_url` | Binance API 地址 | 测试网: `https://testnet.binance.vision`<br>生产: `https://api.binance.com` |

### 主账户配置

| 配置项 | 说明 |
|--------|------|
| `master.api_key` | 主账户 API Key |
| `master.api_secret` | 主账户 API Secret |

### 跟随账户配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `name` | 账户名称（用于日志） | - |
| `api_key` | 跟随账户 API Key | - |
| `api_secret` | 跟随账户 API Secret | - |
| `scale` | 跟单比例倍数 | 1.0 |
| `enabled` | 是否启用该账户 | true |

### 交易设置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `follower_order_type` | 跟随账户订单类型 | `MARKET` |
| `min_order_quantity` | 最小订单数量 | 0.001 |
| `max_order_quantity` | 最大订单数量 | 1000.0 |
| `allowed_symbols` | 允许的交易对（空=全部） | [] |
| `excluded_symbols` | 排除的交易对 | [] |

### 日志配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `level` | 日志级别 | `INFO` |
| `file` | 日志文件路径 | `logs/copy_trade.log` |
| `max_bytes` | 单个日志文件最大大小 | 10485760 (10MB) |
| `backup_count` | 保留的日志文件数量 | 5 |
| `console_output` | 是否输出到控制台 | true |

### WebSocket 配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `reconnect_enabled` | 是否启用自动重连 | true |
| `reconnect_delay` | 重连延迟（秒） | 5 |
| `max_reconnect_attempts` | 最大重连次数 | 10 |
| `keepalive_interval` | 保活间隔（秒） | 1800 |

## 🔐 安全建议

1. **API Key 安全**
   - 不要授予 API Key 提现权限
   - 设置 IP 白名单
   - 定期更换 API Key
   - 不要将 config.yaml 提交到 Git

2. **测试建议**
   - 先在测试网充分测试
   - 从小金额开始
   - 监控初期运行情况

3. **风险控制**
   - 设置合理的 `min_order_quantity` 和 `max_order_quantity`
   - 使用 `allowed_symbols` 限制交易对
   - 定期检查日志

## 🔧 工作原理

1. **连接监听**
   - 程序通过 WebSocket 连接到主账户的 User Data Stream
   - 实时接收主账户的订单执行报告

2. **订单复制**
   - 当主账户订单成交时（status=FILLED, exec_type=TRADE）
   - 解析成交信息（交易对、方向、数量、价格）
   - 按照配置的比例计算跟随账户的订单数量
   - 向跟随账户发送市价单（确保立即成交）

3. **错误处理**
   - WebSocket 断线自动重连
   - 订单失败记录日志但不影响其他账户
   - 详细的统计信息

## 📊 日志示例

```
2024-11-02 10:30:15 - root - INFO - ✓ Connected to master account user data stream
2024-11-02 10:31:20 - root - INFO - 📊 Master executed: BUY 0.001 BTCUSDT @ 35000.0
2024-11-02 10:31:21 - root - INFO - ✓ Follower 'follower_1': BUY 0.001 BTCUSDT - orderId=12345
2024-11-02 10:31:21 - root - INFO - ✓ Follower 'follower_2': BUY 0.0005 BTCUSDT - orderId=12346
```

## 🐛 常见问题

### 1. 连接失败

**问题**: `Failed to create listen key`

**解决**:
- 检查 API Key 和 Secret 是否正确
- 确认 API Key 有交易权限
- 检查网络连接

### 2. 订单失败

**问题**: `Failed to place order - Insufficient balance`

**解决**:
- 检查跟随账户余额是否足够
- 调整 `scale` 参数降低跟单比例

### 3. 数量精度错误

**问题**: `LOT_SIZE filter error`

**解决**:
- 调整 `min_order_quantity` 参数
- 确保数量符合交易对的精度要求

## 📝 待改进功能

- [ ] 支持期货合约跟单
- [ ] 更完善的风险管理（每日交易次数限制、亏损限制）
- [ ] 数量精度自动处理
- [ ] Web 管理界面
- [ ] 交易统计和报表
- [ ] 支持更多交易所

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## ⚖️ 免责声明

本软件仅供学习和研究使用。使用本软件进行交易的所有风险由使用者自行承担。作者不对使用本软件造成的任何直接或间接损失负责。

加密货币交易存在高风险，可能导致部分或全部资金损失。请确保您完全理解相关风险，并在自己能够承受的范围内进行交易。

## 📞 支持

如有问题或建议，请提交 Issue。

---

**⚠️ 再次提醒：请务必先在测试网环境充分测试！**
