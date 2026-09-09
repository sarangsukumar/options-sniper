var BreezeConnect = require('breezeconnect').BreezeConnect;
const fs = require('fs');
const csv = require('csv-parser');
const mysql = require('mysql');
const { exec } = require('child_process');
const path = require('path');

// Resolve directory relative to script position
const parentDir = path.dirname(__dirname);

// Command line arguments parsing
let startIndex = 0;
let endIndex = null;
let skipComplete = false;

const positionalArgs = [];
for (let i = 2; i < process.argv.length; i++) {
    if (process.argv[i] === '--start-index') {
        startIndex = parseInt(process.argv[i + 1], 10);
        i++;
    } else if (process.argv[i] === '--end-index') {
        endIndex = parseInt(process.argv[i + 1], 10);
        i++;
    } else if (process.argv[i] === '--skip-complete') {
        skipComplete = true;
    } else {
        positionalArgs.push(process.argv[i]);
    }
}

// 1. Configuration & Date Setup
let fromDate = positionalArgs[0];
let toDate = positionalArgs[1];
let isCustomRange = true;

if (!fromDate || !toDate) {
    isCustomRange = false;
    const todayObj = new Date();
    const yesterdayObj = new Date();
    yesterdayObj.setDate(todayObj.getDate() - 1);
    
    fromDate = yesterdayObj.toISOString().slice(0, 10);
    toDate = todayObj.toISOString().slice(0, 10);
}

const isfuture = positionalArgs[2] || 'F1'; // Default to "F1" futures
const source = "ICICI";
const TABLENAME = "scrapdata_F1";

let checkpointSuffix = "_manisha";
if (process.argv.includes('--start-index')) {
    checkpointSuffix = `_manisha_${startIndex}_${endIndex}`;
}
const CHECKPOINT_FILE = path.join(__dirname, `checkpoint_F1${checkpointSuffix}.json`);

// Clear checkpoint file for fresh daily run
if (!isCustomRange) {
    try {
        if (fs.existsSync(CHECKPOINT_FILE)) {
            fs.unlinkSync(CHECKPOINT_FILE);
            console.log("[Setup] Cleared checkpoint file for fresh daily run.");
        }
    } catch (cpErr) {
        console.error("[Setup Warning] Could not clear checkpoint file:", cpErr.message);
    }
}

// Account Configurations
const ACCOUNT_CONFIGS = {
    Amrit: {
        name: "Amrit",
        appKey: "77059JQ7633PoSc1mk465580B6wp1x04",
        appSecret: "6P9^377d3*412585q(527i3ZgJ437040",
        sessionFile: path.join(parentDir, 'auth', 'icicisession.txt'),
        otpScript: path.join(parentDir, 'auth', '2.OTP_Amrit.py')
    },
    Bineesh: {
        name: "Bineesh",
        appKey: "S945YmT9K3Z4425450K+C205BMZ9$085",
        appSecret: "6P9^377d3*412585q(527i3ZgJ437040",
        sessionFile: "/home/ubuntu/KotakCodes1/ICICI/icici_session_token/icicisession_bineesh.txt",
        otpScript: path.join('/home/ubuntu/KotakCodes1/ICICI', '2.OTP_Bineesh.py')
    }
};

// Start with Amrit, fallback to Manisha
let activeAccountName = "Amrit";
let activeConfig = ACCOUNT_CONFIGS[activeAccountName];
let MASTER_FILE = path.join(parentDir, 'config', 'ICICImaster.csv');

console.log(`=======================================================`);
console.log(`ICICI HIGH-SPEED FUTURE DATA LOADER (AMRIT + MANISHA FALLBACK)`);
console.log(`=======================================================`);
console.log(`Period       : ${fromDate} to ${toDate}`);
console.log(`Type         : ${isfuture}`);
console.log(`Target DB    : markets.${TABLENAME}`);
console.log(`Master File  : ${MASTER_FILE}`);
console.log(`Checkpoint   : ${CHECKPOINT_FILE}`);
console.log(`Start Index  : ${startIndex}`);
console.log(`End Index    : ${endIndex !== null ? endIndex : 'End'}`);
console.log(`Skip Complete: ${skipComplete}`);
console.log(`=======================================================`);

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

