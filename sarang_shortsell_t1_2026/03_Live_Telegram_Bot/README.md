# Combined Live Execution Bot

This folder contains the live production daemon that runs both the 09:20 and 09:42 models on the live market.

## How to Run
- Host this script on your Linux server.
- Run `python3 live_master_execution.py`.
- The bot will use the `schedule` library to automatically trigger at 09:19 and 09:40, download the live market index features, and send the predictions to your Telegram Channel.
