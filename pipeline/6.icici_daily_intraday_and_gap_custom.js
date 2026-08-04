/**
 * 6.icici_daily_intraday_and_gap_custom.js (CUSTOM DATE ML PIPELINE VERSION - DUAL ACCOUNT)
 * =========================================================================================
 * Unified ICICI Script with custom target date parameter & automatic Manisha account failover.
 * =========================================================================================
 */

var BreezeConnect = require('breezeconnect').BreezeConnect;
const fs = require('fs');
const csv = require('csv-parser');
const path = require('path');
const mysql = require('mysql');
const { exec } = require('child_process');

// ── CONFIGURATION ────────────────────────────────────────────────────────────
const parentDir = path.dirname(__dirname);
const MASTER_CSV = path.join(parentDir, 'config', 'masterfile.csv');

// Account Configurations
const ACCOUNT_CONFIGS = {
    Amrit: {
        name: "Amrit",
        appKey: "77059JQ7633PoSc1mk465580B6wp1x04",
        appSecret: "6P9^377d3*412585q(527i3ZgJ437040",
        sessionFile: path.join(parentDir, 'auth', 'icicisession.txt'),
        otpScript: path.join(parentDir, 'auth', '2.OTP_Amrit.py')
    },
    Manisha: {
        name: "Manisha",
        appKey: "1f3Pi887R1652C91_76J6808z8191jq~",
        appSecret: "4d7(89!0_3~8+11%49J38+g340k99n2~",
        sessionFile: path.join(parentDir, 'auth', 'icicisession_Manisha.txt'),
        otpScript: path.join(parentDir, 'auth', '2.OTP_Manisha.py')
    }
};

let activeAccountName = "Amrit";
let activeConfig = ACCOUNT_CONFIGS[activeAccountName];

const dbConfig = {
    host: 'localhost',
    user: 'root',
    password: 'root',
    database: 'markets'
};

const TABLENAME = "scrapdata";

const VALIDSTOCKNAMES = "AARTIIND,ABB,ABBOTINDIA,ABCAPITAL,ABFRL,ACC,ADANIENT,ADANIPORTS,ALKEM,AMBUJACEM,APOLLOHOSP,APOLLOTYRE,ASHOKLEY,ASIANPAINT,ASTRAL,ATUL,AUBANK,AUROPHARMA,AXISBANK,BAJAJ-AUTO,BAJAJFINSV,BAJFINANCE,BALKRISIND,BALRAMCHIN,BANDHANBNK,BANKBARODA,BANKNIFTY,BATAINDIA,BEL,BERGEPAINT,BHARATFORG,BHARTIARTL,BHEL,BIOCON,BOSCHLTD,BPCL,BRITANNIA,BSOFT,CANBK,CANFINHOME,CHAMBLFERT,CHOLAFIN,CIPLA,COALINDIA,COFORGE,COLPAL,CONCOR,COROMANDEL,CROMPTON,CUB,CUMMINSIND,DABUR,DALBHARAT,DEEPAKNTR,DELTACORP,DIVISLAB,DIXON,DLF,DRREDDY,EICHERMOT,ESCORTS,EXIDEIND,FEDERALBNK,FINNIFTY,GAIL,GLENMARK,GMRINFRA,GNFC,GODREJCP,GODREJPROP,GRANULES,GRASIM,GUJGASLTD,HAL,HAVELLS,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HEROMOTOCO,HINDALCO,HINDCOPPER,HINDPETRO,HINDUNILVR,IBULHSGFIN,ICICIBANK,ICICIGI,ICICIPRULI,IDEA,IDFC,IDFCFIRSTB,IEX,IGL,INDHOTEL,INDIACEM,INDIAMART,INDIGO,INDUSINDBK,INDUSTOWER,INFY,IOC,IPCALAB,IRCTC,ITC,JINDALSTEL,JKCEMENT,JSWSTEEL,JUBLFOOD,KOTAKBANK,L&TFH,LALPATHLAB,LAURUSLABS,LICHSGFIN,LT,LTF,LTIM,LTTS,LUPIN,M&M,M&MFIN,MANAPPURAM,MARICO,MARUTI,MCDOWELL-N,MCX,METROPOLIS,MFSL,MGL,MIDCPNIFTY,MOTHERSON,MPHASIS,MRF,MUTHOOTFIN,NATIONALUM,NAUKRI,NAVINFLUOR,NESTLEIND,NIFTY,NIFTY NEXT 50,NMDC,NTPC,OBEROIRLTY,OFSS,ONGC,PAGEIND,PEL,PERSISTENT,PETRONET,PFC,PIDILITIND,PIIND,PNB,POLYCAB,POWERGRID,PVRINOX,RAMCOCEM,RBLBANK,RECLTD,RELIANCE,SAIL,SBICARD,SBILIFE,SBIN,SHREECEM,SHRIRAMFIN,SIEMENS,SRF,SUNPHARMA,SUNTV,SYNGENE,TATACHEM,TATACOMM,TATACONSUM,TATAMOTORS,TATAPOWER,TATASTEEL,TCS,TECHM,TITAN,TORNTPHARM,TRENT,TVSMOTOR,UBL,ULTRACEMCO,UNITDSPR,UPL,VEDL,VOLTAS,WIPRO,ZEEL,ZYDUSLIFE";

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function withTimeout(promise, ms, errorMessage = "Timeout exceeded") {
    let timeoutId;
    const timeoutPromise = new Promise((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error(errorMessage)), ms);
    });
    return Promise.race([promise, timeoutPromise]).finally(() => clearTimeout(timeoutId));
}

