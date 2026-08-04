/**
 * 6.icici_daily_intraday_and_gap.js
 * ==========================================================================
 * Unified Daily ICICI Script (To be run every day at or after 3:15 PM)
 *
 * 1. Fetches 1-minute intraday ticks for all stocks for TODAY and saves to MySQL `scrapdata`.
 * 2. Uses the 9:15 AM tick from that same dataset for the CSV `Open` price.
 * 3. Fetches 1-day interval data for the previous day's `Close` price.
 * 4. Updates the gap features CSV file without creating duplicates.
 *
 * It prevents duplicate rows in both the database and the CSV by explicitly 
 * deleting today's entries before inserting.
 * ==========================================================================
 */

var BreezeConnect = require('breezeconnect').BreezeConnect;
const fs = require('fs');
const csv = require('csv-parser');
const path = require('path');
const mysql = require('mysql');
const { exec } = require('child_process');

// ── CONFIGURATION ────────────────────────────────────────────────────────────
const OUTPUT_CSV = path.join(
    __dirname,
    'yahoo_finance_all_stocks_2015_2026_gap_features.csv'
);

const SESSION_FILE  = 'icicisession.txt';
const MASTER_CSV    = 'masterfile.csv';
const CSV_HEADER    = 'Date,Stock,Open,Prev_Close,Gap_Pct,Volume_Change_Pct';

var appKey    = "77059JQ7633PoSc1mk465580B6wp1x04";
var appSecret = "6P9^377d3*412585q(527i3ZgJ437040";

const dbConfig = {
    host: 'localhost',
    user: 'root',
    password: 'root',
    database: 'markets'
};

const TABLENAME = "scrapdata";

// ── STOCK LIST ───────────────────────────────────────────────────────────────
const VALIDSTOCKNAMES = "AARTIIND,ABB,ABBOTINDIA,ABCAPITAL,ABFRL,ACC,ADANIENT,ADANIPORTS,ALKEM,AMBUJACEM,APOLLOHOSP,APOLLOTYRE,ASHOKLEY,ASIANPAINT,ASTRAL,ATUL,AUBANK,AUROPHARMA,AXISBANK,BAJAJ-AUTO,BAJAJFINSV,BAJFINANCE,BALKRISIND,BALRAMCHIN,BANDHANBNK,BANKBARODA,BANKNIFTY,BATAINDIA,BEL,BERGEPAINT,BHARATFORG,BHARTIARTL,BHEL,BIOCON,BOSCHLTD,BPCL,BRITANNIA,BSOFT,CANBK,CANFINHOME,CHAMBLFERT,CHOLAFIN,CIPLA,COALINDIA,COFORGE,COLPAL,CONCOR,COROMANDEL,CROMPTON,CUB,CUMMINSIND,DABUR,DALBHARAT,DEEPAKNTR,DELTACORP,DIVISLAB,DIXON,DLF,DRREDDY,EICHERMOT,ESCORTS,EXIDEIND,FEDERALBNK,FINNIFTY,GAIL,GLENMARK,GMRINFRA,GNFC,GODREJCP,GODREJPROP,GRANULES,GRASIM,GUJGASLTD,HAL,HAVELLS,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HEROMOTOCO,HINDALCO,HINDCOPPER,HINDPETRO,HINDUNILVR,IBULHSGFIN,ICICIBANK,ICICIGI,ICICIPRULI,IDEA,IDFC,IDFCFIRSTB,IEX,IGL,INDHOTEL,INDIACEM,INDIAMART,INDIGO,INDUSINDBK,INDUSTOWER,INFY,IOC,IPCALAB,IRCTC,ITC,JINDALSTEL,JKCEMENT,JSWSTEEL,JUBLFOOD,KOTAKBANK,L&TFH,LALPATHLAB,LAURUSLABS,LICHSGFIN,LT,LTF,LTIM,LTTS,LUPIN,M&M,M&MFIN,MANAPPURAM,MARICO,MARUTI,MCDOWELL-N,MCX,METROPOLIS,MFSL,MGL,MIDCPNIFTY,MOTHERSON,MPHASIS,MRF,MUTHOOTFIN,NATIONALUM,NAUKRI,NAVINFLUOR,NESTLEIND,NIFTY,NIFTY NEXT 50,NMDC,NTPC,OBEROIRLTY,OFSS,ONGC,PAGEIND,PEL,PERSISTENT,PETRONET,PFC,PIDILITIND,PIIND,PNB,POLYCAB,POWERGRID,PVRINOX,RAMCOCEM,RBLBANK,RECLTD,RELIANCE,SAIL,SBICARD,SBILIFE,SBIN,SHREECEM,SHRIRAMFIN,SIEMENS,SRF,SUNPHARMA,SUNTV,SYNGENE,TATACHEM,TATACOMM,TATACONSUM,TATAMOTORS,TATAPOWER,TATASTEEL,TCS,TECHM,TITAN,TORNTPHARM,TRENT,TVSMOTOR,UBL,ULTRACEMCO,UNITDSPR,UPL,VEDL,VOLTAS,WIPRO,ZEEL,ZYDUSLIFE";

