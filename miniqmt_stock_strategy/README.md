# miniQMT Stock Strategy Skeleton

这是一个用于股票策略的可运行框架，结构与 `miniqmt_etf_strategy` 类似。
当前已接入：

- 尾盘窗口调仓（14:50-14:56）
- 调仓周期控制（默认 19 个交易日）
- ATR 波动风控 + 组合回撤锁仓框架
- 实盘下单流程（先卖后买）
- **股票池优先** `xtdata.get_stock_list_in_sector`；**因子优先** `xtdata.get_market_data`（估值字段）；接口无数据且 `config.USE_DATA_FILE_FALLBACK=True` 时再读本地 `data/stock_pool.txt` / `factors_YYYYMMDD.csv`

## 目录结构

- `main.py`：主循环与流程编排
- `strategy.py`：策略占位（后续填入你的股票策略）
- `broker_xtquant.py`：miniQMT/xtquant 接口封装
- `state_store.py`：状态读写（按日文件）
- `logger.py`：日志分流（console/strategy/errors）
- `config.py`：参数与路径
- `bat_start/start_strategy.bat`：启动入口
- `bat_ops/force_rebalance.bat`：强制调仓状态入口
- `logs/`：运行日志
- `state/`：状态文件
- `data/stock_pool.txt`（可选，接口失败时的备用股票池）
- `data/factors_YYYYMMDD.csv`（可选，接口失败时的备用因子）

## 使用

1. 修改 `config.py` 里的 `XTQUANT_PATH`、`QMT_PATH`、`ACCOUNT_ID`
2. 在终端侧确保已下载板块/指数成分等基础数据（否则 `get_stock_list_in_sector` 可能为空）
3. 双击 `bat_start/start_strategy.bat` 启动
4. 若接口无数据，可临时放置备用文件（见下）；或设置 `USE_DATA_FILE_FALLBACK = False` 强制只看错误日志、不用文件

## 备用因子文件格式（仅当接口拉取失败且开启回退时）

至少包含以下列：

- `code`（如 `000001.SZ`）
- `pe`
- `pb`
- `roe`
- `market_cap`

策略会自动计算：

- `ep = 1/pe`
- `bp = 1/pb`
- `size = 1/log(market_cap)`
- `lowvol`（若文件未提供，则用近 61 日行情补算）

