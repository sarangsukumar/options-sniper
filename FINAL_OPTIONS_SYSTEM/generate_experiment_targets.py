import csv
import os
import random
from datetime import datetime

MASTER_PNL = '../data/markets_pnl0325.csv'
TRACKER_FILE = '../output/trades_dynamic_threshold.csv'

EXPIRY_DATES = [
    # 2024
    "25 Jan 2024", "29 Feb 2024", "28 Mar 2024", "25 Apr 2024", "30 May 2024",
    "27 Jun 2024", "25 Jul 2024", "29 Aug 2024", "26 Sep 2024", "31 Oct 2024",
    "28 Nov 2024", "26 Dec 2024",
    # 2025
    "30 Jan 2025", "27 Feb 2025", "27 Mar 2025", "24 Apr 2025", "29 May 2025",
    "26 Jun 2025", "31 Jul 2025", "28 Aug 2025", "30 Sep 2025", "28 Oct 2025",
    "25 Nov 2025", "30 Dec 2025",
    # 2026
    "27 Jan 2026", "24 Feb 2026", "31 Mar 2026", "28 Apr 2026", "26 May 2026",
    "30 Jun 2026", "28 Jul 2026", "25 Aug 2026", "29 Sep 2026", "27 Oct 2026",
    "24 Nov 2026", "29 Dec 2026"
]

def get_expiry(buy_date_str):
    buy_dt = datetime.strptime(buy_date_str, "%Y-%m-%d")
    for exp_str in EXPIRY_DATES:
        exp_dt = datetime.strptime(exp_str, "%d %b %Y")
        if buy_dt <= exp_dt:
            return exp_dt.strftime("%Y-%m-%dT07:00:00.000Z")
    return None

def main():
    years = ['2024', '2025', '2026']
    
    unique_dates = set()
    price_lookup = {}
    all_stocks = set()
    with open(MASTER_PNL, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = row['simulationdate']
            stock = row['stockname']
            all_stocks.add(stock)
            unique_dates.add(dt)
            price_lookup[f"{dt}_{stock}"] = row['buy_price']

    sorted_dates = sorted(list(unique_dates))
    date_mapping = {sorted_dates[i]: sorted_dates[i+1] for i in range(len(sorted_dates)-1)}
    all_stocks_list = list(all_stocks)

    trades_by_date = {}
    with open(TRACKER_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = row['date']
            if any(dt.startswith(y) for y in years):
                if dt not in trades_by_date:
                    trades_by_date[dt] = []
                trades_by_date[dt].append(row)

    for year in years:
        output_file = f'experiment_targets_{year}.csv'
        download_targets = []
        year_dates = sorted([d for d in trades_by_date if d.startswith(year)])
        
        for dt in year_dates:
            group = trades_by_date[dt]
            try:
                group = sorted(group, key=lambda x: int(x['rank']))
            except: pass

            target_map = {}
            if len(group) > 0: target_map['R1'] = group[0]['stock']
            if len(group) > 1: target_map['R2'] = group[1]['stock']
            if len(group) > 2: target_map['R3'] = group[2]['stock']
            if len(group) > 3: target_map['R4'] = group[3]['stock']

            # Pick 2 random stocks that are not in the R1-R4
            picked = set(target_map.values())
            randoms = random.sample([s for s in all_stocks_list if s not in picked], 2)
            target_map['RAND1'] = randoms[0]
            target_map['RAND2'] = randoms[1]

            sell_date = date_mapping.get(dt)
            if not sell_date: continue
            expiry = get_expiry(dt)
            gap_days = (datetime.strptime(sell_date, "%Y-%m-%d") - datetime.strptime(dt, "%Y-%m-%d")).days

            for rank_type, stock in target_map.items():
                buy_price = price_lookup.get(f"{dt}_{stock}", "UNKNOWN")
                download_targets.append({
                    'rank_type': rank_type,
                    'stock': stock,
                    'buy_date': dt,
                    'sell_date': sell_date,
                    'gap_days': gap_days,
                    'buy_price': buy_price,
                    'expiry_date': expiry
                })

        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['rank_type','stock','buy_date','sell_date','gap_days','buy_price','expiry_date'])
            writer.writeheader()
            for t in download_targets: writer.writerow(t)

        print(f"[{year}] Generated {len(download_targets)} experimental targets -> {output_file}")

if __name__ == "__main__":
    main()