function readTextFileSync(filePath) {
    try {
        return fs.readFileSync(filePath, 'utf8').trim();
    } catch (err) {
        return null;
    }
}

function getLocalDateString(d) {
    const tzOffset = d.getTimezoneOffset() * 60000;
    return (new Date(d.getTime() - tzOffset)).toISOString().slice(0, 10);
}

function readScripCodes() {
    const codes = {};
    return new Promise((resolve, reject) => {
        fs.createReadStream(MASTER_CSV)
            .pipe(csv())
            .on('data', row => { codes[row.stockCodes] = row.scripcode; })
            .on('end',  () => resolve(codes))
            .on('error', reject);
    });
}

function isSessionError(resp, err) {
    const errorMsg = String(
        (err && (err.message || err)) || 
        (resp && (resp.Error || resp.Message || JSON.stringify(resp))) || 
        ""
    ).toLowerCase();
    return errorMsg.includes("could not authenticate credentials") || 
           errorMsg.includes("session key required") ||
           errorMsg.includes("api session") ||
           (errorMsg.includes("session") && (errorMsg.includes("invalid") || errorMsg.includes("expired") || errorMsg.includes("authenticate")));
}

function isQuotaExceededError(resp, err) {
    const errorMsg = String(
        (err && (err.message || err)) || 
        (resp && (resp.Error || resp.Message || JSON.stringify(resp))) || 
        ""
    ).toLowerCase();
    return errorMsg.includes("limit exceed") || errorMsg.includes("api call per day");
}

let breeze = new BreezeConnect({ appKey: activeConfig.appKey });
const connection = mysql.createConnection(dbConfig);

let globalRenewalCount = 0;
const MAX_RENEWAL_ATTEMPTS = 2;

async function switchAccount(accountName) {
    console.log(`\n=======================================================`);
    console.log(`[Account Failover] Switching intraday fetch to ${accountName}`);
    console.log(`=======================================================`);
    activeAccountName = accountName;
    activeConfig = ACCOUNT_CONFIGS[activeAccountName];
    breeze = new BreezeConnect({ appKey: activeConfig.appKey });
    globalRenewalCount = 0;
}

async function authenticateOrRenew() {
    globalRenewalCount++;
    if (globalRenewalCount > MAX_RENEWAL_ATTEMPTS) {
        if (activeAccountName === "Amrit") {
            await switchAccount("Manisha");
            return authenticateOrRenew();
        } else {
            console.error("[Fatal] Exceeded max renewal attempts across all accounts.");
            process.exit(1);
        }
    }

    try {
        console.log(`[Auth] Attempting login for ${activeAccountName} (Attempt ${globalRenewalCount})...`);
        const session_key = readTextFileSync(activeConfig.sessionFile);
        await withTimeout(breeze.generateSession(activeConfig.appSecret, session_key), 15000);
        console.log(`[Auth] Authenticated ${activeAccountName} account successfully.`);
    } catch (err) {
        console.warn(`[Auth Warning] ${activeAccountName} session failed:`, err.message || err);
        if (activeAccountName === "Amrit") {
            console.warn(`[Failover Triggered] Amrit auth failed. Switching immediately to Manisha account...`);
            await switchAccount("Manisha");
            return authenticateOrRenew();
        }
        console.log(`[Auth] Triggering ${activeConfig.otpScript}...`);
        await new Promise((resolve, reject) => {
            exec(`python3 "${activeConfig.otpScript}" --force`, { cwd: parentDir }, (error, stdout, stderr) => {
                if (error) return reject(error);
                resolve();
            });
        });
        const fresh_session_key = readTextFileSync(activeConfig.sessionFile);
        await withTimeout(breeze.generateSession(activeConfig.appSecret, fresh_session_key), 15000);
        console.log(`[Auth] Refreshed authentication successful for ${activeAccountName}.`);
    }
}

let TARGET_DATE;
if (process.argv[2] && /^\d{4}-\d{2}-\d{2}$/.test(process.argv[2])) {
    TARGET_DATE = process.argv[2];
    console.log(`[ARG] Custom target date received: ${TARGET_DATE}`);
} else {
    TARGET_DATE = getLocalDateString(new Date());
    console.log(`[ARG] No valid target date provided. Using today: ${TARGET_DATE}`);
}

const FROM_DATE = `${TARGET_DATE}T07:00:00.000Z`;
const TO_DATE   = `${TARGET_DATE}T17:00:00.000Z`;

function deleteRecordsForDate(targetDate) {
    return new Promise((resolve, reject) => {
        const sql = `DELETE FROM ${TABLENAME} WHERE DATE(date) = ?`;
        connection.query(sql, [targetDate], (err, results) => {
            if (err) return reject(err);
            console.log(`[DB] Deleted ${results.affectedRows} existing records for target date ${targetDate}.`);
            resolve();
        });
    });
}

