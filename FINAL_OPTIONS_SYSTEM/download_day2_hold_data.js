const BreezeConnect = require('breezeconnect').BreezeConnect;
const fs = require('fs');
const path = require('path');
const mysql = require('mysql');
const util = require('util');
const csv = require('csv-parser');

const parentDir = path.dirname(__dirname);
const TARGETS_CSV = path.join(__dirname, 'day2_hold_download_tasks.csv');

const appKey = "77059JQ7633PoSc1mk465580B6wp1x04";
const appSecret = "6P9^377d3*412585q(527i3ZgJ437040";
const sessionFile = path.join(parentDir, 'auth', 'icicisession.txt');

const breeze = new BreezeConnect({ appKey: appKey });
const dbConfig = { host: 'localhost', user: 'root', password: 'root', database: 'markets' };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function checkExists(db, stock, date, strike) {
    let res = await db.query(
        "SELECT COUNT(*) as c FROM scrapdata_options WHERE stock_code=? AND DATE(datetime)=? AND strike_price=? AND `right`='Put'",
        [stock, date, strike]
    );
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

    let tasks = [];
    fs.createReadStream(TARGETS_CSV)
        .pipe(csv())
        .on('data', (row) => tasks.push(row))
        .on('end', async () => {
            console.log(`Loaded ${tasks.length} total tasks from day2_hold_download_tasks.csv`);
            
            let downloadQueue = [];
            for (let t of tasks) {
                let stock = t.stock;
                let date = t.date;
                let sell_strike = parseFloat(t.sell_strike);
                let buy_strike = parseFloat(t.buy_strike);
                let expiry = t.expiry_date;
                let iciciSymbol = symbolMap[stock] || stock;

                // Check sell strike
                let sellExists = await checkExists(db, stock, date, sell_strike);
                if (!sellExists) {
                    downloadQueue.push({ stock, iciciSymbol, date, expiry, strike: sell_strike });
                }

                // Check buy strike
                let buyExists = await checkExists(db, stock, date, buy_strike);
                if (!buyExists) {
                    downloadQueue.push({ stock, iciciSymbol, date, expiry, strike: buy_strike });
                }
            }

            console.log(`Found ${downloadQueue.length} missing strike-date combinations to download.`);

            let activePromises = [];
            let jobIdx = 0;
            while (jobIdx < downloadQueue.length || activePromises.length > 0) {
                while (activePromises.length < 8 && jobIdx < downloadQueue.length) {
                    let job = downloadQueue[jobIdx++];
                    let p = downloadAndInsert(db, job.stock, job.iciciSymbol, job.date, job.expiry, "Put", job.strike).finally(() => {
                        let pIdx = activePromises.indexOf(p);
                        if (pIdx !== -1) activePromises.splice(pIdx, 1);
                    });
                    activePromises.push(p);
                    if (jobIdx % 20 === 0 || jobIdx === downloadQueue.length) {
                        console.log(`Progress: ${jobIdx} / ${downloadQueue.length} jobs dispatched`);
                    }
                    await sleep(125); // Rate limit RPS <= 8
                }
                if (activePromises.length > 0) {
                    await Promise.race(activePromises);
                }
            }

            await db.end();
            console.log(`[DONE] All Day 0, Day 1, and Day 2 options data successfully downloaded and inserted!`);
            process.exit(0);
        });
}
run();
