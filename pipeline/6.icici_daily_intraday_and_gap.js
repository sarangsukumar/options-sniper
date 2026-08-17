/**
 * 6.icici_daily_intraday_and_gap.js (STREAMLINED TICK DOWNLOADER)
 * ==========================================================================
 * Afternoon Daily ICICI Cash Ticks Downloader
 * Runs every trading day at or after 3:15 PM.
 * 
 * Downloads 1-minute intraday tick series for the active date and stores
 * them in MySQL markets.scrapdata for computing live afternoon intraday features.
 * 
 * Gaps calculation and CSV updates are fully handled by update_today_gaps_morning.js
 * in the morning simulation pipeline, making this script run 3x faster!
 * ==========================================================================
 */

var BreezeConnect = require('breezeconnect').BreezeConnect;
const fs = require('fs');
const csv = require('csv-parser');
const path = require('path');
const mysql = require('mysql');

// ── CONFIGURATION ────────────────────────────────────────────────────────────
const parentDir = path.dirname(__dirname);
const MASTER_CSV = path.join(parentDir, 'config', 'masterfile.csv');
const TABLENAME = "scrapdata";

// Account Configurations
const ACCOUNT_CONFIGS = {
    Amrit: {
        name: "Amrit",
        appKey: "77059JQ7633PoSc1mk465580B6wp1x04",
        appSecret: "6P9^377d3*412585q(527i3ZgJ437040",
        sessionFile: "/home/ubuntu/KotakCodes1/ICICI/icici_session_token/icicisession_amrit.txt",
        otpScript: path.join(parentDir, 'auth', '2.OTP_Amrit.py')
    },
    Manisha: {
        name: "Manisha",
        appKey: "1f3Pi887R1652C91_76J6808z8191jq~",
        appSecret: "4d7(89!0_3~8+11%49J38+g340k99n2~",
        sessionFile: "/home/ubuntu/KotakCodes1/ICICI/icici_session_token/icicisession_manisha.txt",
        otpScript: path.join(parentDir, 'auth', '2.OTP_Manisha.py')
    }
};

let activeAccountName = "Amrit";
let activeConfig = ACCOUNT_CONFIGS[activeAccountName];

const dbConfig = {
    host:     'localhost',
    user:     'root',
    password: 'root',
    database: 'markets'
};

const connection = mysql.createConnection(dbConfig);
connection.connect((err) => {
    if (err) {
        console.error('[MySQL Error] DB Connection failed:', err.message);
        process.exit(1);
    }
});

let breeze = null;
let isBreezeInitialized = false;

// ── LIST OF STOCKS ───────────────────────────────────────────────────────────
const VALIDSTOCKNAMES = "AARTIIND,ABB,ABBOTINDIA,ABCAPITAL,ABFRL,ACC,ADANIENT,ADANIPORTS,ALKEM,AMBUJACEM,APOLLOHOSP,APOLLOTYRE,ASHOKLEY,ASIANPAINT,ASTRAL,ATUL,AUBANK,AUROPHARMA,AXISBANK,BAJAJ-AUTO,BAJAJFINSV,BAJFINANCE,BALKRISIND,BALRAMCHIN,BANDHANBNK,BANKBARODA,BANKNIFTY,BATAINDIA,BEL,BERGEPAINT,BHARATFORG,BHARTIARTL,BHEL,BIOCON,BOSCHLTD,BPCL,BRITANNIA,BSOFT,CANBK,CANFINHOME,CHAMBLFERT,CHOLAFIN,CIPLA,COALINDIA,COFORGE,COLPAL,CONCOR,COROMANDEL,CROMPTON,CUB,CUMMINSIND,DABUR,DALBHARAT,DEEPAKNTR,DELTACORP,DIVISLAB,DIXON,DLF,DRREDDY,EICHERMOT,ESCORTS,EXIDEIND,FEDERALBNK,FINNIFTY,GAIL,GLENMARK,GMRINFRA,GNFC,GODREJCP,GODREJPROP,GRANULES,GRASIM,GUJGASLTD,HAL,HAVELLS,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HEROMOTOCO,HINDALCO,HINDCOPPER,HINDPETRO,HINDUNILVR,IBULHSGFIN,ICICIBANK,ICICIGI,ICICIPRULI,IDEA,IDFC,IDFCFIRSTB,IEX,IGL,INDHOTEL,INDIACEM,INDIAMART,INDIGO,INDUSINDBK,INDUSTOWER,INFY,IOC,IPCALAB,IRCTC,ITC,JINDALSTEL,JKCEMENT,JSWSTEEL,JUBLFOOD,KOTAKBANK,L&TFH,LALPATHLAB,LAURUSLABS,LICHSGFIN,LT,LTF,LTIM,LTTS,LUPIN,M&M,M&MFIN,MANAPPURAM,MARICO,MARUTI,MCDOWELL-N,MCX,METROPOLIS,MFSL,MGL,MIDCPNIFTY,MOTHERSON,MPHASIS,MRF,MUTHOOTFIN,NATIONALUM,NAUKRI,NAVINFLUOR,NESTLEIND,NIFTY,NIFTY NEXT 50,NMDC,NTPC,OBEROIRLTY,OFSS,ONGC,PAGEIND,PEL,PERSISTENT,PETRONET,PFC,PIDILITIND,PIIND,PNB,POLYCAB,POWERGRID,PVRINOX,RAMCOCEM,RBLBANK,RECLTD,RELIANCE,SAIL,SBICARD,SBILIFE,SBIN,SHREECEM,SHRIRAMFIN,SIEMENS,SRF,SUNPHARMA,SUNTV,SYNGENE,TATACHEM,TATACOMM,TATACONSUM,TATAMOTORS,TATAPOWER,TATASTEEL,TCS,TECHM,TITAN,TORNTPHARM,TRENT,TVSMOTOR,UBL,ULTRACEMCO,UNITDSPR,UPL,VEDL,VOLTAS,WIPRO,ZEEL,ZYDUSLIFE";

