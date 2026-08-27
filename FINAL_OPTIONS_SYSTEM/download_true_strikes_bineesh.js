const BreezeConnect = require('breezeconnect').BreezeConnect;
const fs = require('fs');
const path = require('path');
const mysql = require('mysql');
const util = require('util');
const csv = require('csv-parser');

const parentDir = path.dirname(__dirname);
const TARGETS_CSV = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/FINAL_OPTIONS_SYSTEM/missing_data_download_tasks.csv';
const appKey = "S945YmT9K3Z4425450K+C205BMZ9$085";
const appSecret = "6P9^377d3*412585q(527i3ZgJ437040";
const sessionFile = "/home/ubuntu/KotakCodes1/Bineesh_ICICI/icicisession.txt";

const breeze = new BreezeConnect({ appKey: appKey });
const dbConfig = { host: 'localhost', user: 'root', password: 'root', database: 'markets' };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function downloadAndInsert(db, stock, iciciSymbol, date, expiryDate, strike) {
    let fromDateIso = date + "T09:15:00.000Z";
    let toDateIso = date + "T15:30:00.000Z";
    try {
        let res = await breeze.getHistoricalDatav2({
            interval: "1minute", fromDate: fromDateIso, toDate: toDateIso,
            stockCode: iciciSymbol, exchangeCode: "NFO", productType: "options",
            expiryDate: expiryDate, right: "Put", strikePrice: strike.toString()
        });
        if (res.Success && res.Success.length > 0) {
            let promises = res.Success.map(row => {
                let query = `INSERT IGNORE INTO scrapdata_options (stock_code, datetime, expiry_date, \`right\`, strike_price, open, high, low, close, volume, open_interest, month_type) VALUES (?, ?, STR_TO_DATE(?, '%d-%b-%Y'), ?, ?, ?, ?, ?, ?, ?, ?, 'F1')`;
                let values = [stock, row.datetime, row.expiry_date, "Put", strike, row.open, row.high, row.low, row.close, row.volume, row.open_interest];
                return db.query(query, values);
            });
            await Promise.all(promises);
            return res.Success.length;
        }
    } catch (e) {
        // Ignore errors, usually means 0 volume
    }
    return 0;
}

async function run() {
    let session_key = fs.readFileSync(sessionFile, 'utf8').trim();
    try {
        await breeze.generateSession(appSecret, session_key);
    } catch (e) {
        console.error("Session failed. Please verify the session key in " + sessionFile);
        process.exit(1);
    }
    const rawDb = mysql.createConnection(dbConfig);
    rawDb.connect();
    const db = { query: util.promisify(rawDb.query).bind(rawDb), end: util.promisify(rawDb.end).bind(rawDb) };

    let symbolMap = {
        'HINDCOPPER': 'HINCOP',
        'M&MFIN': 'MAHFIN',
        'BAJAJFINSV': 'BAFINS',
        'BAJFINANCE': 'BAJFI',
        'CHOLAFIN': 'CHOINV',
        'HINDALCO': 'HINDAL',
        'HINDUNILVR': 'HINLEV',
        'LICHSGFIN': 'LICHF',
        'MUTHOOTFIN': 'MUTFIN',
        'SHRIRAMFIN': 'SHRTRA',
        'TECHM': 'TECMAH',
        'KOTAKBANK': 'KOTMAH',
        'PERSISTENT': 'PERSYS',
        'PAGEIND': 'PAGIND',
        'PATANJALI': 'RUCSOY',
        'PAYTM': 'ONE97',
        'POLICYBZR': 'PBFINT',
        'PFC': 'POWFIN',
        'PGEL': 'PGELEC',
        'M_M': 'MAHMAH',
        'M&M': 'MAHMAH',
        'ABBOTINDIA': 'ABBIND',
        'AARTIIND': 'AARIND',
        'BALRAMCHIN': 'BALCHI',
        'COROMANDEL': 'CORINT',
        'DEEPAKNTR': 'DEENIT',
        'ESCORTS': 'ESCORT',
        'INDIAMART': 'INDMAR',
        'IPCALAB': 'IPCLAB',
        'JKCEMENT': 'JKCEM',
        'NAVINFLUOR': 'NAVFLU',
        'PVRINOX': 'PVR'
    };
    const MASTER_CSV = path.join(parentDir, 'config', 'ICICImaster.csv');
    if (fs.existsSync(MASTER_CSV)) {
        let masterRows = fs.readFileSync(MASTER_CSV, 'utf8').split('\n');
        for (let row of masterRows) {
            let parts = row.split(',');
            if (parts.length >= 7) {
                let ts = parts[6].trim(); let is = parts[2].trim();
                if (ts && is) symbolMap[ts] = is;
            }
        }
    }

    let targets = [];
    fs.createReadStream(TARGETS_CSV).pipe(csv()).on('data', (row) => targets.push(row)).on('end', async () => {
        console.log(`Loaded ${targets.length} precise target rows to download.`);
        let active = [];
        let count = 0;
        for (let t of targets) {
            let stock = t.Stock;
            let iciciSymbol = symbolMap[stock] || stock;
            let date = t.Date;
            let strike = parseFloat(t.Strike);
            let expiryDate = t.icici_expiry;
            
            if (!expiryDate || isNaN(strike)) continue;

            // Optional: check if exists to save API calls
            let existRes = await db.query("SELECT COUNT(*) as c FROM scrapdata_options WHERE stock_code=? AND DATE(datetime)=? AND strike_price=? AND `right`='Put' AND month_type='F1'", [stock, date, strike]);
            if (existRes[0].c > 5) {
                // Already downloaded completely
                continue;
            }

            console.log(`[DOWNLOAD-BINEESH] ${stock} | Date:${date} | Strike:${strike}`);
            
            let p = downloadAndInsert(db, stock, iciciSymbol, date, expiryDate, strike).finally(() => {
                let i = active.indexOf(p); if (i !== -1) active.splice(i, 1);
            });
            active.push(p);
            
            count++;
            
            while (active.length >= 4) {
                await sleep(100);
            }
            await sleep(150); // ICICI Rate limit protection
        }
        
        while (active.length > 0) {
            await sleep(100);
        }
        await db.end();
        console.log(`[DONE] Finished processing ${count} new missing strikes with Bineesh credentials.`);
        
        // Notify Telegram
        const https = require('https');
        const tgData = JSON.stringify({
            chat_id: process.env.TELEGRAM_CHAT_ID,
            text: `✅ **Bineesh Data Download Complete!**\n\nSuccessfully requested exactly ${count} true missing strikes from ICICI and inserted the valid ones directly into your \`markets\` database!`
        });
        const req = https.request({
            hostname: 'api.telegram.org', port: 443,
            path: `/bot${process.env.TELEGRAM_FILE_BOT_TOKEN}/sendMessage`,
            method: 'POST', headers: {'Content-Type': 'application/json', 'Content-Length': tgData.length}
        });
        req.write(tgData); req.end();
        
        process.exit(0);
    });
}
run();