function getDatesInRange(startDate, endDate) {
    const dates = [];
    const currentDate = new Date(startDate);
    const lastDate = new Date(endDate);

    while (currentDate <= lastDate) {
        const dayOfWeek = currentDate.getDay();
        if (dayOfWeek !== 0 && dayOfWeek !== 6) { 
            const dateString = currentDate.toISOString().slice(0, 10);
            dates.push(dateString);
        }
        currentDate.setDate(currentDate.getDate() + 1);
    }
    return dates;
}

function getDatesInRangeByYear(startDate, endDate) {
    const yearsData = [];
    let startYear = new Date(startDate).getFullYear();
    let endYear = new Date(endDate).getFullYear();

    for (let year = endYear; year >= startYear; year--) {
        let currentYearStartDate;
        let currentYearEndDate;

        if (year === endYear) {
            currentYearStartDate = (year === startYear) ? startDate : `${year}-01-01`;
            currentYearEndDate = endDate;
        } else if (year === startYear) {
            currentYearStartDate = startDate;
            currentYearEndDate = `${year}-12-31`;
        } else {
            currentYearStartDate = `${year}-01-01`;
            currentYearEndDate = `${year}-12-31`;
        }
        yearsData.push({
            year: year,
            dates: getDatesInRange(currentYearStartDate, currentYearEndDate)
        });
    }
    return yearsData;
}

function resetTime(date) {
    const d = new Date(date);
    d.setHours(0, 0, 0, 0);
    return d;
}

const expiryDatesList = [
    "27 Jan 2011","24 Feb 2011","31 Mar 2011","28 Apr 2011","26 May 2011","30 Jun 2011","28 Jul 2011","25 Aug 2011","29 Sep 2011","25 Oct 2011","24 Nov 2011","29 Dec 2011",
    "25 Jan 2012","23 Feb 2012","29 Mar 2012","26 Apr 2012","31 May 2012","28 Jun 2012","26 Jul 2012","30 Aug 2012","27 Sep 2012","25 Oct 2012","29 Nov 2012","27 Dec 2012",
    "31 Jan 2013","28 Feb 2013","28 Mar 2013","25 Apr 2013","30 May 2013","27 Jun 2013","25 jul 2013","29 Aug 2013","26 Sep 2013","31 Oct 2013","28 Nov 2013","26 Dec 2013",
    "30 Jan 2014","26 Feb 2014","27 Mar 2014","24 Apr 2014","29 May 2014","26 Jun 2014","31 Jul 2014","28 Aug 2014","25 Sep 2014","30 Oct 2014","27 Nov 2014","24 Dec 2014",
    "29 Jan 2015","26 Feb 2015","26 Mar 2015","30 Apr 2015","28 May 2015","25 Jun 2015","30 Jul 2015","27 Aug 2015","24 Sep 2015","29 Oct 2015","26 Nov 2015","31 Dec 2015",
    "28 Jan 2016","25 Feb 2016","31 Mar 2016","28 Apr 2016","26 May 2016","30 Jun 2016","28 Jul 2016","25 Aug 2016","29 Sep 2016","27 Oct 2016","24 Nov 2016","29 Dec 2016",
    "25 Jan 2017","23 Feb 2017","30 Mar 2017","27 Apr 2017","25 May 2017","29 Jun 2017","27 Jul 2017","31 Aug 2017","28 Sep 2017","26 Oct 2017","30 Nov 2017","28 Dec 2017",
    "25 Jan 2018","22 Feb 2018","28 Mar 2018","26 Apr 2018","31 May 2018","28 Jun 2018","26 Jul 2018","30 Aug 2018","27 Sep 2018","25 Oct 2018","29 Nov 2018","27 Dec 2018",
    "31 Jan 2019","28 Feb 2019","28 Mar 2019","25 Apr 2019","30 May 2019","27 Jun 2019","25 Jul 2019","29 Aug 2019","26 Sep 2019","24 Oct 2019","28 Nov 2019","26 Dec 2019",
    "30 Jan 2020","27 Feb 2020","26 Mar 2020","30 Apr 2020","28 May 2020","25 Jun 2020","30 Jul 2020","27 Aug 2020","24 Sep 2020","29 Oct 2020","26 Nov 2020","31 Dec 2020",
    "28 Jan 2021","25 Feb 2021","25 Mar 2021","29 Apr 2021","27 May 2021","24 Jun 2021","29 Jul 2021","26 Aug 2021","30 Sep 2021","28 Oct 2021","25 Nov 2021","30 Dec 2021",
    "27 Jan 2022","24 Feb 2022","31 Mar 2022","28 Apr 2022","26 May 2022","30 Jun 2022","28 Jul 2022","25 Aug 2022","29 Sep 2022","27 Oct 2022","24 Nov 2022","29 Dec 2022",
    "25 Jan 2023","23 Feb 2023","29 Mar 2023","27 Apr 2023","25 May 2023","28 Jun 2023","27 Jul 2023","31 Aug 2023","28 Sep 2023","26 Oct 2023","30 Nov 2023","28 Dec 2023",
    "25 Jan 2024","29 Feb 2024","28 Mar 2024","25 Apr 2024","30 May 2024","27 Jun 2024","25 Jul 2024","29 Aug 2024","26 Sep 2024","31 Oct 2024","28 Nov 2024","26 Dec 2024",
    "30 Jan 2025","27 Feb 2025","27 Mar 2025","24 Apr 2025","29 May 2025","26 Jun 2025","31 Jul 2025","28 Aug 2025","30 Sep 2025","28 Oct 2025","25 Nov 2025","30 Dec 2025",
    "27 Jan 2026","24 Feb 2026","31 Mar 2026","28 Apr 2026","26 May 2026","30 Jun 2026","28 Jul 2026","25 Aug 2026","29 Sep 2026","27 Oct 2026","24 Nov 2026","29 Dec 2026"
];

