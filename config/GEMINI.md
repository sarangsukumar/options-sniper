# 📈 Quantitative Backtest & Output Generation Rules

Whenever executing a user command in this directory that contains instructions like "show results", "send results", "generate graph", "send graph", or any phrases requesting reports or visualizations:

1. **Automatic PDF Comparison Report Generation**:
   At the very end of your execution (after running any of the strategy simulation scripts), you MUST automatically run the PDF generator script to compile a complete, comprehensive report:
   ```bash
   python3 scratch/generate_pdf.py
   ```
   This ensures that the latest simulation results from `trades_static_baseline.csv`, `trades_dynamic_threshold.csv`, and `trades_ticker_suspension.csv` are compiled into the final 5-page PDF `output/yearly_comparison_report.pdf`.

2. **Automatic Bar Charts / PnL Charts PDF Generation**:
   If the user request specifically asks for bar charts, PnL charts, monthly graphs, or detailed PnL visualizations, you MUST also run the corresponding visualization scripts:
   ```bash
   python3 scratch/generate_monthly_bar_charts_pdf.py
   python3 scratch/generate_full_monthly_pnl_charts_pdf.py
   ```
   This ensures all requested visualizations are properly regenerated and updated.

3. **Verify Execution**:
   Always verify that these scripts complete successfully. Once compiled, state clearly in your final markdown response that the PDF reports and graphs have been successfully regenerated and are ready for download. This ensures the Telegram bot's background file monitor detects the new modification timestamps and uploads them to the user's chat.
