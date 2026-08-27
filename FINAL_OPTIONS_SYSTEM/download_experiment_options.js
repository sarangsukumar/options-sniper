const BreezeConnect = require('breezeconnect').BreezeConnect;
const fs = require('fs');
const path = require('path');
const mysql = require('mysql');
const util = require('util');
const csv = require('csv-parser');

const parentDir = path.dirname(__dirname);
const YEAR = process.argv[2] || '2026';
const TARGETS_CSV = `experiment_targets_${YEAR}.csv`;

const appKey = "77059JQ7633PoSc1mk465580B6wp1x04";
const appSecret = "6P9^377d3*412585q(527i3ZgJ437040";
const sessionFile = path.join(parentDir, 'auth', 'icicisession.txt');

const breeze = new BreezeConnect({ appKey: appKey });
const dbConfig = { host: 'localhost', user: 'root', password: 'root', database: 'markets' };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function generateMultiStrikes(buyPrice) {
    let step = 5;
    if (buyPrice > 2500) step = 50; else if (buyPrice > 1000) step = 20; else if (buyPrice > 500) step = 10; else if (buyPrice > 100) step = 5; else if (buyPrice > 50) step = 2.5; else step = 1;
    let rounded = Math.round(buyPrice / step) * step;
    let strikes = new Set();
    for (let i = -6; i <= 2; i++) { let s = rounded + (step * i); if (s > 0) strikes.add(s); }
    return Array.from(strikes).sort((a, b) => b - a);
}

async function checkExists(db, stock, date) {
    let res = await db.query("SELECT COUNT(*) as c FROM scrapdata_options WHERE stock_code=? AND DATE(datetime)=? AND TIME(datetime) >= '15:00:00'", [stock, date]);
    return res[0].c > 5;
}

async function downloadAndInsert(db, stock, iciciSymbol, date, expiryDate, right, strike) {
    let fromDateIso = date + "T09:15:00.000Z";
    let toDateIso = date + "T15:30:00.000Z";
    try {
        let res = await breeze.getHistoricalDatav2({
            interval: "1minute", fromDate: fromDateIso, toDate: toDateIso,
            stockCode: iciciSymbol, exchangeCode: "NFO", productType: "options",
            expiryDate: expiryDate, right: right, strikePrice: strike.toString()
        });
        if (res.Success && res.Success.length > 0) {
            let promises = res.Success.map(row => {
                let query = `INSERT IGNORE INTO scrapdata_options (stock_code, datetime, expiry_date, \`right\`, strike_price, open, high, low, close, volume, open_interest) VALUES (?, ?, STR_TO_DATE(?, '%d-%b-%Y'), ?, ?, ?, ?, ?, ?, ?, ?)`;
                let values = [stock, row.datetime, row.expiry_date, right, strike, row.open, row.high, row.low, row.close, row.volume, row.open_interest];
                return db.query(query, values);
            });
            await Promise.all(promises);
            return res.Success.length;
        }
    } catch (e) {}
    return 0;
}

async function run() {
    let session_key = fs.readFileSync(sessionFile, 'utf8').trim();
    await breeze.generateSession(appSecret, session_key);
    
    const rawDb = mysql.createConnection(dbConfig);
    rawDb.connect();
    const db = { query: util.promisify(rawDb.query).bind(rawDb), end: util.promisify(rawDb.end).bind(rawDb) };

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
            console.log(`Loaded ${targets.length} targets for ${YEAR}`);
            
            for (let t of targets) {
                let stock = t.stock;
                if (stock === 'UNKNOWN' || !stock) continue;
                if (t.buy_price === 'UNKNOWN') continue;
                
                let exists1 = await checkExists(db, stock, t.buy_date);
                let exists2 = await checkExists(db, stock, t.sell_date);
                if (exists1 && exists2) {
                    console.log(`[SKIP] ${stock} on ${t.buy_date} (Already Exists)`);
                    continue;
                }

                let iciciSymbol = symbolMap[stock] || stock;
                let strikes = generateMultiStrikes(parseFloat(t.buy_price));
                console.log(`[DL] ${stock} | ${t.buy_date} | ${strikes.length} strikes...`);
                
                let jobs = [];
                for (let s of strikes) {
                    if (s === undefined) continue;
                    if (!exists1) jobs.push({ date: t.buy_date, strike: s });
                    if (!exists2) jobs.push({ date: t.sell_date, strike: s });
                }
                
                let activePromises = [];
                let jobIdx = 0;
                while (jobIdx < jobs.length || activePromises.length > 0) {
                    while (activePromises.length < 8 && jobIdx < jobs.length) {
                        let job = jobs[jobIdx++];
                        let p = downloadAndInsert(db, stock, iciciSymbol, job.date, t.expiry_date, "Put", job.strike).finally(() => {
                            let pIdx = activePromises.indexOf(p);
                            if (pIdx !== -1) activePromises.splice(pIdx, 1);
                        });
                        activePromises.push(p);
                        await sleep(125); // Launch delay to keep RPS under 8
                    }
                    if (activePromises.length > 0) {
                        await Promise.race(activePromises);
                    }
                }
            }
            await db.end();
            console.log(`[DONE] Year ${YEAR}`);
            process.exit(0);
        });
}
run();