function getExpiryDate(expiryDatesList, today) {
    const todayReset = resetTime(today);
    const expiryDates = expiryDatesList.map(dateStr => resetTime(new Date(dateStr)));

    let futurecounter = 1;
    if (isfuture.startsWith("F")) {
        futurecounter = parseInt(isfuture.substring(1));
    }

    const validExpiries = expiryDates.filter(expDate => todayReset <= expDate);

    if (validExpiries.length >= futurecounter) {
        return validExpiries[futurecounter - 1].addHours(23).toISOString().slice(0, 10);
    } else {
        return expiryDates[expiryDates.length - 1].addHours(23).toISOString().slice(0, 10);
    }
}

Date.prototype.addHours = function (h) {
    this.setTime(this.getTime() + (h * 60 * 60 * 1000));
    return this;
};

function withTimeout(promise, ms, errorMessage = "Timeout exceeded") {
    let timeoutId;
    const timeoutPromise = new Promise((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error(errorMessage)), ms);
    });
    return Promise.race([promise, timeoutPromise]).finally(() => clearTimeout(timeoutId));
}

function readTextFileSync(filePath) {
    try {
        const data = fs.readFileSync(filePath, 'utf8');
        return data.trim();
    } catch (err) {
        return null;
    }
}

function saveCheckpoint(year, stockCode) {
    fs.writeFileSync(CHECKPOINT_FILE, JSON.stringify({ year, stockCode }, null, 2), 'utf8');
}

function loadCheckpoint() {
    if (fs.existsSync(CHECKPOINT_FILE)) {
        try {
            return JSON.parse(fs.readFileSync(CHECKPOINT_FILE, 'utf8'));
        } catch (e) {
            return null;
        }
    }
    return null;
}

// Database configuration
const dbConfig = {
    host: 'localhost',
    user: 'root',
    password: 'root',
    database: 'markets'
};

const startTime = new Date();
const connection = mysql.createConnection(dbConfig);

let breeze = new BreezeConnect({ "appKey": activeConfig.appKey });

// --- Single-Flight global session renewal mechanism with Failover to Manisha ---
let isRenewingSession = false;
let sessionRenewPromise = null;
let globalRenewalCount = 0;
const MAX_GLOBAL_RENEWAL_ATTEMPTS = 2;

async function switchAccount(accountName) {
    console.log(`\n=======================================================`);
    console.log(`[Account Failover] Switching active account to ${accountName}`);
    console.log(`=======================================================`);
    activeAccountName = accountName;
    activeConfig = ACCOUNT_CONFIGS[activeAccountName];
    breeze = new BreezeConnect({ "appKey": activeConfig.appKey });
    globalRenewalCount = 0; // reset retry counter for fallback account
}

