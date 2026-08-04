/**
 * update_today_gaps_morning.js
 * ==========================================================================
 * Morning Daily Gap Feature Downloader
 * Runs at 9:32 AM as part of the Morning Simulation Pipeline.
 * 
 * Primary: Yahoo Finance API (No limits, fast, no login needed)
 * Failover: ICICI Breeze API (Amrit + Manisha backup)
 * ==========================================================================
 */

var BreezeConnect = require('breezeconnect').BreezeConnect;
const fs = require('fs');
const csv = require('csv-parser');
const path = require('path');
const https = require('https');

// ── CONFIGURATION ────────────────────────────────────────────────────────────
const parentDir = path.dirname(__dirname);
const OUTPUT_CSV = path.join(parentDir, 'data', 'yahoo_finance_all_stocks_2015_2026_gap_features.csv');
const MASTER_CSV = path.join(parentDir, 'config', 'masterfile.csv');
const SUMMARY_JSON = path.join(parentDir, 'pipeline', 'morning_gap_summary.json');
const CSV_HEADER = 'Date,Stock,Open,Prev_Close,Gap_Pct,Volume_Change_Pct';

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
let breeze = null;
let isBreezeInitialized = false;

const VALIDSTOCKNAMES = "AARTIIND,ABB,ABBOTINDIA,ABCAPITAL,ABFRL,ACC,ADANIENT,ADANIPORTS,ALKEM,AMBUJACEM,APOLLOHOSP,APOLLOTYRE,ASHOKLEY,ASIANPAINT,ASTRAL,ATUL,AUBANK,AUROPHARMA,AXISBANK,BAJAJ-AUTO,BAJAJFINSV,BAJFINANCE,BALKRISIND,BALRAMCHIN,BANDHANBNK,BANKBARODA,BANKNIFTY,BATAINDIA,BEL,BERGEPAINT,BHARATFORG,BHARTIARTL,BHEL,BIOCON,BOSCHLTD,BPCL,BRITANNIA,BSOFT,CANBK,CANFINHOME,CHAMBLFERT,CHOLAFIN,CIPLA,COALINDIA,COFORGE,COLPAL,CONCOR,COROMANDEL,CROMPTON,CUB,CUMMINSIND,DABUR,DALBHARAT,DEEPAKNTR,DELTACORP,DIVISLAB,DIXON,DLF,DRREDDY,EICHERMOT,ESCORTS,EXIDEIND,FEDERALBNK,FINNIFTY,GAIL,GLENMARK,GMRINFRA,GNFC,GODREJCP,GODREJPROP,GRANULES,GRASIM,GUJGASLTD,HAL,HAVELLS,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HEROMOTOCO,HINDALCO,HINDCOPPER,HINDPETRO,HINDUNILVR,IBULHSGFIN,ICICIBANK,ICICIGI,ICICIPRULI,IDEA,IDFC,IDFCFIRSTB,IEX,IGL,INDHOTEL,INDIACEM,INDIAMART,INDIGO,INDUSINDBK,INDUSTOWER,INFY,IOC,IPCALAB,IRCTC,ITC,JINDALSTEL,JKCEMENT,JSWSTEEL,JUBLFOOD,KOTAKBANK,L&TFH,LALPATHLAB,LAURUSLABS,LICHSGFIN,LT,LTF,LTIM,LTTS,LUPIN,M&M,M&MFIN,MANAPPURAM,MARICO,MARUTI,MCDOWELL-N,MCX,METROPOLIS,MFSL,MGL,MIDCPNIFTY,MOTHERSON,MPHASIS,MRF,MUTHOOTFIN,NATIONALUM,NAUKRI,NAVINFLUOR,NESTLEIND,NIFTY,NIFTY NEXT 50,NMDC,NTPC,OBEROIRLTY,OFSS,ONGC,PAGEIND,PEL,PERSISTENT,PETRONET,PFC,PIDILITIND,PIIND,PNB,POLYCAB,POWERGRID,PVRINOX,RAMCOCEM,RBLBANK,RECLTD,RELIANCE,SAIL,SBICARD,SBILIFE,SBIN,SHREECEM,SHRIRAMFIN,SIEMENS,SRF,SUNPHARMA,SUNTV,SYNGENE,TATACHEM,TATACOMM,TATACONSUM,TATAMOTORS,TATAPOWER,TATASTEEL,TCS,TECHM,TITAN,TORNTPHARM,TRENT,TVSMOTOR,UBL,ULTRACEMCO,UNITDSPR,UPL,VEDL,VOLTAS,WIPRO,ZEEL,ZYDUSLIFE";

