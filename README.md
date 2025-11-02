# 币安合约跟单交易机器人

专为币安合约（Binance Futures）设计的专业级跟单交易系统。

> **注意**: 本项目仅支持合约交易，不支持现货交易。

## ⚠️ 重要警告

- **合约交易风险极高，可能导致全部本金损失**
- **杠杆交易会放大收益和亏损**
- **请务必在测试网充分测试后再考虑实盘**
- **建议从低杠杆和小资金开始**
- **作者不对使用本软件造成的任何损失负责**

## ✨ 核心特性

### 🎯 基础功能
- 🔄 **实时跟单** - WebSocket 实时监控主账户合约交易
- 📊 **灵活配置** - 支持多个跟随账户，每个账户独立配置比例
- 🛡️ **风险控制** - 最小/最大订单数量、交易对过滤
- 🔌 **自动重连** - WebSocket 断线自动重连
- 📝 **详细日志** - 完整的交易记录和统计

### 🚀 高级功能（v2.0 增强版）
- ✅ **余额检查** - 下单前自动检查账户余额，支持并发安全
- ✅ **MIN_NOTIONAL 验证** - 所有订单类型（包括MARKET）都验证最小金额
- ✅ **精度处理** - 自动处理价格和数量精度（LOT_SIZE, PRICE_FILTER）
- ✅ **杠杆管理** - 启动时自动配置杠杆和保证金类型
- ✅ **持仓模式** - 支持单向持仓和双向持仓（对冲模式）
- ✅ **保证金模式** - 支持全仓和逐仓模式
- ✅ **订单去重** - 基于时间戳的智能去重，自动清理过期记录
- ✅ **部分成交** - 正确处理部分成交情况
- ✅ **时间同步** - 强制时间同步，失败后自动重试
- ✅ **并发安全** - 多账户并发下单时的余额锁保护

## 📋 系统要求

- Python 3.7+
- 币安合约账户（主账户 + 跟随账户）
- API Key 和 Secret（需要合约交易权限，不要授予提现权限）

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
# 测试网地址（强烈推荐先用测试网）
base_url: "https://testnet.binancefuture.com"

# 主账户配置
master:
  api_key: "你的主账户API_KEY"
  api_secret: "你的主账户API_SECRET"

# 跟随账户配置
followers:
  - name: "follower_1"
    api_key: "跟随账户1的API_KEY"
    api_secret: "跟随账户1的API_SECRET"
    scale: 1.0  # 跟单比例
    enabled: true

# 合约特有设置
trading:
  leverage: 10  # 杠杆倍数
  margin_type: "CROSSED"  # 全仓模式
  position_mode: "one_way"  # 单向持仓
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
binance_copy_trading/
├── main.py                            # 主程序入口
├── config.example.yaml                # 配置模板
├── requirements.txt                   # Python 依赖
├── README.md                          # 项目文档
├── CHANGELOG.md                       # 更新日志
└── src/
    ├── binance_futures_client.py      # Futures API 客户端
    ├── futures_copy_trade_engine.py   # 跟单引擎核心
    ├── config_loader.py               # 配置加载器
    └── logger.py                      # 日志系统
```

## ⚙️ 配置说明

### 基础配置

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `base_url` | 合约 API 地址 | 测试网: `https://testnet.binancefuture.com`<br>生产: `https://fapi.binance.com` |

### 合约特有配置

| 配置项 | 说明 | 默认值 | 范围 |
|--------|------|--------|------|
| `leverage` | 杠杆倍数 | 10 | 1-125 |
| `margin_type` | 保证金模式 | CROSSED | ISOLATED / CROSSED |
| `position_mode` | 持仓模式 | one_way | one_way / hedge |
| `auto_set_leverage` | 自动设置杠杆 | true | true / false |

#### 杠杆倍数说明

- **低杠杆（1-5x）**: 风险较低，适合新手
- **中杠杆（5-20x）**: 平衡风险和收益
- **高杠杆（20-125x）**: 风险极高，可能快速爆仓

#### 保证金模式

- **CROSSED（全仓）**: 所有持仓共享账户余额，风险分散但可能全部亏损
- **ISOLATED（逐仓）**: 每个持仓独立保证金，风险隔离但需要更多资金

#### 持仓模式

- **one_way（单向）**: 每个交易对只能持有一个方向的仓位
- **hedge（对冲）**: 可以同时持有多空双向仓位

### 交易设置

```yaml
trading:
  follower_order_type: "MARKET"  # 跟单订单类型
  min_order_quantity: 0.001      # 最小订单数量
  max_order_quantity: 100.0      # 最大订单数量
  
  # 符号特定杠杆（覆盖默认杠杆）
  symbol_leverage:
    BTCUSDT: 20
    ETHUSDT: 15
```

### 风险管理

```yaml
risk_management:
  enabled: true
  max_daily_trades: 100                    # 每日最大交易次数
  max_daily_loss_percentage: 5.0           # 每日最大亏损百分比
  max_position_size_percentage: 20.0       # 单个持仓最大占比
  min_balance_required: 10.0               # 最小余额要求（USDT）
  emergency_stop_percentage: 50.0          # 紧急停止阈值
```

## 🔧 工作原理

### 1. 初始化阶段

1. 加载配置文件
2. 连接主账户和跟随账户
3. 设置持仓模式（单向/对冲）
4. 为每个交易对设置杠杆和保证金模式

### 2. 监听阶段

1. 通过 WebSocket 连接到主账户的 User Data Stream
2. 实时接收 `ORDER_TRADE_UPDATE` 事件
3. 解析订单成交信息

### 3. 跟单阶段

对于每笔主账户成交：