// ── HELPERS ──────────────────────────────────────────────────────────────────
function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
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

function getHistoricalLinesWithoutToday(csvPath, todayStr) {
    if (!fs.existsSync(csvPath)) return [];
    const lines = fs.readFileSync(csvPath, 'utf8').split('\n');
    const filtered = [];
    let deletedCount = 0;
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        if (line.split(',')[0].trim() !== todayStr) {
            filtered.push(line);
        } else {
            deletedCount++;
        }
    }
    if (deletedCount > 0) {
        console.log(`Deleted ${deletedCount} existing rows for ${todayStr} from Gap CSV to allow a clean overwrite.`);
    } else {
        console.log(`No existing rows for ${todayStr} found in Gap CSV.`);
    }
    return filtered;
}


// ── SESSION ───────────────────────────────────────────────────────────────────
var breeze = new BreezeConnect({ appKey });
const connection = mysql.createConnection(dbConfig);

async function generateAndAuthenticateSession() {
    const session_key = readTextFileSync(SESSION_FILE);
    console.log("Session key:", session_key ? session_key : '(none)');
    try {
        await breeze.generateSession(appSecret, session_key);
        console.log("Session authenticated.");
        await runDownload();
    } catch (err) {
        const msg = String(err.message || err.toString());
        if (msg.includes("Could not authenticate credentials")) {
            console.log("Session invalid — running OTP script...");
            await new Promise((resolve, reject) => {
                exec('python 2.OTP_Amrit.py', (error, stdout, stderr) => {
                    if (error) return reject(error);
                    resolve();
                });
            });
            await generateAndAuthenticateSession();
        } else {
            console.error("Unexpected session error:", msg);
            process.exit(1);
        }
    }
}

