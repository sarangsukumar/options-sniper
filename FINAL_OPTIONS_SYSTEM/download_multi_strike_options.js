const BreezeConnect = require('breezeconnect').BreezeConnect;
const fs = require('fs');
const path = require('path');
const mysql = require('mysql');
const util = require('util');
const csv = require('csv-parser');

const parentDir = path.dirname(__dirname);
const YEAR = process.argv[2] || '2026';
const TARGETS_CSV = `options_download_targets_${YEAR}_verified.csv`;

// ICICI Breeze Credentials (Amrit Account)
const appKey = "77059JQ7633PoSc1mk465580B6wp1x04";
const appSecret = "6P9^377d3*412585q(527i3ZgJ437040";
const sessionFile = path.join(parentDir, 'auth', 'icicisession.txt');

const breeze = new BreezeConnect({ appKey: appKey });

const dbConfig = {
    host: 'localhost',
    user: 'root',
    password: 'root',
    database: 'markets'
};

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function generateMultiStrikes(buyPrice) {
    let strikes = new Set();
    let step = 5;
    if (buyPrice > 2500) step = 50;
    else if (buyPrice > 1000) step = 20;
    else if (buyPrice > 500) step = 10;
    else if (buyPrice > 100) step = 5;
    else if (buyPrice > 50) step = 2.5;
    else step = 1;

    let rounded = Math.round(buyPrice / step) * step;
    
    // Generate strikes from +2% to -6% of buyPrice
    for (let i = -6; i <= 2; i++) {
        let s = rounded + (step * i);
        if (s > 0) strikes.add(s);
    }
    return Array.from(strikes).sort((a, b) => b - a); // Higher (ATM/ITM) to Lower (OTM)
}

async function downloadAndInsert(db, stock, iciciSymbol, date, expiryDate, right, strike) {
    let fromDateIso = date + "T03:45:00.000Z"; // 9:15 AM IST = 3:45 AM UTC
    let toDateIso = date + "T10:00:00.000Z";   // 3:30 PM IST = 10:00 AM UTC
    
    try {
        let res = await breeze.getHistoricalDatav2({
            interval: "1minute",
            fromDate: fromDateIso,
            toDate: toDateIso,
            stockCode: iciciSymbol,
            exchangeCode: "NFO",
            productType: "options",
            expiryDate: expiryDate,
            right: right,
            strikePrice: strike.toString()
        });

        if (res.Success && res.Success.length > 0) {
            let inserted = 0;
            for (let row of res.Success) {
                let query = `INSERT IGNORE INTO scrapdata_options (stock_code, datetime, expiry_date, \`right\`, strike_price, open, high, low, close, volume, open_interest) VALUES (?, ?, STR_TO_DATE(?, '%d-%b-%Y'), ?, ?, ?, ?, ?, ?, ?, ?)`;
                let values = [stock, row.datetime, row.expiry_date, right, strike, row.open, row.high, row.low, row.close, row.volume, row.open_interest];
                let result = await db.query(query, values);
                if (result && result.affectedRows > 0) inserted++;
            }
            return inserted;
        }
    } catch (e) {
        // Quiet failure for non-existent strikes
    }
    return 0;
}

async function run() {
    console.log("==================================================");
    console.log(`  ICICI MULTI-STRIKE OPTIONS DOWNLOADER [YEAR: ${YEAR}]`);
    console.log("==================================================");

    let session_key = fs.readFileSync(sessionFile, 'utf8').trim();
    try {
        await breeze.generateSession(appSecret, session_key);
        console.log("[Auth] ICICI Session authenticated successfully.");
    } catch (e) {
        console.error("[Auth] Session failed.", e.message);
        return;
    }

    const rawDb = mysql.createConnection(dbConfig);
    rawDb.connect();
    const db = {
        query: util.promisify(rawDb.query).bind(rawDb),
        end: util.promisify(rawDb.end).bind(rawDb)
    };
    console.log("[DB] Connected to MySQL successfully.\n");

    let symbolMap = {};
    const MASTER_CSV = path.join(parentDir, 'config', 'ICICImaster.csv');
    if (fs.existsSync(MASTER_CSV)) {
        let masterRows = fs.readFileSync(MASTER_CSV, 'utf8').split('\n');
        for (let row of masterRows) {
            let parts = row.split(',');
            if (parts.length >= 7) {
                let trackingStock = parts[6].trim();
                let iciciSym = parts[2].trim();
                if (trackingStock && iciciSym) symbolMap[trackingStock] = iciciSym;
            }
        }
    }

    let targets = [];
    fs.createReadStream(TARGETS_CSV)
        .pipe(csv())
        .on('data', (row) => targets.push(row))
        .on('end', async () => {
            console.log(`[Target] Loaded ${targets.length} targets for ${YEAR}`);
            
            for (let t of targets) {
                let stock = t.stock;
                let buyDate = t.buy_date;
                let sellDate = t.sell_date;
                let buyPrice = parseFloat(t.buy_price);
                let expiryDate = t.expiry_date;
                
                let iciciSymbol = symbolMap[stock] || stock;
                let strikes = generateMultiStrikes(buyPrice);
                
                console.log(`\n[Process] ${stock} (ICICI: ${iciciSymbol}) | Buy: ${buyDate} | Sell: ${sellDate} | Price: ${buyPrice}`);
                console.log(`    [Strikes] Testing ${strikes.length} strikes: ${strikes.join(', ')}`);
                
                for (let s of strikes) {
                    let buyRows = await downloadAndInsert(db, stock, iciciSymbol, buyDate, expiryDate, "Put", s);
                    await sleep(350);
                    let sellRows = await downloadAndInsert(db, stock, iciciSymbol, sellDate, expiryDate, "Put", s);
                    await sleep(350);
                    
                    if (buyRows > 0 || sellRows > 0) {
                        console.log(`      -> Strike ${s} Put: Inserted Buy Date=${buyRows} rows | Sell Date=${sellRows} rows`);
                    }
                }
            }
            
            console.log(`\n==================================================`);
            console.log(`  COMPLETED MULTI-STRIKE DOWNLOAD FOR ${YEAR}!`);
            console.log(`==================================================`);
            await db.end();
            process.exit(0);
        });
}

run();
