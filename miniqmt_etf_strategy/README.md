# miniQMT ETF rotation strategy

This directory contains a local miniQMT version of the ETF rotation strategy.

## Files

- `config.py`: local paths, account, ETF pool, risk and schedule parameters
- `broker_xtquant.py`: miniQMT connection, account queries, order submit/cancel/sync
- `strategy.py`: momentum target calculation and volatility position scaling
- `state_store.py`: JSON state loading/saving
- `logger.py`: daily strategy/error logs
- `main.py`: runtime loop, risk checks, rebalance window, pending orders
- `run_strategy.bat`: Windows watchdog launcher

## Before running

Edit `config.py`:

```python
XTQUANT_PATH = r"D:\迅投极速交易终端 睿智融科版\bin.x64\Lib\site-packages"
QMT_PATH = r"D:\迅投极速交易终端 睿智融科版\userdata_mini"
ACCOUNT_ID = "2064890"
```

Keep the QMT client open and the target trading account logged in.

## Run once

```bat
D:\qmt\code\qmt_etf_strategy\.venv\Scripts\python.exe main.py
```

## Watchdog run

Double-click `run_strategy.bat` or run it from CMD.

Logs are written to `logs/`, state is written to `state/`.