// ── MAIN DOWNLOAD ─────────────────────────────────────────────────────────────
async function runDownload() {
    const startTime  = new Date();
    const todayStr   = getLocalDateString(startTime);
    const stockList  = VALIDSTOCKNAMES.split(',').map(s => s.trim()).filter(Boolean);
    const scripCodes = await readScripCodes();
    
    const tenDaysAgo = new Date();
    tenDaysAgo.setDate(tenDaysAgo.getDate() - 10);
    const fromStr = getLocalDateString(tenDaysAgo);

    console.log(`\n${'='.repeat(70)}`);
    console.log(`UNIFIED ICICI DAILY DOWNLOADER`);
    console.log(`Target Date : ${todayStr}`);
    console.log(`Output CSV  : ${OUTPUT_CSV}`);
    console.log(`Output DB   : MySQL markets.${TABLENAME}`);
    console.log('='.repeat(70));

    // 1. Delete today's existing data from Database to prevent duplicates
    await new Promise((resolve, reject) => {
        const deleteSql = `DELETE FROM markets.${TABLENAME} WHERE date = ?`;
        connection.query(deleteSql, [todayStr], (err, result) => {
            if (err) {
                console.error("Error deleting today's rows from DB:", err);
                return reject(err);
            }
            console.log(`Deleted ${result.affectedRows} existing rows for ${todayStr} from DB.`);
            resolve();
        });
    });

    // 2. Read existing CSV and exclude today's rows
    const oldLines = getHistoricalLinesWithoutToday(OUTPUT_CSV, todayStr);
    const newLines = [];

    // Process each stock
    for (let si = 0; si < stockList.length; si++) {
        const stockName = stockList[si];
        console.log(`\n[${si + 1}/${stockList.length}] ${stockName}`);

        if (!scripCodes.hasOwnProperty(stockName)) {
            console.log(`  Not found in masterfile.csv. Skipping.`);
            continue;
        }
        const scripCode = scripCodes[stockName];
        let todayOpen = null;
        let prevClose = null;

        // --- FETCH 1-MINUTE DATA FOR TODAY (FOR DB AND CSV OPEN) ---
        let retries = 0, success = false;
        let intradayRows = [];
        
        while (retries < 3 && !success) {
            try {
                const respMin = await breeze.getHistoricalDatav2({
                    interval:     "1minute",
                    fromDate:     `${todayStr}T03:30:00.000Z`,
                    toDate:       `${todayStr}T15:30:00.000Z`,
                    stockCode:    scripCode,
                    exchangeCode: "NSE", // Adjust if fetching NFO/futures
                    productType:  "cash",
                    right:        "others",
                    strikePrice:  "0"
                });
                
                if (respMin.Success && Array.isArray(respMin.Success) && respMin.Success.length > 0) {
                    // Save the first tick's open for the Gap CSV
                    todayOpen = parseFloat(respMin.Success[0].open);
                    intradayRows = respMin.Success;
                    success = true;
                } else if (respMin.Status === 500) {
                    console.log(`  No 1-minute data available for today yet.`);
                    success = true;
                }
            } catch (e) {
                retries++;
                console.error(`  [1Min] Error (Attempt ${retries}): ${e.message || e}`);
                await delay(1000);
            }
        }

        // Insert Intraday Rows to DB
        if (intradayRows.length > 0) {
            try {
                const now = new Date();
                const currentTimestamp = now.toISOString().slice(0, 19).replace('T', ' ');
                const dbDataToInsert = intradayRows.map(dp => [
                    stockName,
                    dp.open, // price
                    dp.open, // open
                    dp.high, // high
                    dp.low,  // low
                    dp.close,// close
                    dp.datetime,
                    currentTimestamp, // cretime
                    currentTimestamp, // modtime
                    todayStr, // date
                    'TRUE',   // isvalid
                    'EQ',     // is_future
                    'ICICI'   // source
                ]);
                
                const sql = `INSERT INTO markets.${TABLENAME} (stockname, price, \`open\`, high, \`low\`, \`close\`, time, cretime, modtime, date, isvalid, is_future, source) VALUES ?`;
                await new Promise((resolve, reject) => {
                    connection.query(sql, [dbDataToInsert], (err, result) => {
                        if (err) return reject(err);
                        console.log(`  -> Inserted ${result.affectedRows} ticks into DB.`);
                        resolve();
                    });
                });
            } catch (dbErr) {
                console.error(`  Error inserting into DB: ${dbErr}`);
            }
        }

        if (todayOpen === null || todayOpen === 0) {
            console.log(`  Today's open not found, skipping CSV update.`);
            await delay(500); // Wait before next stock
            continue;
        }

        await delay(500); // Pause between ICICI API calls

        // --- FETCH 1-DAY DATA (FOR CSV PREVIOUS CLOSE) ---
        retries = 0; success = false;
        while (retries < 3 && !success) {
            try {
                const respDaily = await breeze.getHistoricalDatav2({
                    interval:     "1day",
                    fromDate:     `${fromStr}T00:00:00.000Z`,
                    toDate:       `${todayStr}T23:59:59.000Z`,
                    stockCode:    scripCode,
                    exchangeCode: "NSE",
                    productType:  "cash",
                    right:        "others",
                    strikePrice:  "0"
                });
                
                if (respDaily.Success && Array.isArray(respDaily.Success)) {
                    // Strictly before today
                    const pastDays = respDaily.Success.filter(dp => dp.datetime.slice(0, 10) < todayStr);
                    if (pastDays.length > 0) {
                        prevClose = parseFloat(pastDays[pastDays.length - 1].close);
                    }
                    success = true;
                } else if (respDaily.Status === 500) {
                    success = true; // No data
                }
            } catch (e) {
                retries++;
                console.error(`  [Daily] Error (Attempt ${retries}): ${e.message || e}`);
                await delay(1000);
            }
        }

        if (prevClose === null) {
            console.log(`  Could not find previous day data, skipping CSV update.`);
            await delay(500); // Wait before next stock
            continue;
        }

        // --- COMPUTE AND SAVE CSV ROW ---
        const gapPct = ((todayOpen - prevClose) / prevClose * 100).toFixed(6);
        const volChangePct = '0.000000'; // Hardcoded safely as discussed

        newLines.push(`${todayStr},${stockName},${todayOpen},${prevClose},${gapPct},${volChangePct}`);
        console.log(`  -> CSV Ready | Open: ${todayOpen} | PrevClose: ${prevClose} | Gap: ${gapPct}%`);
        
        await delay(500); // Rate limit pause before next stock
    }

    // Write final CSV
    console.log(`\nWriting ${oldLines.length} old rows + ${newLines.length} today rows to CSV...`);
    const finalContent = CSV_HEADER + '\n' + oldLines.concat(newLines).join('\n') + '\n';
    fs.writeFileSync(OUTPUT_CSV, finalContent, 'utf8');

    const elapsed = ((new Date() - startTime) / 1000).toFixed(1);
    console.log(`DONE in ${elapsed}s. DB and CSV successfully updated!`);
    
    connection.end();
}

// ── ENTRY POINT ───────────────────────────────────────────────────────────────
generateAndAuthenticateSession();