// ── UTILS ────────────────────────────────────────────────────────────────────
function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

function getLocalDateString(date) {
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

// ── AUTH & SESSION MANAGEMENT (FOR ICICI) ────────────────────────────────────
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

async function authenticateOrRenew() {
    await initializeBreeze();
    let sessionKey = readSessionKey(activeConfig.sessionFile);
    
    if (!sessionKey) {
        console.log(`[Auth] No active session file. Triggering OTP generation for ${activeAccountName}...`);
        await runOtpScript(activeConfig.otpScript);
        sessionKey = readSessionKey(activeConfig.sessionFile);
        if (!sessionKey) throw new Error(`OTP generation failed to create session file for ${activeAccountName}`);
    }

    try {
        await breeze.generateSession(activeConfig.appSecret, sessionKey);
        console.log(`[Session] Authenticated successfully on ${activeAccountName} account.`);
    } catch (err) {
        console.warn(`[Auth Error] Session failed for ${activeAccountName}: ${err.message}. Retrying...`);
        await runOtpScript(activeConfig.otpScript);
        sessionKey = readSessionKey(activeConfig.sessionFile);
        try {
            await breeze.generateSession(activeConfig.appSecret, sessionKey);
            console.log(`[Session] Re-authenticated successfully on ${activeAccountName} account.`);
        } catch (err2) {
            throw new Error(`Could not authenticate credentials: ${err2.message}`);
        }
    }
}

async function switchAccount(accountName) {
    if (!ACCOUNT_CONFIGS[accountName]) return;
    activeAccountName = accountName;
    activeConfig = ACCOUNT_CONFIGS[accountName];
    isBreezeInitialized = false;
    breeze = null;
    console.log(`[Account Switch] Switched active downloader credentials to: ${accountName}`);
}

// Helper: Read stock scrip codes from masterfile.csv
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

// ── YAHOO FINANCE SCRAPER ────────────────────────────────────────────────────
function fetchFromYahooFinance(stockName) {
    return new Promise((resolve) => {
        let symbol = stockName;
        if (symbol === "NIFTY NEXT 50") symbol = "^NSMID_50";
        else symbol = `${symbol}.NS`;

        const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=1d&range=2d`;
        
        https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res) => {
            let data = '';
            res.on('data', (chunk) => { data += chunk; });
            res.on('end', () => {
                try {
                    const parsed = JSON.parse(data);
                    if (!parsed.chart || !parsed.chart.result || parsed.chart.result.length === 0) {
                        return resolve(null);
                    }
                    const result = parsed.chart.result[0];
                    const indicators = result.indicators.quote[0];
                    const meta = result.meta;
                    
                    let prevClose = meta.chartPreviousClose || null;
                    let todayOpen = null;
                    
                    if (indicators && indicators.open && indicators.open.length > 0) {
                        todayOpen = indicators.open[indicators.open.length - 1];
                    }
                    
                    resolve({ prevClose, todayOpen });
                } catch (e) {
                    resolve(null);
                }
            });
        }).on('error', () => {
            resolve(null);
        });
    });
}

// ── PROCESS STOCK GAP VALUES ─────────────────────────────────────────────────
async function processAllGaps(stockList, scripCodes, todayStr, fromStr) {
    const concurrency = 8;
    const newLines = [];
    let stats = {
        total: stockList.length,
        yahoo: 0,
        icici: 0,
        skipped: 0
    };

    const worker = async (stockName, index) => {
        await delay(index * 30);

        if (!scripCodes.hasOwnProperty(stockName)) {
            stats.skipped++;
            return;
        }
        const scripCode = scripCodes[stockName];
        let todayOpen = null;
        let prevClose = null;

        // 1. Try Yahoo Finance first (Primary)
        const yfRes = await fetchFromYahooFinance(stockName);
        if (yfRes && yfRes.todayOpen && yfRes.prevClose && yfRes.todayOpen !== 0) {
            todayOpen = yfRes.todayOpen;
            prevClose = yfRes.prevClose;
            
            const gapPct = ((todayOpen - prevClose) / prevClose * 100).toFixed(6);
            const volChangePct = '0.000000';
            newLines.push(`${todayStr},${stockName},${todayOpen},${prevClose},${gapPct},${volChangePct}`);
            stats.yahoo++;
            console.log(`[${index + 1}/${stockList.length}] ${stockName.padEnd(12)} | Open: ${todayOpen.toFixed(2).padStart(8)} | PrevClose: ${prevClose.toFixed(2).padStart(8)} | Gap: ${(gapPct + '%').padStart(8)} [SUCCESS - YAHOO PRIMARY]`);
        } else {
            // 2. Fall back to ICICI Breeze API (Failover)
            console.log(`[${index + 1}/${stockList.length}] ${stockName.padEnd(12)} | Yahoo primary missed or returned 0. Falling back to ICICI Breeze...`);
            
            // Connect breeze lazily on first fallback
            try {
                if (!breeze) {
                    await authenticateOrRenew();
                }
            } catch (err_auth) {
                console.error(`[Failover Error] Failed to initialize ICICI backup connection: ${err_auth.message}`);
                stats.skipped++;
                return;
            }

            // Task 1: Intraday Open Price
            const fetchIntradayOpen = async () => {
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
                            await authenticateOrRenew();
                            continue;
                        }
                        if (isQuotaExceededError(respMin, null)) {
                            if (activeAccountName === "Amrit") {
                                await switchAccount("Manisha");
                                await authenticateOrRenew();
                                continue;
                            } else {
                                throw new Error("API Quota exceeded across all accounts");
                            }
                        }

                        if (respMin.Success && Array.isArray(respMin.Success) && respMin.Success.length > 0) {
                            todayOpen = parseFloat(respMin.Success[0].open);
                            success = true;
                        } else {
                            success = true;
                        }
                    } catch (e) {
                        retries++;
                        if (retries < 3) await delay(1000);
                    }
                }
            };

            // Task 2: Previous Close Price
            const fetchPrevClose = async () => {
                let retries = 0, success = false;
                while (retries < 3 && !success) {
                    try {
                        const respDaily = await withTimeout(breeze.getHistoricalDatav2({
                            interval:     "1day",
                            fromDate:     `${fromStr}T00:00:00.000Z`,
                            toDate:       `${todayStr}T23:59:59.000Z`,
                            stockCode:    scripCode,
                            exchangeCode: "NSE",
                            productType:  "cash",
                            right:        "others",
                            strikePrice:  "0"
                        }), 10000);

                        if (isSessionError(respDaily, null)) {
                            await authenticateOrRenew();
                            continue;
                        }
                        if (isQuotaExceededError(respDaily, null)) {
                            if (activeAccountName === "Amrit") {
                                await switchAccount("Manisha");
                                await authenticateOrRenew();
                                continue;
                            } else {
                                throw new Error("API Quota exceeded across all accounts");
                            }
                        }
                        
                        if (respDaily.Success && Array.isArray(respDaily.Success)) {
                            const pastDays = respDaily.Success.filter(dp => dp.datetime.slice(0, 10) < todayStr);
                            if (pastDays.length > 0) {
                                prevClose = parseFloat(pastDays[pastDays.length - 1].close);
                            }
                            success = true;
                        } else {
                            success = true;
                        }
                    } catch (e) {
                        retries++;
                        if (retries < 3) await delay(1000);
                    }
                }
            };

            await Promise.all([fetchIntradayOpen(), fetchPrevClose()]);

            if (todayOpen !== null && todayOpen !== 0 && prevClose !== null) {
                const gapPct = ((todayOpen - prevClose) / prevClose * 100).toFixed(6);
                const volChangePct = '0.000000';
                newLines.push(`${todayStr},${stockName},${todayOpen},${prevClose},${gapPct},${volChangePct}`);
                stats.icici++;
                console.log(`[${index + 1}/${stockList.length}] ${stockName.padEnd(12)} | Open: ${todayOpen.toFixed(2).padStart(8)} | PrevClose: ${prevClose.toFixed(2).padStart(8)} | Gap: ${(gapPct + '%').padStart(8)} [SUCCESS - ICICI FALLBACK]`);
            } else {
                stats.skipped++;
                console.log(`[${index + 1}/${stockList.length}] ${stockName.padEnd(12)} | Missing Open or PrevClose [SKIPPED]`);
            }
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

    return { newLines, stats };
}

// Reads existing lines from the CSV, dropping any existing entries for today
function getHistoricalLinesWithoutToday(filePath, todayStr) {
    if (!fs.existsSync(filePath)) return [];
    const content = fs.readFileSync(filePath, 'utf8');
    const lines = content.split('\n');
    return lines.slice(1).map(l => l.trim()).filter(l => {
        if (!l) return false;
        const datePart = l.split(',')[0];
        return datePart !== todayStr;
    });
}

// ── MAIN RUN ─────────────────────────────────────────────────────────────────
async function runMorningGaps() {
    const startTime = new Date();
    let todayStr;
    if (process.argv[2] && /^\d{4}-\d{2}-\d{2}$/.test(process.argv[2])) {
        todayStr = process.argv[2];
        console.log(`[ARG] Custom target date received: ${todayStr}`);
    } else {
        todayStr = getLocalDateString(startTime);
        console.log(`[ARG] No valid target date provided. Using today: ${todayStr}`);
    }
    const stockList = VALIDSTOCKNAMES.split(',').map(s => s.trim()).filter(Boolean);
    const scripCodes = await readScripCodes();
    
    const targetDateObj = new Date(todayStr);
    const tenDaysAgo = new Date(targetDateObj);
    tenDaysAgo.setDate(tenDaysAgo.getDate() - 10);
    const fromStr = getLocalDateString(tenDaysAgo);

    console.log(`\n=======================================================`);
    console.log(`🌅 MORNING GAP FEATURES CONCURRENT DOWNLOADER`);
    console.log(`Target Date: ${todayStr}`);
    console.log(`Output CSV : ${OUTPUT_CSV}`);
    console.log(`=======================================================`);

    const { newLines, stats } = await processAllGaps(stockList, scripCodes, todayStr, fromStr);

    // Save outputs to gap features CSV
    console.log("\nUpdating CSV gap features file...");
    const historicalLines = getHistoricalLinesWithoutToday(OUTPUT_CSV, todayStr);
    const finalContent = [CSV_HEADER, ...historicalLines, ...newLines].join('\n') + '\n';
    fs.writeFileSync(OUTPUT_CSV, finalContent, 'utf8');
    console.log(`✔ Successfully updated ${OUTPUT_CSV} (${newLines.length} rows written).`);

    // Save summary statistics to JSON
    fs.writeFileSync(SUMMARY_JSON, JSON.stringify(stats, null, 4), 'utf8');
    console.log(`✔ Saved execution summary to ${SUMMARY_JSON}`);

    const endTime = new Date();
    const executionTime = ((endTime - startTime) / 1000).toFixed(2);
    console.log(`\n🎉 Morning Ingestion Complete in ${executionTime} seconds.`);
    console.log(`📊 Yahoo: ${stats.yahoo} | ICICI: ${stats.icici} | Skipped: ${stats.skipped}\n`);
}

runMorningGaps().catch(e => {
    console.error("Fatal Error running morning gap downloader:", e);
    process.exit(1);
});