async function renewSessionGlobal() {
    if (isRenewingSession) {
        return sessionRenewPromise;
    }

    isRenewingSession = true;
    sessionRenewPromise = (async () => {
        try {
            globalRenewalCount++;
            console.log(`\n[Session Lock] Session issue detected on ${activeAccountName} account (Attempt ${globalRenewalCount}/${MAX_GLOBAL_RENEWAL_ATTEMPTS}). Launching ${activeConfig.otpScript}...`);
            
            await new Promise((resolve, reject) => {
                exec(`python3 "${activeConfig.otpScript}" --force`, { cwd: parentDir }, (error, stdout, stderr) => {
                    if (error) return reject(error);
                    resolve();
                });
            });

            const session_key = readTextFileSync(activeConfig.sessionFile);
            await withTimeout(breeze.generateSession(activeConfig.appSecret, session_key), 15000);
            console.log(`[Session Lock] Successfully authenticated ${activeAccountName} with refreshed session key.`);
        } catch (e) {
            console.error(`[Session Lock] Error renewing session for ${activeAccountName}:`, e.message || e);
            
            // If primary (Amrit) failed or hit quota limit, failover to Bineesh account
            if (activeAccountName === "Amrit") {
                console.warn(`[Failover Triggered] Amrit account failed session renewal. Falling back to Bineesh account...`);
                await switchAccount("Bineesh");
                return renewSessionGlobal();
            }

            // If Manisha account also failed or exceeded limit, exit cleanly
            if (isQuotaExceededError(null, e)) {
                console.error("[Session Lock] All ICICI Daily API Quotas Exceeded. Exiting pipeline.");
                process.exit(1);
            }
            if (globalRenewalCount >= MAX_GLOBAL_RENEWAL_ATTEMPTS) {
                console.error("[Session Lock] Aborting pipeline run due to repeated renewal failures across all accounts.");
                process.exit(1);
            }
            throw e;
        } finally {
            isRenewingSession = false;
            sessionRenewPromise = null;
        }
    })();

    return sessionRenewPromise;
}

async function generateAndAuthenticateSession() {
    let session_key = readTextFileSync(activeConfig.sessionFile);
    console.log(`[Session] Account: ${activeAccountName} | Initial session key:`, session_key ? session_key : "(none)");

    try {
        await withTimeout(breeze.generateSession(activeConfig.appSecret, session_key), 15000);
        console.log(`[Session] Initial session authentication successful for ${activeAccountName}.`);
    } catch (e) {
        console.warn(`[Session Warning] Initial session authentication failed for ${activeAccountName} (${e.message || e}). Attempting renewal/failover...`);
        if (activeAccountName === "Amrit" && isQuotaExceededError(null, e)) {
            console.warn(`[Quota Exceeded] Amrit account daily API quota hit. Switching directly to Manisha account...`);
            await switchAccount("Manisha");
        }
        await renewSessionGlobal();
    }
}

function fetchBreezeData(stockCode, expiryDate, fromDateIso, toDateIso) {
    return new Promise((resolve, reject) => {
        breeze.getHistoricalDatav2({
            interval: "1minute",
            fromDate: fromDateIso,
            toDate: toDateIso,
            stockCode: stockCode,
            exchangeCode: "NFO",
            productType: "futures",
            expiryDate: expiryDate,
            right: "others",
            strikePrice: "0"
        }).then(res => resolve(res)).catch(err => reject(err));
    });
}