1. **去重检查** - 使用 order_id + trade_id 防止重复
2. **符号过滤** - 检查是否在允许列表中
3. **计算数量** - 根据 scale 参数计算跟单数量
4. **余额检查** - 检查跟随账户余额是否充足
5. **精度调整** - 根据 LOT_SIZE 和 PRICE_FILTER 调整精度
6. **MIN_NOTIONAL 检查** - 确保订单金额满足最小要求
7. **下单** - 向跟随账户发送订单
8. **记录日志** - 记录成功/失败信息

### 4. 错误处理

- 余额不足：记录日志，跳过该订单
- MIN_NOTIONAL 不满足：记录日志，跳过该订单
- 网络错误：自动重试（最多 3 次）
- WebSocket 断线：自动重连

## 📊 日志示例

```
2024-11-02 11:00:00 - root - INFO - ✓ Connected to Futures user data stream
2024-11-02 11:00:15 - root - INFO - Setting leverage for BTCUSDT: 20x
2024-11-02 11:00:16 - root - INFO - Follower 'follower_1': Leverage set to 20x
2024-11-02 11:01:20 - root - INFO - 📊 Master FILLED: BUY 0.001 BTCUSDT @ 35000.0 [BOTH]
2024-11-02 11:01:21 - root - INFO - ✓ Follower 'follower_1': BUY 0.001/0.001 BTCUSDT - orderId=12345, status=FILLED, positionSide=BOTH
```

## 🐛 常见问题

### 1. 余额不足

**问题**: `Insufficient balance for 0.01 BTCUSDT`

**解决**:
- 检查跟随账户 USDT 余额
- 降低 `scale` 参数
- 增加账户余额
- 降低杠杆倍数

### 2. MIN_NOTIONAL 错误

**问题**: `Order value too small. MIN_NOTIONAL: 5.0`

**解决**:
- 增加 `min_order_quantity`
- 提高 `scale` 参数
- 选择价格更高的交易对

### 3. 杠杆设置失败

**问题**: `Failed to set leverage - Position exists`

**解决**:
- 先平掉该交易对的所有持仓
- 然后再设置杠杆
- 或者手动在网页端设置杠杆

### 4. 持仓模式冲突

**问题**: `No need to change position side`

**解决**:
- 这不是错误，表示持仓模式已经是目标模式
- 可以忽略此消息

## 💡 最佳实践

### 1. 测试流程

```bash
# 步骤 1: 在测试网测试
base_url: "https://testnet.binancefuture.com"
leverage: 5  # 低杠杆测试

# 步骤 2: 验证功能
- 测试开多仓
- 测试开空仓
- 测试平仓
- 测试部分成交
- 测试余额不足情况

# 步骤 3: 压力测试
- 快速连续下单
- WebSocket 断线重连
- 网络延迟情况

# 步骤 4: 切换到生产环境
base_url: "https://fapi.binance.com"
leverage: 10  # 根据风险承受能力调整
```

### 2. 风险控制建议

```yaml
# 保守配置
leverage: 5
margin_type: "ISOLATED"
max_position_size_percentage: 10.0
max_daily_loss_percentage: 2.0

# 激进配置（不推荐新手）
leverage: 20
margin_type: "CROSSED"
max_position_size_percentage: 30.0
max_daily_loss_percentage: 5.0
```

### 3. 杠杆选择建议

| 经验水平 | 推荐杠杆 | 说明 |
|---------|---------|------|
| 新手 | 1-5x | 学习阶段，控制风险 |
| 中级 | 5-10x | 有一定经验，平衡收益 |
| 高级 | 10-20x | 经验丰富，严格风控 |
| 专业 | 20x+ | 专业交易员，极度谨慎 |

### 4. 资金管理

- **初始资金**: 建议至少 100 USDT
- **单笔风险**: 不超过总资金的 2%
- **总持仓**: 不超过总资金的 50%
- **止损**: 每笔交易设置止损点

## 🔐 安全建议

1. **API Key 安全**
   - ✅ 不要授予提现权限
   - ✅ 设置 IP 白名单
   - ✅ 定期更换 API Key
   - ✅ 不要将 config.yaml 提交到 Git

2. **风险控制**
   - ✅ 从低杠杆开始（1-5x）
   - ✅ 设置最大持仓限制
   - ✅ 设置每日亏损限制
   - ✅ 使用逐仓模式隔离风险

3. **监控和告警**
   - ✅ 定期检查日志
   - ✅ 监控账户余额
   - ✅ 设置余额告警
   - ✅ 异常情况及时停止

## 📈 性能优化

### 1. 降低延迟

- 使用距离你最近的服务器
- 使用有线网络
- 关闭不必要的后台程序

### 2. 提高稳定性

```bash
# 使用 screen 后台运行
screen -S futures_copy_trade
python main_futures.py
# 按 Ctrl+A 然后按 D 退出

# 重新连接
screen -r futures_copy_trade
```

## ⚖️ 免责声明

**重要提示**:

1. 本软件仅供学习和研究使用
2. 合约交易风险极高，可能导致全部本金损失
3. 杠杆交易会放大收益和亏损
4. 使用本软件进行交易的所有风险由使用者自行承担
5. 作者不对使用本软件造成的任何直接或间接损失负责
6. 请确保您完全理解合约交易的风险
7. 建议从测试网和小资金开始

**风险警告**:

- 合约交易可能导致超过本金的损失
- 市场波动可能导致快速爆仓
- 高杠杆交易风险极高
- 请勿使用无法承受损失的资金

---

**⚠️ 再次提醒：请务必先在测试网充分测试，从低杠杆和小资金开始！**

## 📞 支持

如有问题或建议，请提交 Issue。

---

**祝交易顺利，但请务必注意风险！** 🚀