function fetchIntraday(stockCode) {
    return breeze.getHistoricalDatav2({
        interval:     "1minute",
        fromDate:     FROM_DATE,
        toDate:       TO_DATE,
        stockCode:    stockCode,
        exchangeCode: "NSE",
        productType:  "cash"
    });
}

async function runDownload() {
    console.log(`\n=======================================================`);
    console.log(`ICICI EQUITY INTRADAY DATA LOADER`);
    console.log(`Target Date : ${TARGET_DATE}`);
    console.log(`Target Table: markets.${TABLENAME}`);
    console.log(`=======================================================\n`);

    await deleteRecordsForDate(TARGET_DATE);

    const scripCodesMap = await readScripCodes();
    const stocks = Object.keys(scripCodesMap).filter(stk =>
        VALIDSTOCKNAMES.split(',').includes(stk)
    );
    console.log(`[Stock List] Found ${stocks.length} valid stocks to process.`);

    let successCount = 0;
    let failCount    = 0;
    let emptyCount   = 0;

    for (let i = 0; i < stocks.length; i++) {
        const stockCode = stocks[i];
        console.log(`[${i + 1}/${stocks.length}] [Acc:${activeAccountName}] Processing ${stockCode}...`);

        let attempts = 0;
        let breezeRes = null;
        let fetchSuccess = false;

        while (attempts < 3 && !fetchSuccess) {
            attempts++;
            try {
                breezeRes = await withTimeout(
                    fetchIntraday(stockCode),
                    12000,
                    `Timeout for ${stockCode}`
                );

                if (isSessionError(breezeRes, null)) {
                    console.warn(`[Session Error] Account ${activeAccountName} session expired on ${stockCode}. Renewing...`);
                    await authenticateOrRenew();
                    continue;
                }

                if (isQuotaExceededError(breezeRes, null)) {
                    if (activeAccountName === "Amrit") {
                        await switchAccount("Manisha");
                        await authenticateOrRenew();
                        continue;
                    } else {
                        console.error("[Fatal] All ICICI accounts exceeded daily quota limits.");
                        process.exit(1);
                    }
                }

                fetchSuccess = true;
            } catch (err) {
                console.error(`  Attempt ${attempts}/3 error for ${stockCode}:`, err.message || err);
                if (isQuotaExceededError(null, err) && activeAccountName === "Amrit") {
                    await switchAccount("Manisha");
                    await authenticateOrRenew();
                    continue;
                }
                if (attempts < 3) await delay(1500);
            }
        }

        if (!fetchSuccess || !breezeRes) {
            console.error(`  [SKIP] Failed to fetch ${stockCode} after 3 attempts.`);
            failCount++;
            continue;
        }

        const dataArray = breezeRes.Success || breezeRes.success || [];

        if (!Array.isArray(dataArray) || dataArray.length === 0) {
            console.log(`  [INFO] No intraday data returned for ${stockCode}.`);
            emptyCount++;
            continue;
        }

        console.log(`  Received ${dataArray.length} bars for ${stockCode}. Inserting DB...`);

        const insertValues = dataArray.map(item => {
            const rawDt     = item.datetime || item.datetime_val || '';
            const formatted = rawDt ? rawDt.replace('T', ' ').replace('.000Z', '') : TARGET_DATE;
            return [
                stockCode,
                parseFloat(item.open || 0),
                parseFloat(item.open || 0),
                parseFloat(item.high || 0),
                parseFloat(item.low || 0),
                parseFloat(item.close || 0),
                formatted,
                TARGET_DATE,
                'TRUE',
                'EQ',
                "ICICI"
            ];
        });

        const sql = `
            INSERT INTO ${TABLENAME} 
            (stockname, price, open, high, low, close, time, date, isvalid, is_future, source) 
            VALUES ? 
            ON DUPLICATE KEY UPDATE 
                open = VALUES(open), 
                high = VALUES(high), 
                low = VALUES(low), 
                close = VALUES(close);
        `;

        try {
            await new Promise((resQuery, rejQuery) => {
                connection.query(sql, [insertValues], (errQuery, result) => {
                    if (errQuery) rejQuery(errQuery);
                    else resQuery(result);
                });
            });
            successCount++;
        } catch (dbErr) {
            console.error(`  [DB Error] ${stockCode}:`, dbErr.message);
            failCount++;
        }

        await delay(300);
    }

    console.log(`\n=======================================================`);
    console.log(`DOWNLOAD SUMMARY FOR ${TARGET_DATE}`);
    console.log(`Successful : ${successCount}`);
    console.log(`Empty/NoData: ${emptyCount}`);
    console.log(`Failed     : ${failCount}`);
    console.log(`=======================================================\n`);
}

async function main() {
    try {
        await authenticateOrRenew();
        await runDownload();
        console.log("[Pipeline Complete] Intraday equity data download finished.");
    } catch (err) {
        console.error("[Fatal Error]:", err);
    } finally {
        connection.end();
    }
}

main();