// ── UTILS ────────────────────────────────────────────────────────────────────
function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

function getLocalDateString(date) {
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

// ── AUTH & SESSION MANAGEMENT ────────────────────────────────────────────────
async function initializeBreeze() {
    if (isBreezeInitialized) return;
    breeze = new BreezeConnect({ appKey: activeConfig.appKey });
    isBreezeInitialized = true;
}

function readSessionKey(filePath) {
    try {
        if (fs.existsSync(filePath)) {
            return fs.readFileSync(filePath, 'utf8').trim();
        }
    } catch (e) {
        console.error(`[Session Error] Failed to read ${filePath}:`, e);
    }
    return null;
}

function runOtpScript(scriptPath) {
    return new Promise((resolve, reject) => {
        const { exec } = require('child_process');
        exec(`python3 "${scriptPath}"`, (err, stdout, stderr) => {
            if (err) return reject(new Error(stderr || err.message));
            resolve(stdout.trim());
        });
    });
}

let isRenewingSession = false;
async function authenticateOrRenew() {
    if (isRenewingSession) {
        while (isRenewingSession) await delay(100);
        return;
    }
    isRenewingSession = true;
    try {
        await initializeBreeze();
        let sessionKey = readSessionKey(activeConfig.sessionFile);
        
        if (!sessionKey) {
            console.log(`[Auth] No session file found. Renewing OTP for ${activeAccountName}...`);
            await runOtpScript(activeConfig.otpScript);
            sessionKey = readSessionKey(activeConfig.sessionFile);
            if (!sessionKey) throw new Error(`OTP renew script failed for ${activeAccountName}`);
        }

        try {
            await breeze.generateSession(activeConfig.appSecret, sessionKey);
            console.log(`[Session] Authenticated successfully on ${activeAccountName} account.`);
        } catch (err) {
            console.warn(`[Auth Warning] Credentials failed for ${activeAccountName}: ${err.message}. Retrying...`);
            await runOtpScript(activeConfig.otpScript);
            sessionKey = readSessionKey(activeConfig.sessionFile);
            try {
                await breeze.generateSession(activeConfig.appSecret, sessionKey);
                console.log(`[Session] Re-authenticated successfully on ${activeAccountName} account.`);
            } catch (err2) {
                const err_msg = err2.message || "Unknown generateSession error";
                if (activeAccountName === "Amrit") {
                    console.warn(`[Account Failover] Triggering backup account (Manisha) switch...`);
                    await switchAccount("Manisha");
                    isRenewingSession = false;
                    return authenticateOrRenew();
                } else {
                    throw new Error(err_msg);
                }
            }
        }
    } finally {
        isRenewingSession = false;
    }
}

async function switchAccount(accountName) {
    if (!ACCOUNT_CONFIGS[accountName]) return;
    activeAccountName = accountName;
    activeConfig = ACCOUNT_CONFIGS[accountName];
    isBreezeInitialized = false;
    breeze = null;
    console.log(`[Account Switch] Credentials updated to: ${accountName}`);
}

function readScripCodes() {
    return new Promise((resolve) => {
        const scripCodes = {};
        if (!fs.existsSync(MASTER_CSV)) {
            console.error(`[Error] masterfile.csv not found at ${MASTER_CSV}`);
            resolve(scripCodes);
            return;
        }
        fs.createReadStream(MASTER_CSV)
            .pipe(csv())
            .on('data', (row) => {
                if (row.stockCodes && row.scripcode) {
                    scripCodes[row.stockCodes.trim().toUpperCase()] = row.scripcode.trim();
                }
            })
            .on('end', () => {
                resolve(scripCodes);
            });
    });
}

function withTimeout(promise, ms) {
    return Promise.race([
        promise,
        new Promise((_, reject) => setTimeout(() => reject(new Error('Timeout')), ms))
    ]);
}

function isSessionError(resp, err) {
    const msg = (resp && resp.Error) || (err && err.message) || "";
    return msg.toLowerCase().includes("session") || msg.toLowerCase().includes("auth") || msg.toLowerCase().includes("token");
}

function isQuotaExceededError(resp, err) {
    const msg = (resp && resp.Error) || (err && err.message) || "";
    return msg.toLowerCase().includes("quota") || msg.toLowerCase().includes("limit") || msg.toLowerCase().includes("rate");
}

// ── CONCURRENT STOCK PROCESSING ───────────────────────────────────────────────
async function processAllStocks(stockList, scripCodes, todayStr) {
    const concurrency = 8;
    const allDbRows = [];

    const worker = async (stockName, index) => {
        await delay(index * 30);

        if (!scripCodes.hasOwnProperty(stockName)) {
            console.log(`[${index + 1}/${stockList.length}] ${stockName} - Skipping: Not in masterfile.csv`);
            return;
        }
        const scripCode = scripCodes[stockName];
        let intradayRows = [];

        // Fetch 1-Minute Intraday Data
        let retries = 0, success = false;
        while (retries < 3 && !success) {
            try {
                const respMin = await withTimeout(breeze.getHistoricalDatav2({
                    interval:     "1minute",
                    fromDate:     `${todayStr}T03:30:00.000Z`,
                    toDate:       `${todayStr}T15:30:00.000Z`,
                    stockCode:    scripCode,
                    exchangeCode: "NSE",
                    productType:  "cash",
                    right:        "others",
                    strikePrice:  "0"
                }), 10000);
                
                if (isSessionError(respMin, null)) {
                    console.warn(`[Session Error] Session expired during fetch for ${stockName}. Renewing...`);
                    await authenticateOrRenew();
                    continue;
                }

                if (isQuotaExceededError(respMin, null)) {
                    if (activeAccountName === "Amrit") {
                        await switchAccount("Manisha");
                        await authenticateOrRenew();
                        continue;
                    } else {
                        console.error("[Fatal] All available accounts have hit daily limits.");
                        process.exit(1);
                    }
                }

                if (respMin.Success && Array.isArray(respMin.Success) && respMin.Success.length > 0) {
                    intradayRows = respMin.Success;
                    success = true;
                } else if (respMin.Status === 500 || (respMin.Status === 200 && (!respMin.Success || respMin.Success.length === 0))) {
                    success = true; // No data available
                } else {
                    retries++;
                    if (retries < 3) await delay(1000);
                }
            } catch (e) {
                if (isSessionError(null, e)) {
                    console.warn(`[Session Error] Session exception during fetch for ${stockName}. Renewing...`);
                    await authenticateOrRenew();
                    continue;
                }
                if (isQuotaExceededError(null, e)) {
                    if (activeAccountName === "Amrit") {
                        await switchAccount("Manisha");
                        await authenticateOrRenew();
                        continue;
                    } else {
                        console.error("[Fatal] All available accounts have hit daily limits.");
                        process.exit(1);
                    }
                }
                retries++;
                if (retries < 3) await delay(1000);
            }
        }

        if (intradayRows.length > 0) {
            const now = new Date();
            const currentTimestamp = now.toISOString().slice(0, 19).replace('T', ' ');
            for (const dp of intradayRows) {
                allDbRows.push([
                    stockName,
                    dp.open,
                    dp.open,
                    dp.high,
                    dp.low,
                    dp.close,
                    dp.datetime,
                    currentTimestamp,
                    currentTimestamp,
                    todayStr,
                    'TRUE',
                    'EQ',
                    'ICICI'
                ]);
            }
            console.log(`[${index + 1}/${stockList.length}] ${stockName.padEnd(12)} | Fetched ${intradayRows.length.toString().padStart(4)} ticks [SUCCESS]`);
        } else {
            console.log(`[${index + 1}/${stockList.length}] ${stockName.padEnd(12)} | No ticks available [SKIPPED]`);
        }
    };

    const queue = [...stockList];
    const activePromises = [];
    let idx = 0;

    while (queue.length > 0 || activePromises.length > 0) {
        while (activePromises.length < concurrency && queue.length > 0) {
            const stock = queue.shift();
            const currentIdx = idx++;
            const p = worker(stock, currentIdx).finally(() => {
                const pIdx = activePromises.indexOf(p);
                if (pIdx !== -1) {
                    activePromises.splice(pIdx, 1);
                }
            });
            activePromises.push(p);
        }
        if (activePromises.length > 0) {
            await Promise.race(activePromises);
        }
    }

    return { allDbRows };
}

// ── MAIN DOWNLOAD ─────────────────────────────────────────────────────────────
async function runDownload() {
    const startTime = new Date();
    let todayStr;
    if (process.argv[2] && /^\d{4}-\d{2}-\d{2}$/.test(process.argv[2])) {
        todayStr = process.argv[2];
        console.log(`[ARG] Custom target date received: ${todayStr}`);
    } else {
        todayStr = getLocalDateString(new Date());
        console.log(`[ARG] No valid target date provided. Using today: ${todayStr}`);
    }
    const stockList  = VALIDSTOCKNAMES.split(',').map(s => s.trim()).filter(Boolean);
    const scripCodes = await readScripCodes();

    console.log(`\n${'=' .repeat(70)}`);
    console.log(`UNIFIED ICICI AFTERNOON TICK DOWNLOADER (STREAMLINED)`);
    console.log(`Target Date : ${todayStr}`);
    console.log(`Output DB   : MySQL markets.${TABLENAME}`);
    console.log(`Concurrency : 8 stocks in parallel`);
    console.log('=' .repeat(70));

    console.log("\nDeleting existing database records for today...");
    await new Promise((resolve, reject) => {
        const sql = `DELETE FROM ${TABLENAME} WHERE date = ?`;
        connection.query(sql, [todayStr], (err, results) => {
            if (err) return reject(err);
            console.log(`✔ Deleted ${results.affectedRows} existing rows for ${todayStr} from MySQL database.`);
            resolve();
        });
    });

    console.log("\nStarting parallel fetch for all stocks...");
    const { allDbRows } = await processAllStocks(stockList, scripCodes, todayStr);

    if (allDbRows.length > 0) {
        console.log(`\nInserting ${allDbRows.length} intraday tick records into MySQL...`);
        const insertSql = `
            INSERT INTO ${TABLENAME} 
            (stockname, price, open, high, low, close, time, cretime, modtime, date, isvalid, is_future, source) 
            VALUES ?
        `;
        const chunkSize = 1000;
        for (let i = 0; i < allDbRows.length; i += chunkSize) {
            const chunk = allDbRows.slice(i, i + chunkSize);
            await new Promise((resolve, reject) => {
                connection.query(insertSql, [chunk], (err, results) => {
                    if (err) return reject(err);
                    resolve();
                });
            });
        }
        console.log(`✔ Successfully inserted ${allDbRows.length} rows into MySQL \`${TABLENAME}\`.`);
    } else {
        console.log("\n⚠️ No intraday DB rows collected today.");
    }

    const duration = ((new Date() - startTime) / 1000).toFixed(2);
    console.log(`\n${'=' .repeat(70)}`);
    console.log(`🎉 Streamlined Afternoon Downloader finished in ${duration} seconds.`);
    console.log('=' .repeat(70) + '\n');
}

async function main() {
    try {
        await authenticateOrRenew();
        await runDownload();
    } catch (err) {
        console.error("[Fatal Downloader Error]:", err);
    } finally {
        connection.end();
    }
}

main();