function runDataFetcherPipeline() {
    return new Promise((resolve, reject) => {
        let rows = [];

        fs.createReadStream(MASTER_FILE)
            .pipe(csv({ headers: false }))
            .on('data', (data) => rows.push(data))
            .on('end', async () => {
                // De-duplicate rows by standard stockCode (row[6]) to process each stock exactly once (nearest contract)
                const uniqueRows = [];
                const seenStocks = new Set();
                for (const row of rows) {
                    if (row[0] === 'Token' || row[6] === 'stockCodes') continue;
                    const stockCode = row[6] ? row[6].trim() : '';
                    if (!stockCode) continue;
                    if (!seenStocks.has(stockCode)) {
                        seenStocks.add(stockCode);
                        uniqueRows.push(row);
                    }
                }
                console.log(`[Master CSV] Total records loaded: ${rows.length} | Unique stocks: ${uniqueRows.length}`);

                const slicedRows = uniqueRows.slice(startIndex, endIndex !== null ? endIndex : uniqueRows.length);
                console.log(`[Processing] Processing ${slicedRows.length} unique stocks (Index range: ${startIndex} to ${endIndex !== null ? endIndex : uniqueRows.length - 1})`);

                // ── PRE-DELETE TARGET DATES TO PREVENT DUPLICATE ENTRIES ──
                await new Promise((resDel, rejDel) => {
                    const delSql = `DELETE FROM ${TABLENAME} WHERE date BETWEEN ? AND ?`;
                    connection.query(delSql, [fromDate, toDate], (errDel, resDelQuery) => {
                        if (errDel) {
                            console.error(`[DB Pre-Delete Warning] Could not delete old records:`, errDel.message);
                        } else {
                            console.log(`[DB Pre-Delete] Cleared ${resDelQuery.affectedRows} existing rows for range ${fromDate} to ${toDate} from ${TABLENAME}.`);
                        }
                        resDel();
                    });
                });

                const checkpoint = loadCheckpoint();
                let isResumeYear = false;
                let isResumeStock = false;

                if (checkpoint) {
                    console.log(`[Checkpoint] Found existing checkpoint: Year=${checkpoint.year}, Stock=${checkpoint.stockCode}`);
                    isResumeYear = true;
                    isResumeStock = true;
                }

                const yearsDataList = getDatesInRangeByYear(fromDate, toDate);

                for (let yearObj of yearsDataList) {
                    const currentYear = yearObj.year;
                    const dateListForYear = yearObj.dates;

                    if (isResumeYear && currentYear > checkpoint.year) {
                        console.log(`[Checkpoint] Skipping year ${currentYear} (already processed in previous run)`);
                        continue;
                    }
                    if (isResumeYear && currentYear === checkpoint.year) {
                        isResumeYear = false; 
                    }

                    for (let index = 0; index < slicedRows.length; index++) {
                        const row = slicedRows[index];
                        // If row contains the header string 'Token' or 'stockCodes', skip it
                        if (row[0] === 'Token' || row[6] === 'stockCodes') continue;
                        
                        const stockCode = row[6] ? row[6].trim() : '';
                        const iciciSymbol = row[2] ? row[2].trim() : '';

                        if (!stockCode || !iciciSymbol) continue;

                        if (isResumeStock) {
                            if (stockCode === checkpoint.stockCode) {
                                isResumeStock = false; 
                                console.log(`[Checkpoint] Resuming execution starting from stock: ${stockCode}`);
                            } else {
                                console.log(`[Checkpoint] Skipping already processed stock: ${stockCode}`);
                                continue;
                            }
                        }

                        for (let dateStr of dateListForYear) {
                            const today = new Date(dateStr);
                            const expiryDateIso = getExpiryDate(expiryDatesList, today);
                            const expiryDateFormatted = `${expiryDateIso}T07:00:00.000Z`;

                            const fromDateIso = `${dateStr}T00:00:00.000Z`;
                            const toDateIso = `${dateStr}T23:59:59.000Z`;

                            const actualIndex = startIndex + index;
                            console.log(`[Fetch] [Acc:${activeAccountName}] (${actualIndex + 1}/${uniqueRows.length}) Stock: ${stockCode} (ICICI: ${iciciSymbol}) | Date: ${dateStr} | Expiry: ${expiryDateIso}`);

                            let breezeResponse = null;
                            let fetchSuccess = false;
                            let attempts = 0;

                            while (!fetchSuccess && attempts < 3) {
                                attempts++;
                                try {
                                    breezeResponse = await withTimeout(
                                        fetchBreezeData(iciciSymbol, expiryDateFormatted, fromDateIso, toDateIso),
                                        15000,
                                        `Timeout fetching data for ${stockCode} (ICICI: ${iciciSymbol}) on ${dateStr}`
                                    );

                                    if (isSessionError(breezeResponse, null)) {
                                        console.warn(`[Session Expired] Account ${activeAccountName} session error on ${stockCode}. Renewing...`);
                                        await renewSessionGlobal();
                                        continue; 
                                    }

                                    if (isQuotaExceededError(breezeResponse, null)) {
                                        console.warn(`[Quota Exceeded] ${activeAccountName} quota exceeded. Triggering failover...`);
                                        if (activeAccountName === "Amrit") {
                                            await switchAccount("Manisha");
                                            await renewSessionGlobal();
                                            continue;
                                        } else {
                                            console.error("[Fatal] All available ICICI accounts have exceeded daily API limits.");
                                            process.exit(1);
                                        }
                                    }

                                    fetchSuccess = true;
                                } catch (fetchErr) {
                                    console.error(`[Fetch Error] Attempt ${attempts}/3 failed for ${stockCode} on ${dateStr}: ${fetchErr.message || fetchErr}`);

                                    if (isSessionError(null, fetchErr)) {
                                        console.warn(`[Session Expired Error] Session error detected. Renewing/Failing over...`);
                                        await renewSessionGlobal();
                                        continue;
                                    }

                                    if (isQuotaExceededError(null, fetchErr)) {
                                        if (activeAccountName === "Amrit") {
                                            await switchAccount("Manisha");
                                            await renewSessionGlobal();
                                            continue;
                                        } else {
                                            console.error("[Fatal] All available ICICI accounts exceeded daily quota.");
                                            process.exit(1);
                                        }
                                    }

                                    if (attempts < 3) {
                                        console.log(`[Retry] Waiting 2 seconds before retry ${attempts + 1}...`);
                                        await new Promise(res => setTimeout(res, 2000));
                                    }
                                }
                            }

                            if (!fetchSuccess || !breezeResponse) {
                                console.error(`[Fetch Failed] Skipping stock ${stockCode} for ${dateStr} after 3 failed attempts.`);
                                continue;
                            }

                            const responseData = breezeResponse.Success || breezeResponse.success || [];

                            if (Array.isArray(responseData) && responseData.length > 0) {
                                console.log(`[Data Received] Received ${responseData.length} minute bars for ${stockCode}. Inserting to DB...`);

                                const insertValues = responseData.map(item => {
                                    const rawDate = item.datetime || item.datetime_val || '';
                                    const formattedDate = rawDate ? rawDate.replace('T', ' ').replace('.000Z', '') : dateStr;

                                    return [
                                        stockCode,
                                        formattedDate, // maps to 'time'
                                        dateStr,       // maps to 'date'
                                        parseFloat(item.open || 0),
                                        parseFloat(item.high || 0),
                                        parseFloat(item.low || 0),
                                        parseFloat(item.close || 0),
                                        parseFloat(item.close || 0), // maps to 'price'
                                        parseInt(item.volume || 0, 10),
                                        parseInt(item.open_interest || item.open_interest_val || 0, 10),
                                        source,
                                        isfuture,      // maps to 'is_future'
                                        "TRUE"         // maps to 'isvalid'
                                    ];
                                });

                                const sql = `
                                    INSERT INTO ${TABLENAME} 
                                    (stockname, time, date, open, high, low, close, price, volume, open_interest, source, is_future, isvalid) 
                                    VALUES ? 
                                    ON DUPLICATE KEY UPDATE 
                                        open = VALUES(open), 
                                        high = VALUES(high), 
                                        low = VALUES(low), 
                                        close = VALUES(close), 
                                        price = VALUES(price),
                                        volume = VALUES(volume), 
                                        open_interest = VALUES(open_interest);
                                `;

                                await new Promise((resQuery, rejQuery) => {
                                    connection.query(sql, [insertValues], (errQuery, result) => {
                                        if (errQuery) {
                                            console.error(`[DB Error] Failed to insert data for ${stockCode} on ${dateStr}:`, errQuery.message);
                                            rejQuery(errQuery);
                                        } else {
                                            console.log(`[DB Insert] Successfully processed ${result.affectedRows} rows for ${stockCode}.`);
                                            resQuery(result);
                                        }
                                    });
                                });
                            } else {
                                console.log(`[No Data] Zero records returned for ${stockCode} on ${dateStr}.`);
                            }

                            saveCheckpoint(currentYear, stockCode);
                        }
                    }
                }

                resolve();
            })
            .on('error', (err) => reject(err));
    });
}

async function main() {
    try {
        await generateAndAuthenticateSession();
        await runDataFetcherPipeline();
        console.log(`\n[Pipeline Complete] Data download pipeline finished successfully.`);
    } catch (err) {
        console.error(`[Fatal Pipeline Error]:`, err);
    } finally {
        connection.end();
        const duration = ((new Date() - startTime) / 1000).toFixed(2);
        console.log(`[Execution Stats] Total execution time: ${duration} seconds.`);
    }
}

main();
